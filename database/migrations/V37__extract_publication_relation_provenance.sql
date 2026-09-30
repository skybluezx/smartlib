SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Domain provenance uses real foreign keys; the generic relation has no paper column.
CREATE TABLE smartlib.publication_relation_provenance (
    relation_id uuid PRIMARY KEY REFERENCES smartlib.relation_assertion(relation_id) ON DELETE CASCADE,
    publication_authorship_id uuid REFERENCES smartlib.publication_authorship(publication_authorship_id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO smartlib.publication_relation_provenance(relation_id,publication_authorship_id)
SELECT relation_id,source_publication_authorship_id FROM smartlib.relation_assertion
WHERE source_publication_authorship_id IS NOT NULL;
CREATE INDEX publication_relation_provenance_authorship_idx ON smartlib.publication_relation_provenance(publication_authorship_id);
ALTER TABLE smartlib.publication_relation_provenance ENABLE ROW LEVEL SECURITY;
CREATE POLICY publication_relation_provenance_read ON smartlib.publication_relation_provenance
FOR SELECT TO smartlib_app,smartlib_readonly USING (EXISTS (
 SELECT 1 FROM smartlib.relation_assertion r WHERE r.relation_id=publication_relation_provenance.relation_id));
CREATE POLICY publication_relation_provenance_write ON smartlib.publication_relation_provenance
FOR ALL TO smartlib_app USING (EXISTS (
 SELECT 1 FROM smartlib.relation_assertion r WHERE r.relation_id=publication_relation_provenance.relation_id
 AND r.created_by=smartlib.current_actor_id())) WITH CHECK (EXISTS (
 SELECT 1 FROM smartlib.relation_assertion r WHERE r.relation_id=publication_relation_provenance.relation_id
 AND r.created_by=smartlib.current_actor_id()));
GRANT SELECT,INSERT,UPDATE,DELETE ON smartlib.publication_relation_provenance TO smartlib_app;
GRANT SELECT ON smartlib.publication_relation_provenance TO smartlib_readonly;
CREATE FUNCTION smartlib.publication_relation_authorship(p_relation_id uuid) RETURNS uuid
LANGUAGE sql STABLE SET search_path=pg_catalog,smartlib AS $$
 SELECT publication_authorship_id FROM smartlib.publication_relation_provenance WHERE relation_id=p_relation_id
$$;
REVOKE ALL ON FUNCTION smartlib.publication_relation_authorship(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.publication_relation_authorship(uuid) TO smartlib_app,smartlib_readonly;


CREATE OR REPLACE FUNCTION smartlib.validate_person_affiliation_snapshot(p_relation_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    selected_relation smartlib.relation_assertion%ROWTYPE;
BEGIN
    SELECT * INTO selected_relation
      FROM smartlib.relation_assertion
     WHERE relation_id = p_relation_id;
    IF NOT FOUND OR selected_relation.predicate <> 'person.affiliated_with'
       OR selected_relation.review_state <> 'approved'
       OR selected_relation.system_to <> 'infinity'::timestamptz THEN
        RETURN;
    END IF;
    IF selected_relation.object_id IS NULL
       OR selected_relation.context_object_id IS NULL
       OR smartlib.publication_relation_authorship(selected_relation.relation_id) IS NULL THEN
        RAISE EXCEPTION 'approved person affiliation requires organization, publication context and authorship'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM smartlib.knowledge_object person,
               smartlib.knowledge_object organization,
               smartlib.knowledge_object publication
         WHERE person.object_id = selected_relation.subject_id
           AND person.object_type = 'person'
           AND person.system_to = 'infinity'::timestamptz
           AND organization.object_id = selected_relation.object_id
           AND organization.object_type = 'organization'
           AND organization.system_to = 'infinity'::timestamptz
           AND publication.object_id = selected_relation.context_object_id
           AND publication.object_type = 'publication'
           AND publication.system_to = 'infinity'::timestamptz
    ) THEN
        RAISE EXCEPTION 'approved person affiliation endpoints must be active person, organization and publication objects'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM smartlib.publication_authorship authorship
         WHERE authorship.publication_authorship_id =
               smartlib.publication_relation_authorship(selected_relation.relation_id)
           AND authorship.publication_id = selected_relation.context_object_id
           AND authorship.person_object_id = selected_relation.subject_id
           AND authorship.verification_status <> 'rejected'
    ) THEN
        RAISE EXCEPTION 'affiliation snapshot authorship must match its person and publication'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM smartlib.relation_evidence link
          JOIN smartlib.evidence_record evidence
            ON evidence.evidence_id = link.evidence_id
          JOIN smartlib.publication_fulltext_resource fulltext
            ON fulltext.fulltext_resource_id = evidence.fulltext_resource_id
         WHERE link.relation_id = selected_relation.relation_id
           AND evidence.evidence_kind = 'author_affiliation'
           AND evidence.verification_state = 'confirmed'
           AND evidence.object_id = selected_relation.context_object_id
           AND fulltext.publication_id = selected_relation.context_object_id
    ) THEN
        RAISE EXCEPTION 'approved affiliation snapshot requires confirmed PDF affiliation evidence'
            USING ERRCODE = '23514';
    END IF;
END
$function$;

CREATE OR REPLACE FUNCTION smartlib.guard_person_authored_projection() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE a jsonb; current_relation smartlib.relation_assertion%ROWTYPE;
BEGIN
    SELECT * INTO current_relation FROM smartlib.relation_assertion WHERE relation_id=NEW.relation_id;
    IF NOT FOUND THEN RETURN NEW; END IF;
    IF current_relation.predicate<>'person.authored' THEN RETURN NEW; END IF;
    a=smartlib.authored_authority_attributes(current_relation.object_id,current_relation.subject_id);
    IF current_relation.review_state IN ('rejected','superseded') THEN
        IF a IS NOT NULL THEN RAISE EXCEPTION 'change authorship authority before retiring its projection' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    IF a IS NULL OR current_relation.review_state<>'approved' OR current_relation.fact_class<>'literature_fact'
       OR smartlib.publication_relation_authorship(current_relation.relation_id) IS DISTINCT FROM (a->>'canonical_authorship_id')::uuid
       OR EXISTS (SELECT 1 FROM jsonb_each(a) e WHERE current_relation.attributes->e.key IS DISTINCT FROM e.value) THEN
        RAISE EXCEPTION 'person.authored fields must match verified authorship authority' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION smartlib.refresh_person_authored_relation(p_publication_id uuid,p_person_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE a jsonb; r smartlib.relation_assertion%ROWTYPE; actor uuid; relation_key uuid;
BEGIN
    IF p_publication_id IS NULL OR p_person_id IS NULL THEN RETURN; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_publication_id::text||':'||p_person_id::text,0));
    a=smartlib.authored_authority_attributes(p_publication_id,p_person_id);
    SELECT * INTO r FROM smartlib.relation_assertion WHERE predicate='person.authored'
      AND subject_id=p_person_id AND object_id=p_publication_id AND system_to='infinity'::timestamptz FOR UPDATE;
    IF a IS NULL THEN
        IF r.relation_id IS NOT NULL AND r.review_state NOT IN ('superseded','rejected') THEN
            UPDATE smartlib.relation_assertion SET review_state='superseded',version=version+1
              WHERE relation_id=r.relation_id;
        END IF;
        RETURN;
    END IF;
    IF r.relation_id IS NOT NULL THEN
        UPDATE smartlib.relation_assertion SET attributes=attributes||a,
            review_state='approved',fact_class='literature_fact',model_version='authorship-authority-v2',version=version+1
        WHERE relation_id=r.relation_id AND (NOT(attributes @> a) OR review_state<>'approved'
            OR smartlib.publication_relation_authorship(r.relation_id) IS DISTINCT FROM (a->>'canonical_authorship_id')::uuid);
        relation_key=r.relation_id;
    ELSE
        SELECT created_by INTO actor FROM smartlib.publication_authorship
          WHERE publication_authorship_id=(a->>'canonical_authorship_id')::uuid;
        INSERT INTO smartlib.relation_assertion(subject_id,predicate,object_id,fact_class,confidence,
            visibility,review_state,model_version,attributes,created_by)
        VALUES(p_person_id,'person.authored',p_publication_id,'literature_fact',NULL,'restricted','approved',
            'authorship-authority-v2',a,actor) RETURNING relation_id INTO relation_key;
    END IF;
    INSERT INTO smartlib.publication_relation_provenance(relation_id,publication_authorship_id)
    VALUES(relation_key,(a->>'canonical_authorship_id')::uuid)
    ON CONFLICT(relation_id) DO UPDATE SET publication_authorship_id=EXCLUDED.publication_authorship_id
    WHERE publication_relation_provenance.publication_authorship_id IS DISTINCT FROM EXCLUDED.publication_authorship_id;
END $$;

CREATE OR REPLACE VIEW smartlib.authorship_relation_sync_state AS
WITH pairs AS (
    SELECT DISTINCT publication_id,person_object_id FROM smartlib.publication_authorship WHERE person_object_id IS NOT NULL
    UNION SELECT object_id,subject_id FROM smartlib.relation_assertion WHERE predicate='person.authored'
), states AS (
    SELECT p.*,smartlib.authored_authority_attributes(p.publication_id,p.person_object_id) AS a,
        (SELECT count(*)::integer FROM smartlib.publication_authorship s WHERE s.publication_id=p.publication_id
           AND s.person_object_id=p.person_object_id AND s.match_status='matched'
           AND s.verification_status IN ('matched','corrected')) AS occurrences
    FROM pairs p
)
SELECT s.publication_id,s.person_object_id,s.occurrences AS authorship_occurrence_count,
    count(r.relation_id)::integer AS graph_relation_count,
    COALESCE(bool_and(smartlib.publication_relation_authorship(r.relation_id) IS NOT NULL),false) AS linked_to_authority,
    CASE WHEN s.a IS NULL AND count(r.relation_id)=0 THEN 'synchronized'
         WHEN s.a IS NULL THEN 'graph_without_authority'
         WHEN count(r.relation_id)=0 THEN 'authority_without_graph'
         WHEN count(r.relation_id)<>1 THEN 'duplicate_graph_relation'
         WHEN NOT bool_and(r.attributes @> s.a AND smartlib.publication_relation_authorship(r.relation_id)=(s.a->>'canonical_authorship_id')::uuid
             AND r.review_state='approved' AND r.fact_class='literature_fact') THEN 'authority_content_drift'
         ELSE 'synchronized' END AS sync_state
FROM states s LEFT JOIN smartlib.relation_assertion r ON r.object_id=s.publication_id AND r.subject_id=s.person_object_id
    AND r.predicate='person.authored' AND r.review_state IN ('approved','pending') AND r.system_to='infinity'::timestamptz
GROUP BY s.publication_id,s.person_object_id,s.occurrences,s.a;

CREATE OR REPLACE FUNCTION smartlib_projection.graph_relation_json(p_relation_id uuid)
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
    SELECT jsonb_build_object(
        'relation_id', relation.relation_id,
        'subject_id', relation.subject_id,
        'object_id', relation.object_id,
        'context_object_id', relation.context_object_id,
        'predicate', relation.predicate,
        'fact_class', relation.fact_class,
        'confidence', relation.confidence,
        'review_state', relation.review_state,
        'visibility', relation.visibility,
        'created_by', relation.created_by,
        'relation_version', relation.version,
        'projection_version', 'graph-projection-v3-domain-provenance',
        'attributes', relation.attributes,
        'evidence_ids_all', COALESCE((
            SELECT jsonb_agg(evidence.evidence_id ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_visibilities', COALESCE((
            SELECT jsonb_agg(evidence.visibility ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb),
        'evidence_created_by', COALESCE((
            SELECT jsonb_agg(evidence.created_by ORDER BY evidence.evidence_id)
              FROM smartlib.relation_evidence link
              JOIN smartlib.evidence_record evidence
                ON evidence.evidence_id = link.evidence_id
             WHERE link.relation_id = relation.relation_id
        ), '[]'::jsonb)
    )
      FROM smartlib.relation_assertion relation
     WHERE relation.relation_id = p_relation_id
       AND relation.object_id IS NOT NULL
       AND relation.review_state IN ('pending', 'approved')
       AND relation.system_to = 'infinity'::timestamptz
$function$;


DROP TRIGGER person_authored_projection_guard ON smartlib.relation_assertion;
CREATE CONSTRAINT TRIGGER person_authored_projection_guard AFTER INSERT OR UPDATE ON smartlib.relation_assertion
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.guard_person_authored_projection();

CREATE FUNCTION smartlib.validate_publication_relation_provenance() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE k uuid; r smartlib.relation_assertion%ROWTYPE; a jsonb; source_id uuid;
BEGIN
 k=COALESCE(NEW.relation_id,OLD.relation_id);
 SELECT * INTO r FROM smartlib.relation_assertion WHERE relation_id=k;
 IF NOT FOUND THEN RETURN NULL; END IF;
 source_id=smartlib.publication_relation_authorship(k);
 IF source_id IS NOT NULL AND r.review_state IN ('pending','approved') AND r.system_to='infinity'::timestamptz AND NOT EXISTS (
   SELECT 1 FROM smartlib.publication_authorship s WHERE s.publication_authorship_id=source_id
   AND s.person_object_id=r.subject_id AND s.publication_id=CASE WHEN r.predicate='person.authored' THEN r.object_id ELSE r.context_object_id END
   AND r.predicate IN ('person.authored','person.affiliated_with')) THEN
   RAISE EXCEPTION 'publication provenance must match relation person, publication and predicate' USING ERRCODE='23514';
 END IF;
 IF r.predicate='person.authored' AND r.review_state IN ('pending','approved') AND r.system_to='infinity'::timestamptz THEN
   a=smartlib.authored_authority_attributes(r.object_id,r.subject_id);
   IF a IS NULL OR source_id IS DISTINCT FROM (a->>'canonical_authorship_id')::uuid THEN
     RAISE EXCEPTION 'authored provenance must match verified authority' USING ERRCODE='23514';
   END IF;
 END IF;
 PERFORM smartlib.validate_person_affiliation_snapshot(k);
 IF source_id IS NOT NULL AND r.predicate='person.affiliated_with' AND r.review_state IN ('pending','approved')
    AND r.system_to='infinity'::timestamptz THEN
   PERFORM pg_advisory_xact_lock(hashtextextended(source_id::text||':'||r.object_id::text,0));
   IF EXISTS (SELECT 1 FROM smartlib.publication_relation_provenance p JOIN smartlib.relation_assertion other USING(relation_id)
     WHERE p.publication_authorship_id=source_id AND other.relation_id<>k AND other.predicate=r.predicate
     AND other.object_id=r.object_id AND other.subject_id=r.subject_id AND other.context_object_id=r.context_object_id
     AND other.review_state IN ('pending','approved') AND other.system_to='infinity'::timestamptz) THEN
     RAISE EXCEPTION 'duplicate publication affiliation snapshot' USING ERRCODE='23505';
   END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER publication_provenance_integrity AFTER INSERT OR UPDATE OR DELETE
ON smartlib.publication_relation_provenance DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION smartlib.validate_publication_relation_provenance();
CREATE CONSTRAINT TRIGGER publication_relation_integrity AFTER INSERT OR UPDATE
ON smartlib.relation_assertion DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION smartlib.validate_publication_relation_provenance();
CREATE TRIGGER publication_provenance_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_relation_provenance
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('relation_id');
CREATE FUNCTION smartlib.guard_publication_provenance_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.relation_id<>OLD.relation_id THEN RAISE EXCEPTION 'provenance relation identity is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER publication_provenance_identity BEFORE UPDATE ON smartlib.publication_relation_provenance
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_publication_provenance_identity();
CREATE FUNCTION smartlib.revalidate_authorship_affiliations() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE k uuid;
BEGIN
 FOR k IN SELECT relation_id FROM smartlib.publication_relation_provenance
 WHERE publication_authorship_id=COALESCE(NEW.publication_authorship_id,OLD.publication_authorship_id) LOOP
 PERFORM smartlib.validate_person_affiliation_snapshot(k);
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER authorship_affiliation_integrity AFTER UPDATE OR DELETE ON smartlib.publication_authorship
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.revalidate_authorship_affiliations();
REVOKE ALL ON FUNCTION smartlib.guard_publication_provenance_identity(),smartlib.revalidate_authorship_affiliations() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.guard_publication_provenance_identity() TO smartlib_app;
ALTER TABLE smartlib.relation_assertion DROP COLUMN source_publication_authorship_id;
COMMENT ON TABLE smartlib.publication_relation_provenance IS 'Publication-domain provenance extension; one canonical authorship per relation, all roles remain authoritative in publication_authorship.';
REVOKE ALL ON FUNCTION smartlib.validate_publication_relation_provenance() FROM PUBLIC;
RESET ROLE;
