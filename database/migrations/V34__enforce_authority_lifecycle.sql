SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- History belongs to the authority layer and survives retirement/deletion.
CREATE TABLE smartlib.entity_revision (
    revision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_table text NOT NULL,
    entity_id uuid NOT NULL,
    operation text NOT NULL CHECK(operation IN ('INSERT','UPDATE','DELETE')),
    before_value jsonb,
    after_value jsonb,
    actor_id uuid,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX entity_revision_entity_idx ON smartlib.entity_revision(entity_table,entity_id,recorded_at);
CREATE TRIGGER entity_revision_append_only BEFORE UPDATE OR DELETE ON smartlib.entity_revision
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
REVOKE ALL ON smartlib.entity_revision FROM PUBLIC;

CREATE FUNCTION smartlib.capture_entity_revision() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE b jsonb; a jsonb; k uuid;
BEGIN
    IF TG_OP<>'INSERT' THEN b=to_jsonb(OLD); END IF;
    IF TG_OP<>'DELETE' THEN a=to_jsonb(NEW); END IF;
    k=(COALESCE(a,b)->>TG_ARGV[0])::uuid;
    INSERT INTO smartlib.entity_revision(entity_table,entity_id,operation,before_value,after_value,actor_id)
    VALUES(TG_TABLE_NAME,k,TG_OP,b,a,smartlib.current_actor_id());
    RETURN COALESCE(NEW,OLD);
END $$;

CREATE FUNCTION smartlib.enforce_object_identity_contract() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE target text; expected text;
BEGIN
    IF TG_OP='UPDATE' AND NEW.object_type<>OLD.object_type THEN
        RAISE EXCEPTION 'object type is immutable; use an explicit identity migration' USING ERRCODE='23514';
    END IF;
    IF NEW.object_type IN ('project','journal','funding_program') AND
       (NULLIF(NEW.attributes->>'record_kind','') IS NULL OR NOT EXISTS(
           SELECT 1 FROM smartlib.attribute_definition WHERE entity_kind='object'
            AND entity_type=NEW.object_type AND record_kind=NEW.attributes->>'record_kind'
            AND attribute_key='record_kind' AND lifecycle_state='active')) THEN
        RAISE EXCEPTION 'registered record_kind is required for %',NEW.object_type USING ERRCODE='23514';
    END IF;
    FOREACH target IN ARRAY ARRAY['funding_program_id','principal_investigator_person_id','parent_organization_id'] LOOP
        IF NEW.attributes->>target IS NOT NULL THEN
            expected=CASE target WHEN 'funding_program_id' THEN 'funding_program'
                WHEN 'principal_investigator_person_id' THEN 'person' ELSE 'organization' END;
            IF NOT EXISTS(SELECT 1 FROM smartlib.knowledge_object WHERE object_id::text=NEW.attributes->>target
                AND object_type=expected AND system_to='infinity'::timestamptz) THEN
                RAISE EXCEPTION 'invalid % reference',target USING ERRCODE='23514';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER object_identity_contract BEFORE INSERT OR UPDATE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_object_identity_contract();

-- A matched slot is distinct from a provisional/ambiguous person identity.
CREATE FUNCTION smartlib.authored_authority_attributes(p_publication uuid,p_person uuid) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
    SELECT CASE WHEN count(*)=0 THEN NULL ELSE jsonb_build_object(
        'author_order',min(author_order),
        'author_orders',jsonb_agg(author_order ORDER BY author_order,publication_authorship_id),
        'authorship_ids',jsonb_agg(publication_authorship_id ORDER BY author_order,publication_authorship_id),
        'canonical_authorship_id',(array_agg(publication_authorship_id ORDER BY author_order,publication_authorship_id))[1],
        'roles',to_jsonb(array_remove(ARRAY[
            CASE WHEN bool_or(is_first_author) THEN 'first_author' END,
            CASE WHEN bool_or(is_co_first_author) THEN 'co_first_author' END,
            CASE WHEN bool_or(is_corresponding_author) THEN 'corresponding_author' END,
            CASE WHEN bool_or(is_co_corresponding_author) THEN 'co_corresponding_author' END],NULL)),
        'authority_source','publication_authorship','role_source','publication_authorship',
        'rule_version','authorship-authority-v2','sync_version','authorship-authority-v2') END
    FROM smartlib.publication_authorship
    WHERE publication_id=p_publication AND person_object_id=p_person
      AND match_status='matched' AND verification_status IN ('matched','corrected')
$$;

CREATE OR REPLACE FUNCTION smartlib.guard_person_authored_projection() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE a jsonb;
BEGIN
    IF NEW.predicate<>'person.authored' THEN RETURN NEW; END IF;
    a=smartlib.authored_authority_attributes(NEW.object_id,NEW.subject_id);
    IF NEW.review_state IN ('rejected','superseded') THEN
        IF a IS NOT NULL THEN RAISE EXCEPTION 'change authorship authority before retiring its projection' USING ERRCODE='23514'; END IF;
        RETURN NEW;
    END IF;
    IF a IS NULL OR NEW.review_state<>'approved' OR NEW.fact_class<>'literature_fact'
       OR NEW.source_publication_authorship_id IS DISTINCT FROM (a->>'canonical_authorship_id')::uuid
       OR EXISTS (SELECT 1 FROM jsonb_each(a) e WHERE NEW.attributes->e.key IS DISTINCT FROM e.value) THEN
        RAISE EXCEPTION 'person.authored fields must match verified authorship authority' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER person_authored_projection_guard ON smartlib.relation_assertion;
CREATE TRIGGER person_authored_projection_guard BEFORE INSERT OR UPDATE ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_person_authored_projection();

CREATE OR REPLACE FUNCTION smartlib.refresh_person_authored_relation(p_publication_id uuid,p_person_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE a jsonb; r smartlib.relation_assertion%ROWTYPE; actor uuid;
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
            source_publication_authorship_id=(a->>'canonical_authorship_id')::uuid,
            review_state='approved',fact_class='literature_fact',model_version='authorship-authority-v2',version=version+1
        WHERE relation_id=r.relation_id AND (NOT(attributes @> a) OR review_state<>'approved'
            OR source_publication_authorship_id IS DISTINCT FROM (a->>'canonical_authorship_id')::uuid);
    ELSE
        SELECT created_by INTO actor FROM smartlib.publication_authorship
          WHERE publication_authorship_id=(a->>'canonical_authorship_id')::uuid;
        INSERT INTO smartlib.relation_assertion(subject_id,predicate,object_id,fact_class,confidence,
            visibility,review_state,model_version,attributes,source_publication_authorship_id,created_by)
        VALUES(p_person_id,'person.authored',p_publication_id,'literature_fact',NULL,'restricted','approved',
            'authorship-authority-v2',a,(a->>'canonical_authorship_id')::uuid,actor);
    END IF;
END $$;

-- Journal guard validates actual identity values, with no session-switch bypass.
CREATE OR REPLACE FUNCTION smartlib.guard_materialized_journal_object() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE j smartlib.journal_identity%ROWTYPE;
BEGIN
    IF NEW.object_type<>'journal' THEN RETURN NEW; END IF;
    SELECT * INTO j FROM smartlib.journal_identity WHERE journal_id::text=NEW.attributes->>'journal_identity_id';
    IF NOT FOUND OR (j.knowledge_object_id IS NOT NULL AND j.knowledge_object_id<>NEW.object_id)
       OR NEW.canonical_name IS DISTINCT FROM j.canonical_title
       OR NEW.attributes->>'issn' IS DISTINCT FROM j.issn OR NEW.attributes->>'eissn' IS DISTINCT FROM j.eissn THEN
        RAISE EXCEPTION 'journal object must match its authority identity' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
DROP TRIGGER materialized_journal_object_guard ON smartlib.knowledge_object;
CREATE TRIGGER materialized_journal_object_guard BEFORE INSERT OR UPDATE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_materialized_journal_object();

CREATE FUNCTION smartlib.version_authority_row() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN NEW.version=greatest(NEW.version,OLD.version+1); END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER zz_object_version BEFORE UPDATE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.version_authority_row();
CREATE TRIGGER zz_relation_version BEFORE UPDATE ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.version_authority_row();
CREATE FUNCTION smartlib.emit_authority_event() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE row_value jsonb; k uuid;
BEGIN
    row_value=CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    k=(row_value->>TG_ARGV[0])::uuid;
    INSERT INTO smartlib.outbox_event(aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
    VALUES(TG_TABLE_NAME,k,'knowledge.authority.'||lower(TG_OP),(row_value->>'version')::integer,
        jsonb_build_object('id',k,'version',(row_value->>'version')::bigint),'authority-lifecycle-v2');
    RETURN COALESCE(NEW,OLD);
END $$;
CREATE TRIGGER authority_object_outbox AFTER INSERT OR UPDATE OR DELETE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.emit_authority_event('object_id');
CREATE TRIGGER authority_relation_outbox AFTER INSERT OR UPDATE OR DELETE ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.emit_authority_event('relation_id');
CREATE TRIGGER object_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('object_id');
CREATE TRIGGER relation_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('relation_id');
CREATE TRIGGER authorship_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_authorship
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('publication_authorship_id');
CREATE TRIGGER evidence_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.evidence_record
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('evidence_id');
CREATE TRIGGER metadata_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_metadata
FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('publication_id');

-- Preserve evidence on retirement; reactivation reuses the original relation.
DO $$ DECLARE p record; BEGIN
    FOR p IN SELECT DISTINCT publication_id,person_object_id FROM smartlib.publication_authorship
        WHERE person_object_id IS NOT NULL LOOP
        PERFORM smartlib.refresh_person_authored_relation(p.publication_id,p.person_object_id);
    END LOOP;
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
    COALESCE(bool_and(r.source_publication_authorship_id IS NOT NULL),false) AS linked_to_authority,
    CASE WHEN s.a IS NULL AND count(r.relation_id)=0 THEN 'synchronized'
         WHEN s.a IS NULL THEN 'graph_without_authority'
         WHEN count(r.relation_id)=0 THEN 'authority_without_graph'
         WHEN count(r.relation_id)<>1 THEN 'duplicate_graph_relation'
         WHEN NOT bool_and(r.attributes @> s.a AND r.source_publication_authorship_id=(s.a->>'canonical_authorship_id')::uuid
             AND r.review_state='approved' AND r.fact_class='literature_fact') THEN 'authority_content_drift'
         ELSE 'synchronized' END AS sync_state
FROM states s LEFT JOIN smartlib.relation_assertion r ON r.object_id=s.publication_id AND r.subject_id=s.person_object_id
    AND r.predicate='person.authored' AND r.review_state IN ('approved','pending') AND r.system_to='infinity'::timestamptz
GROUP BY s.publication_id,s.person_object_id,s.occurrences,s.a;

REVOKE ALL ON FUNCTION smartlib.authored_authority_attributes(uuid,uuid),
    smartlib.capture_entity_revision(),smartlib.emit_authority_event(),smartlib.enforce_object_identity_contract() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.authored_authority_attributes(uuid,uuid) TO smartlib_app,smartlib_readonly;
RESET ROLE;
