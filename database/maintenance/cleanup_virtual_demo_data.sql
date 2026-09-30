\set ON_ERROR_STOP on

BEGIN;

SELECT pg_advisory_xact_lock(hashtext('smartlib.cleanup_virtual_demo_data'));

CREATE TEMP TABLE cleanup_demo_objects ON COMMIT DROP AS
SELECT object_id
FROM smartlib.knowledge_object
WHERE COALESCE((attributes ->> 'synthetic')::boolean, false)
   OR attributes ->> 'dataset_version' IN ('scholargraph-demo-v1', 'governance-demo-v1')
   OR canonical_name IN (
       'SmartLib 学校知识基础设施',
       'SmartLib 统一能力接口',
       'SmartLib 检索投影验证',
       'D04_PRIVATE_NEVER_EXPOSE',
       'D05_PUBLIC_START',
       'D05_PRIVATE_INTERMEDIATE',
       'D05_PUBLIC_END'
   );

CREATE TEMP TABLE cleanup_demo_relations ON COMMIT DROP AS
SELECT relation_id
FROM smartlib.relation_assertion
WHERE subject_id IN (SELECT object_id FROM cleanup_demo_objects)
   OR object_id IN (SELECT object_id FROM cleanup_demo_objects)
   OR license_tags && ARRAY['synthetic-demo', 'authorized_demo']::text[]
   OR model_version = 'scholargraph-demo-rules-v1';

CREATE TEMP TABLE cleanup_demo_references ON COMMIT DROP AS
SELECT source_reference_id
FROM smartlib.source_reference
WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects)
   OR COALESCE((metadata ->> 'synthetic')::boolean, false)
   OR source_version IN ('scholargraph-demo-v1', 'governance-demo-v1');

CREATE TEMP TABLE cleanup_demo_evidence ON COMMIT DROP AS
SELECT evidence_id
FROM smartlib.evidence_record
WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects)
   OR source_reference_id IN (SELECT source_reference_id FROM cleanup_demo_references)
   OR COALESCE((metadata ->> 'synthetic')::boolean, false)
   OR license_tags && ARRAY['synthetic-demo', 'authorized_demo']::text[];

DO $safety$
DECLARE
    real_scholar_count integer;
    protected_selected integer;
BEGIN
    SELECT count(*) INTO real_scholar_count
    FROM smartlib.knowledge_object
    WHERE object_type = 'person'
      AND attributes ->> 'dataset_version' = '2026-nsf-representative-publications-v1'
      AND COALESCE((attributes ->> 'synthetic')::boolean, false) = false;

    SELECT count(*) INTO protected_selected
    FROM smartlib.knowledge_object
    WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects)
      AND attributes ->> 'dataset_version' = '2026-nsf-representative-publications-v1';

    IF real_scholar_count <> 58 THEN
        RAISE EXCEPTION 'Safety check failed: expected 58 real scholars, found %', real_scholar_count;
    END IF;
    IF protected_selected <> 0 THEN
        RAISE EXCEPTION 'Safety check failed: cleanup selected % protected real scholars', protected_selected;
    END IF;
END
$safety$;

-- Emit canonical deletion events. Projection workers will remove the same
-- entities from PostgreSQL search and HugeGraph after this transaction commits.
INSERT INTO smartlib.outbox_event (
    event_id, aggregate_type, aggregate_id, event_type, event_version, payload, trace_id
)
SELECT gen_random_uuid(), 'relation_assertion', relation_id,
       'knowledge.relation.deleted', 1,
       jsonb_build_object('relation_id', relation_id, 'reason', 'virtual_demo_cleanup'),
       'cleanup-virtual-demo-2026-09-01'
FROM cleanup_demo_relations;

INSERT INTO smartlib.outbox_event (
    event_id, aggregate_type, aggregate_id, event_type, event_version, payload, trace_id
)
SELECT gen_random_uuid(), 'knowledge_object', object_id,
       'knowledge.object.deleted', 1,
       jsonb_build_object('object_id', object_id, 'reason', 'virtual_demo_cleanup'),
       'cleanup-virtual-demo-2026-09-01'
FROM cleanup_demo_objects;

DELETE FROM smartlib.relation_evidence
WHERE relation_id IN (SELECT relation_id FROM cleanup_demo_relations)
   OR evidence_id IN (SELECT evidence_id FROM cleanup_demo_evidence);

DELETE FROM smartlib.relation_assertion
WHERE relation_id IN (SELECT relation_id FROM cleanup_demo_relations);

DELETE FROM smartlib.object_policy_tag
WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects);

DELETE FROM smartlib.evidence_record
WHERE evidence_id IN (SELECT evidence_id FROM cleanup_demo_evidence);

DELETE FROM smartlib.source_reference
WHERE source_reference_id IN (SELECT source_reference_id FROM cleanup_demo_references);

-- Search is a derived projection. Delete immediately as well as through outbox
-- delivery, so the user-facing search result is clean at commit time.
DELETE FROM smartlib_projection.search_document
WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects);

DELETE FROM smartlib.knowledge_object
WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects);

-- Remove the fully synthetic governance vertical slice in dependency order.
DELETE FROM smartlib.quality_issue
WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.quality_run
WHERE quality_rule_id IN (
    SELECT quality_rule_id FROM smartlib.quality_rule
    WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic)
);

DELETE FROM smartlib.quality_rule
WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.stewardship_assignment
WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.license_grant
WHERE synthetic
   OR data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.data_contract_version
WHERE data_contract_id IN (
    SELECT data_contract_id FROM smartlib.data_contract
    WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic)
);

DELETE FROM smartlib.data_contract
WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.data_schema_field
WHERE data_asset_version_id IN (
    SELECT data_asset_version_id FROM smartlib.data_asset_version
    WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic)
);

DELETE FROM smartlib.data_asset_version
WHERE data_asset_id IN (SELECT data_asset_id FROM smartlib.data_asset WHERE synthetic);

DELETE FROM smartlib.governance_change
WHERE trace_id = 'governance-demo-v1'
   OR resource_id::text LIKE '7%000000-0000-4000-8000-%';

DELETE FROM smartlib.data_asset WHERE synthetic;

DELETE FROM smartlib.governance_domain AS domain
WHERE domain.governance_domain_id = '71000000-0000-4000-8000-000000000001'
  AND NOT EXISTS (
      SELECT 1 FROM smartlib.data_asset AS asset
      WHERE asset.governance_domain_id = domain.governance_domain_id
  );

DELETE FROM smartlib.source_system AS source
WHERE source.code = 'smartlib_demo_seed'
   OR COALESCE((source.metadata ->> 'synthetic')::boolean, false)
   OR source.metadata ->> 'dataset_version' IN ('scholargraph-demo-v1', 'governance-demo-v1');

INSERT INTO audit.audit_event (
    actor_id, action, resource_type, resource_id, decision, trace_id, details
)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'cleanup_virtual_demo_data', 'dataset', 'virtual-demo-data', 'recorded',
    'cleanup-virtual-demo-2026-09-01',
    jsonb_build_object(
        'deleted_objects', (SELECT count(*) FROM cleanup_demo_objects),
        'deleted_relations', (SELECT count(*) FROM cleanup_demo_relations),
        'deleted_references', (SELECT count(*) FROM cleanup_demo_references),
        'deleted_evidence', (SELECT count(*) FROM cleanup_demo_evidence),
        'preserved_real_dataset', '2026-nsf-representative-publications-v1',
        'preserved_real_scholars', 58
    )
);

DO $postcondition$
DECLARE
    remaining_demo_objects integer;
    remaining_real_scholars integer;
BEGIN
    SELECT count(*) INTO remaining_demo_objects
    FROM smartlib.knowledge_object
    WHERE object_id IN (SELECT object_id FROM cleanup_demo_objects);

    SELECT count(*) INTO remaining_real_scholars
    FROM smartlib.knowledge_object
    WHERE object_type = 'person'
      AND attributes ->> 'dataset_version' = '2026-nsf-representative-publications-v1'
      AND COALESCE((attributes ->> 'synthetic')::boolean, false) = false;

    IF remaining_demo_objects <> 0 OR remaining_real_scholars <> 58 THEN
        RAISE EXCEPTION 'Postcondition failed: demo=%, real_scholars=%',
            remaining_demo_objects, remaining_real_scholars;
    END IF;
END
$postcondition$;

SELECT
    (SELECT count(*) FROM cleanup_demo_objects) AS deleted_objects,
    (SELECT count(*) FROM cleanup_demo_relations) AS deleted_relations,
    (SELECT count(*) FROM cleanup_demo_references) AS deleted_references,
    (SELECT count(*) FROM cleanup_demo_evidence) AS deleted_evidence;

COMMIT;

