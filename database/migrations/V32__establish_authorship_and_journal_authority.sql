SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

INSERT INTO smartlib.attribute_definition
    (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,
     required,description,schema_version)
VALUES
    ('relation','person.authored','*','authority_source',ARRAY['string'],true,'权威明细来源，固定为 publication_authorship。','authorship-authority-v1'),
    ('relation','person.authored','*','authorship_ids',ARRAY['array'],true,'支持该去重图关系的全部署名记录ID。','authorship-authority-v1'),
    ('relation','person.authored','*','author_orders',ARRAY['array'],true,'同一人员在论文中的全部署名序号。','authorship-authority-v1'),
    ('relation','person.authored','*','canonical_authorship_id',ARRAY['string'],true,'作为关系上下文锚点的首个署名记录ID。','authorship-authority-v1'),
    ('relation','person.authored','*','sync_version',ARRAY['string'],true,'权威明细到图关系的同步规则版本。','authorship-authority-v1')
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO UPDATE SET
    allowed_json_types=EXCLUDED.allowed_json_types,
    required=EXCLUDED.required,
    description=EXCLUDED.description,
    schema_version=EXCLUDED.schema_version,
    lifecycle_state='active',
    updated_at=clock_timestamp();

INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT gen_random_uuid(),'relation_assertion',relation.relation_id,'knowledge.relation.updated',relation.version,
       jsonb_build_object('relation_id',relation.relation_id,'version',relation.version),
       'authorship-authority-v1:remove-unbacked'
  FROM smartlib.relation_assertion relation
 WHERE relation.predicate='person.authored'
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.publication_authorship authorship
        WHERE authorship.person_object_id=relation.subject_id
          AND authorship.publication_id=relation.object_id
          AND authorship.verification_status<>'rejected'
   );

WITH orphan_relations AS (
    SELECT relation.relation_id
      FROM smartlib.relation_assertion relation
     WHERE relation.predicate='person.authored'
       AND NOT EXISTS (
           SELECT 1 FROM smartlib.publication_authorship authorship
            WHERE authorship.person_object_id=relation.subject_id
              AND authorship.publication_id=relation.object_id
              AND authorship.verification_status<>'rejected'
       )
), deleted_links AS (
    DELETE FROM smartlib.relation_evidence link
     WHERE link.relation_id IN (SELECT relation_id FROM orphan_relations)
    RETURNING link.evidence_id
), deleted_relations AS (
    DELETE FROM smartlib.relation_assertion relation
     WHERE relation.relation_id IN (SELECT relation_id FROM orphan_relations)
    RETURNING relation.relation_id
), deleted_evidence AS (
    DELETE FROM smartlib.evidence_record evidence
     WHERE evidence.evidence_id IN (SELECT evidence_id FROM deleted_links)
       AND NOT EXISTS (
           SELECT 1 FROM smartlib.relation_evidence link
            WHERE link.evidence_id=evidence.evidence_id
       )
       AND NOT EXISTS (
           SELECT 1 FROM smartlib.publication_supplement supplement
            WHERE supplement.evidence_id=evidence.evidence_id
       )
    RETURNING evidence.evidence_id
)
SELECT count(*) FROM deleted_relations;

CREATE UNIQUE INDEX IF NOT EXISTS person_one_authored_relation_idx
    ON smartlib.relation_assertion(subject_id,object_id)
    WHERE predicate='person.authored'
      AND object_id IS NOT NULL
      AND system_to='infinity'::timestamptz;

ALTER TABLE smartlib.relation_assertion
    DROP CONSTRAINT IF EXISTS relation_assertion_source_publication_authorship_id_fkey;
ALTER TABLE smartlib.relation_assertion
    ADD CONSTRAINT relation_assertion_source_publication_authorship_id_fkey
    FOREIGN KEY (source_publication_authorship_id)
    REFERENCES smartlib.publication_authorship(publication_authorship_id)
    ON DELETE SET NULL;

WITH authority AS (
    SELECT authorship.publication_id,authorship.person_object_id,
           (array_agg(authorship.publication_authorship_id
                      ORDER BY authorship.author_order,authorship.publication_authorship_id))[1]
               AS canonical_authorship_id,
           min(authorship.author_order) AS author_order,
           array_agg(authorship.publication_authorship_id
                     ORDER BY authorship.author_order,authorship.publication_authorship_id)
               AS authorship_ids,
           array_agg(authorship.author_order ORDER BY authorship.author_order)
               AS author_orders,
           bool_or(authorship.is_first_author) AS is_first_author,
           bool_or(authorship.is_co_first_author) AS is_co_first_author,
           bool_or(authorship.is_corresponding_author) AS is_corresponding_author,
           bool_or(authorship.is_co_corresponding_author) AS is_co_corresponding_author
      FROM smartlib.publication_authorship authorship
     WHERE authorship.person_object_id IS NOT NULL
       AND authorship.verification_status<>'rejected'
     GROUP BY authorship.publication_id,authorship.person_object_id
), prepared AS (
    SELECT authority.*,
           array_remove(ARRAY[
               CASE WHEN is_first_author THEN 'first_author' END,
               CASE WHEN is_co_first_author THEN 'co_first_author' END,
               CASE WHEN is_corresponding_author THEN 'corresponding_author' END,
               CASE WHEN is_co_corresponding_author THEN 'co_corresponding_author' END
           ],NULL)::text[] AS roles
      FROM authority
), updated AS (
    UPDATE smartlib.relation_assertion relation
       SET source_publication_authorship_id=prepared.canonical_authorship_id,
           fact_class='literature_fact',confidence=1,review_state='approved',
           model_version='authorship-authority-v1',
           attributes=relation.attributes || jsonb_build_object(
               'author_order',prepared.author_order,
               'author_orders',to_jsonb(prepared.author_orders),
               'authorship_ids',to_jsonb(prepared.authorship_ids),
               'canonical_authorship_id',prepared.canonical_authorship_id,
               'roles',to_jsonb(prepared.roles),
               'role_source','publication_authorship',
               'rule_version','authorship-authority-v1',
               'authority_source','publication_authorship',
               'sync_version','authorship-authority-v1'
           ),
           version=relation.version+1,
           updated_at=clock_timestamp()
      FROM prepared
     WHERE relation.predicate='person.authored'
       AND relation.subject_id=prepared.person_object_id
       AND relation.object_id=prepared.publication_id
       AND (
           relation.source_publication_authorship_id IS DISTINCT FROM prepared.canonical_authorship_id
           OR relation.fact_class IS DISTINCT FROM 'literature_fact'
           OR relation.confidence IS DISTINCT FROM 1
           OR relation.review_state IS DISTINCT FROM 'approved'
           OR relation.model_version IS DISTINCT FROM 'authorship-authority-v1'
           OR relation.attributes->>'sync_version' IS DISTINCT FROM 'authorship-authority-v1'
           OR relation.attributes->'authorship_ids' IS DISTINCT FROM to_jsonb(prepared.authorship_ids)
           OR relation.attributes->'author_orders' IS DISTINCT FROM to_jsonb(prepared.author_orders)
           OR relation.attributes->'roles' IS DISTINCT FROM to_jsonb(prepared.roles)
       )
    RETURNING relation.relation_id,relation.version
)
INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT gen_random_uuid(),'relation_assertion',relation_id,'knowledge.relation.updated',version,
       jsonb_build_object('relation_id',relation_id,'version',version),
       'authorship-authority-v1:backfill'
  FROM updated;

CREATE OR REPLACE FUNCTION smartlib.refresh_person_authored_relation(
    p_publication_id uuid,
    p_person_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    authority record;
    selected_relation smartlib.relation_assertion%ROWTYPE;
    selected_relation_id uuid;
    selected_version bigint;
BEGIN
    IF p_publication_id IS NULL OR p_person_id IS NULL THEN
        RETURN;
    END IF;
    SELECT
        (array_agg(authorship.publication_authorship_id
                   ORDER BY authorship.author_order,authorship.publication_authorship_id))[1]
            AS canonical_authorship_id,
        min(authorship.author_order) AS author_order,
        array_agg(authorship.publication_authorship_id
                  ORDER BY authorship.author_order,authorship.publication_authorship_id)
            AS authorship_ids,
        array_agg(authorship.author_order ORDER BY authorship.author_order) AS author_orders,
        array_remove(ARRAY[
            CASE WHEN bool_or(authorship.is_first_author) THEN 'first_author' END,
            CASE WHEN bool_or(authorship.is_co_first_author) THEN 'co_first_author' END,
            CASE WHEN bool_or(authorship.is_corresponding_author) THEN 'corresponding_author' END,
            CASE WHEN bool_or(authorship.is_co_corresponding_author) THEN 'co_corresponding_author' END
        ],NULL)::text[] AS roles,
        (array_agg(authorship.created_by ORDER BY authorship.author_order,
                   authorship.publication_authorship_id))[1] AS created_by
      INTO authority
      FROM smartlib.publication_authorship authorship
     WHERE authorship.publication_id=p_publication_id
       AND authorship.person_object_id=p_person_id
       AND authorship.verification_status<>'rejected';

    PERFORM set_config('smartlib.authorship_relation_sync','on',true);
    IF authority.canonical_authorship_id IS NULL THEN
        FOR selected_relation IN
            DELETE FROM smartlib.relation_assertion
             WHERE predicate='person.authored'
               AND subject_id=p_person_id AND object_id=p_publication_id
            RETURNING *
        LOOP
            INSERT INTO smartlib.outbox_event
                (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
            VALUES ('relation_assertion',selected_relation.relation_id,'knowledge.relation.updated',
                    selected_relation.version,
                    jsonb_build_object('relation_id',selected_relation.relation_id,
                                       'version',selected_relation.version),
                    'authorship-authority-v1:sync-delete');
        END LOOP;
        RETURN;
    END IF;

    SELECT * INTO selected_relation
      FROM smartlib.relation_assertion
     WHERE predicate='person.authored'
       AND subject_id=p_person_id AND object_id=p_publication_id
     FOR UPDATE;
    IF FOUND THEN
        UPDATE smartlib.relation_assertion
           SET source_publication_authorship_id=authority.canonical_authorship_id,
               fact_class='literature_fact',confidence=1,review_state='approved',
               model_version='authorship-authority-v1',
               attributes=attributes || jsonb_build_object(
                   'author_order',authority.author_order,
                   'author_orders',to_jsonb(authority.author_orders),
                   'authorship_ids',to_jsonb(authority.authorship_ids),
                   'canonical_authorship_id',authority.canonical_authorship_id,
                   'roles',to_jsonb(authority.roles),
                   'role_source','publication_authorship',
                   'rule_version','authorship-authority-v1',
                   'authority_source','publication_authorship',
                   'sync_version','authorship-authority-v1'
               ),version=version+1,updated_at=clock_timestamp()
         WHERE relation_id=selected_relation.relation_id
        RETURNING relation_id,version INTO selected_relation_id,selected_version;
    ELSE
        INSERT INTO smartlib.relation_assertion
            (subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,
             review_state,model_version,attributes,source_publication_authorship_id,created_by)
        VALUES (
            p_person_id,'person.authored',p_publication_id,'literature_fact',1,'restricted',
            ARRAY['publication-authorship-authority'],'approved','authorship-authority-v1',
            jsonb_build_object(
                'author_order',authority.author_order,
                'author_orders',to_jsonb(authority.author_orders),
                'authorship_ids',to_jsonb(authority.authorship_ids),
                'canonical_authorship_id',authority.canonical_authorship_id,
                'roles',to_jsonb(authority.roles),
                'role_source','publication_authorship',
                'rule_version','authorship-authority-v1',
                'authority_source','publication_authorship',
                'sync_version','authorship-authority-v1'
            ),authority.canonical_authorship_id,authority.created_by
        ) RETURNING relation_id,version INTO selected_relation_id,selected_version;
    END IF;
    INSERT INTO smartlib.outbox_event
        (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
    VALUES ('relation_assertion',selected_relation_id,'knowledge.relation.updated',selected_version,
            jsonb_build_object('relation_id',selected_relation_id,'version',selected_version),
            'authorship-authority-v1:sync-upsert');
END
$function$;

CREATE OR REPLACE FUNCTION smartlib.guard_person_authored_projection()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    IF NEW.predicate<>'person.authored' THEN
        RETURN NEW;
    END IF;
    IF NEW.object_id IS NULL
       OR NEW.source_publication_authorship_id IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM smartlib.publication_authorship authorship
            WHERE authorship.publication_authorship_id=NEW.source_publication_authorship_id
              AND authorship.publication_id=NEW.object_id
              AND authorship.person_object_id=NEW.subject_id
              AND authorship.verification_status<>'rejected'
       ) THEN
        RAISE EXCEPTION 'person.authored must reference a matching publication_authorship authority row'
            USING ERRCODE='23514';
    END IF;
    IF NEW.fact_class<>'literature_fact'
       OR NEW.review_state<>'approved'
       OR NEW.attributes->>'authority_source'<>'publication_authorship'
       OR NEW.attributes->>'canonical_authorship_id'
            IS DISTINCT FROM NEW.source_publication_authorship_id::text THEN
        RAISE EXCEPTION 'person.authored is a synchronized graph projection, not an independent business fact'
            USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS person_authored_projection_guard ON smartlib.relation_assertion;
CREATE TRIGGER person_authored_projection_guard
BEFORE INSERT OR UPDATE OF subject_id,predicate,object_id,fact_class,review_state,attributes,
    source_publication_authorship_id
ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_person_authored_projection();

CREATE OR REPLACE FUNCTION smartlib.sync_person_authored_from_authorship()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    IF TG_OP='DELETE' THEN
        PERFORM smartlib.refresh_person_authored_relation(OLD.publication_id,OLD.person_object_id);
    ELSIF TG_OP='UPDATE' THEN
        IF OLD.publication_id IS DISTINCT FROM NEW.publication_id
           OR OLD.person_object_id IS DISTINCT FROM NEW.person_object_id THEN
            PERFORM smartlib.refresh_person_authored_relation(OLD.publication_id,OLD.person_object_id);
        END IF;
        PERFORM smartlib.refresh_person_authored_relation(NEW.publication_id,NEW.person_object_id);
    ELSE
        PERFORM smartlib.refresh_person_authored_relation(NEW.publication_id,NEW.person_object_id);
    END IF;
    IF TG_OP='DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS publication_authorship_graph_sync ON smartlib.publication_authorship;
CREATE TRIGGER publication_authorship_graph_sync
AFTER INSERT OR UPDATE OR DELETE ON smartlib.publication_authorship
FOR EACH ROW EXECUTE FUNCTION smartlib.sync_person_authored_from_authorship();

CREATE OR REPLACE VIEW smartlib.authorship_relation_sync_state AS
WITH authority AS (
    SELECT publication_id,person_object_id,count(*)::integer AS authorship_occurrence_count
      FROM smartlib.publication_authorship
     WHERE person_object_id IS NOT NULL AND verification_status<>'rejected'
     GROUP BY publication_id,person_object_id
), graph AS (
    SELECT object_id AS publication_id,subject_id AS person_object_id,
           count(*)::integer AS graph_relation_count,
           bool_and(source_publication_authorship_id IS NOT NULL) AS linked_to_authority
      FROM smartlib.relation_assertion
     WHERE predicate='person.authored'
     GROUP BY object_id,subject_id
)
SELECT COALESCE(authority.publication_id,graph.publication_id) AS publication_id,
       COALESCE(authority.person_object_id,graph.person_object_id) AS person_object_id,
       COALESCE(authority.authorship_occurrence_count,0) AS authorship_occurrence_count,
       COALESCE(graph.graph_relation_count,0) AS graph_relation_count,
       COALESCE(graph.linked_to_authority,false) AS linked_to_authority,
       CASE
           WHEN authority.publication_id IS NULL THEN 'graph_without_authority'
           WHEN graph.publication_id IS NULL THEN 'authority_without_graph'
           WHEN graph.graph_relation_count<>1 THEN 'duplicate_graph_relation'
           WHEN NOT graph.linked_to_authority THEN 'missing_authority_link'
           ELSE 'synchronized'
       END AS sync_state
  FROM authority FULL JOIN graph USING(publication_id,person_object_id);

CREATE OR REPLACE FUNCTION smartlib.sync_journal_identity_to_object()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    selected_version bigint;
BEGIN
    IF NEW.knowledge_object_id IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM set_config('smartlib.journal_identity_sync','on',true);
    UPDATE smartlib.knowledge_object object
       SET canonical_name=NEW.canonical_title,
           attributes=object.attributes || jsonb_build_object(
               'record_kind','journal',
               'journal_identity_id',NEW.journal_id,
               'issn',NEW.issn,
               'eissn',NEW.eissn
           ),
           version=object.version+1,
           updated_at=clock_timestamp()
     WHERE object.object_id=NEW.knowledge_object_id
       AND object.object_type='journal'
       AND (object.canonical_name IS DISTINCT FROM NEW.canonical_title
            OR object.attributes->>'journal_identity_id' IS DISTINCT FROM NEW.journal_id::text
            OR object.attributes->>'issn' IS DISTINCT FROM NEW.issn
            OR object.attributes->>'eissn' IS DISTINCT FROM NEW.eissn)
    RETURNING version INTO selected_version;
    IF selected_version IS NOT NULL THEN
        INSERT INTO smartlib.outbox_event
            (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
        VALUES ('knowledge_object',NEW.knowledge_object_id,'knowledge.object.updated',selected_version,
                jsonb_build_object('object_id',NEW.knowledge_object_id,'version',selected_version),
                'journal-identity-authority-v1');
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS journal_identity_object_sync ON smartlib.journal_identity;
CREATE TRIGGER journal_identity_object_sync
AFTER INSERT OR UPDATE OF canonical_title,issn,eissn,knowledge_object_id
ON smartlib.journal_identity
FOR EACH ROW EXECUTE FUNCTION smartlib.sync_journal_identity_to_object();

CREATE OR REPLACE FUNCTION smartlib.guard_materialized_journal_object()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    identity smartlib.journal_identity%ROWTYPE;
BEGIN
    IF NEW.object_type<>'journal'
       OR current_setting('smartlib.journal_identity_sync',true)='on' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO identity FROM smartlib.journal_identity
     WHERE knowledge_object_id=NEW.object_id;
    IF FOUND AND (
        NEW.canonical_name IS DISTINCT FROM identity.canonical_title
        OR NEW.attributes->>'journal_identity_id' IS DISTINCT FROM identity.journal_id::text
        OR NEW.attributes->>'issn' IS DISTINCT FROM identity.issn
        OR NEW.attributes->>'eissn' IS DISTINCT FROM identity.eissn
    ) THEN
        RAISE EXCEPTION 'journal knowledge object is a projection of journal_identity %',identity.journal_id
            USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS materialized_journal_object_guard ON smartlib.knowledge_object;
CREATE TRIGGER materialized_journal_object_guard
BEFORE UPDATE OF canonical_name,attributes ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_materialized_journal_object();

CREATE OR REPLACE VIEW smartlib.journal_object_sync_state AS
SELECT identity.journal_id,identity.knowledge_object_id,identity.canonical_title,
       object.canonical_name AS object_name,
       CASE
           WHEN identity.knowledge_object_id IS NULL THEN 'not_materialized'
           WHEN object.object_id IS NULL THEN 'missing_object'
           WHEN object.object_type<>'journal' THEN 'wrong_object_type'
           WHEN object.canonical_name IS DISTINCT FROM identity.canonical_title THEN 'name_drift'
           WHEN object.attributes->>'journal_identity_id' IS DISTINCT FROM identity.journal_id::text
               THEN 'identity_link_drift'
           WHEN object.attributes->>'issn' IS DISTINCT FROM identity.issn
             OR object.attributes->>'eissn' IS DISTINCT FROM identity.eissn THEN 'identifier_drift'
           ELSE 'synchronized'
       END AS sync_state
  FROM smartlib.journal_identity identity
  LEFT JOIN smartlib.knowledge_object object
    ON object.object_id=identity.knowledge_object_id;

GRANT SELECT ON smartlib.authorship_relation_sync_state,
    smartlib.journal_object_sync_state TO smartlib_app,smartlib_readonly;

COMMENT ON TABLE smartlib.publication_authorship IS
    'Authoritative publication-scoped authorship occurrences, order, roles and raw affiliation evidence.';
COMMENT ON COLUMN smartlib.journal_identity.knowledge_object_id IS
    'Optional materialized search/graph object; journal_identity remains authoritative for journal identity.';
COMMENT ON VIEW smartlib.authorship_relation_sync_state IS
    'Reconciliation state between authoritative authorship occurrences and deduplicated person.authored graph edges.';
COMMENT ON VIEW smartlib.journal_object_sync_state IS
    'Reconciliation state between authoritative journal identities and materialized journal knowledge objects.';

RESET ROLE;
