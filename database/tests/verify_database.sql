\set ON_ERROR_STOP on

BEGIN;

SET LOCAL ROLE smartlib_app;
SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

INSERT INTO smartlib.source_system (
    source_system_id, code, name, owner_department, source_type, authorization_state
) VALUES (
    '20000000-0000-0000-0000-000000000001',
    'verify_source',
    'Database verification source',
    'SmartLib verification',
    'manual',
    'approved'
);

INSERT INTO smartlib.knowledge_object (
    object_id, object_type, canonical_name, visibility, created_by
) VALUES
    ('30000000-0000-0000-0000-000000000001', 'person', 'DB_VERIFY_ACTOR_A_PRIVATE', 'private', '10000000-0000-0000-0000-000000000001'),
    ('30000000-0000-0000-0000-000000000002', 'person', 'DB_VERIFY_ACTOR_A_PUBLIC', 'public', '10000000-0000-0000-0000-000000000001');

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000002', true);

INSERT INTO smartlib.knowledge_object (
    object_id, object_type, canonical_name, visibility, created_by
) VALUES
    ('30000000-0000-0000-0000-000000000003', 'person', 'DB_VERIFY_ACTOR_B_PRIVATE', 'private', '10000000-0000-0000-0000-000000000002'),
    ('30000000-0000-0000-0000-000000000004', 'person', 'DB_VERIFY_ACTOR_B_PUBLIC', 'public', '10000000-0000-0000-0000-000000000002');

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

INSERT INTO smartlib.knowledge_object (
    object_id, object_type, canonical_name, visibility, created_by
) VALUES (
    '30000000-0000-0000-0000-000000000005', 'publication',
    'PUBLICATION_VERIFY_RECORD', 'private',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.ingestion_batch (
 batch_id,source_system_id,dataset_version,source_uri,source_checksum,source_locator,
 expected_item_count,batch_state,created_by,pipeline_key,source_kind
) VALUES ('91000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',
 'publication-verification-test-v1','controlled://database-test/publications.xlsx',repeat('a',64),
 '{"sheet":"representative_publications"}',1,'verifying','10000000-0000-0000-0000-000000000001','publication','file');
INSERT INTO smartlib.ingestion_record (
 record_id,batch_id,source_record_key,source_locator,record_kind,raw_payload,normalized_payload,payload_checksum,created_by
) VALUES ('92000000-0000-0000-0000-000000000001','91000000-0000-0000-0000-000000000001','test:2',
 '{"sheet":"representative_publications","row":2}','publication',
 '{"title":"Raw title","doi":"https://doi.org/10.1000/Test"}',
 '{"title":"Raw title","doi":"10.1000/test"}',repeat('b',64),'10000000-0000-0000-0000-000000000001');
INSERT INTO smartlib.publication_intake_record(record_id,verification_state,matched_publication_id)
VALUES('92000000-0000-0000-0000-000000000001','manual_review','30000000-0000-0000-0000-000000000005');
INSERT INTO smartlib.representative_work_submission(record_id,representative_work_number,awardee_name_raw,awardee_person_id)
VALUES('92000000-0000-0000-0000-000000000001','TEST-WORK-001','DB Verify Scholar','30000000-0000-0000-0000-000000000001');

INSERT INTO smartlib.publication_metadata (
    publication_id, title, journal_name, publication_year,
    publication_status, created_by
) VALUES (
    '30000000-0000-0000-0000-000000000005', 'Raw title',
    'DB Verification Journal', 2026, 'published',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.publication_identifier (
    publication_identifier_id, publication_id, identifier_type, raw_value,
    normalized_value, is_primary, verification_status, created_by
) VALUES (
    '94000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000005', 'doi',
    'https://doi.org/10.1000/Test', '10.1000/test', true, 'matched',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.publication_authorship (
    publication_authorship_id, publication_id, author_order,
    author_name_raw, author_name_normalized, is_first_author,
    person_object_id, match_status, verification_status, created_by
) VALUES (
    '95000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000005', 1,
    'DB Verify Scholar', 'DB Verify Scholar', true,
    '30000000-0000-0000-0000-000000000001', 'matched', 'matched',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.publication_field_verification (
    field_verification_id, record_id, publication_id, field_name,
    source_value, normalized_source_value, candidate_value,
    candidate_source_code, candidate_external_id, match_score,
    verification_status, decision_reason, created_by
) VALUES (
    '96000000-0000-0000-0000-000000000001',
    '92000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000005', 'title',
    to_jsonb('Raw title'::text), to_jsonb('raw title'::text),
    to_jsonb('Raw title'::text), 'crossref', '10.1000/test', 1.0000,
    'matched', 'Exact normalized title match',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.publication_verification_decision (
    verification_decision_id, record_id, publication_id, decision,
    decision_reason, decision_method, evidence_summary, decided_by, created_by
) VALUES (
    '97000000-0000-0000-0000-000000000001',
    '92000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000005', 'human_verified',
    'Verified against controlled test evidence', 'human',
    '{"verified_fields":["title","doi"]}'::jsonb,
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001'
);

DO $publication_domain_contract$
BEGIN
    IF (SELECT count(*) FROM smartlib.ingestion_record
        WHERE batch_id = '91000000-0000-0000-0000-000000000001') <> 1
       OR (SELECT count(*) FROM smartlib.publication_authorship
           WHERE publication_id = '30000000-0000-0000-0000-000000000005') <> 1
       OR (SELECT count(*) FROM smartlib.publication_verification_decision
           WHERE record_id = '92000000-0000-0000-0000-000000000001'
             AND is_current) <> 1 THEN
        RAISE EXCEPTION 'publication verification domain did not preserve its core records';
    END IF;
END
$publication_domain_contract$;

DO $publication_duplicate_identifier_rejected$
BEGIN
    BEGIN
        INSERT INTO smartlib.publication_identifier (
            publication_id, identifier_type, raw_value, normalized_value,
            verification_status, created_by
        ) VALUES (
            '30000000-0000-0000-0000-000000000005',
            'doi', '10.1000/TEST', '10.1000/TEST', 'pending',
            '10000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'duplicate normalized publication identifier was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
END
$publication_duplicate_identifier_rejected$;

DO $publication_object_type_enforced$
BEGIN
    BEGIN
        INSERT INTO smartlib.publication_identifier (
            publication_id, identifier_type, raw_value, normalized_value,
            verification_status, created_by
        ) VALUES (
            '30000000-0000-0000-0000-000000000001',
            'doi', '10.1000/wrong-type', '10.1000/wrong-type', 'pending',
            '10000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'person object was accepted as a publication';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END
$publication_object_type_enforced$;

DO $publication_decision_is_immutable$
BEGIN
    BEGIN
        UPDATE smartlib.publication_verification_decision
           SET decision_reason = 'MUST_NOT_MUTATE'
         WHERE verification_decision_id = '97000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'publication verification decision history was mutable';
    EXCEPTION WHEN SQLSTATE '55000' THEN NULL;
    END;
END
$publication_decision_is_immutable$;

UPDATE smartlib.publication_verification_decision
   SET is_current = false
 WHERE verification_decision_id = '97000000-0000-0000-0000-000000000001';

INSERT INTO smartlib.publication_verification_decision (
    verification_decision_id, record_id, publication_id, decision,
    decision_reason, decision_method, evidence_summary, decided_by, created_by
) VALUES (
    '97000000-0000-0000-0000-000000000002',
    '92000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000005', 'corrected',
    'New evidence corrected the canonical record', 'human',
    '{"previous_decision":"97000000-0000-0000-0000-000000000001"}'::jsonb,
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001'
);

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000002', true);

DO $publication_verification_rls$
BEGIN
    IF EXISTS (SELECT 1 FROM smartlib.ingestion_batch
               WHERE batch_id = '91000000-0000-0000-0000-000000000001')
       OR EXISTS (SELECT 1 FROM smartlib.publication_verification_decision
                  WHERE record_id = '92000000-0000-0000-0000-000000000001') THEN
        RAISE EXCEPTION 'publication verification workflow leaked across actors';
    END IF;
END
$publication_verification_rls$;

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

DO $rls_actor_a$
BEGIN
    IF (SELECT count(*) FROM smartlib.knowledge_object WHERE canonical_name LIKE 'DB_VERIFY_%') <> 3 THEN
        RAISE EXCEPTION 'RLS actor A expected 3 visible objects';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.knowledge_object
        WHERE object_id = '30000000-0000-0000-0000-000000000003'
    ) THEN
        RAISE EXCEPTION 'RLS exposed actor B private object to actor A';
    END IF;
END
$rls_actor_a$;

INSERT INTO smartlib.governance_domain (
    governance_domain_id, code, name, visibility, created_by
) VALUES (
    '70000000-0000-0000-0000-000000000001', 'verify_private_governance',
    'DB_VERIFY_PRIVATE_GOVERNANCE', 'private', '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.data_asset (
    data_asset_id, governance_domain_id, source_system_id, code, name,
    asset_type, visibility, synthetic, created_by
) VALUES (
    '71000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'verify_private_asset', 'DB_VERIFY_PRIVATE_ASSET', 'dataset', 'private', true,
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.license_grant (
    license_grant_id, data_asset_id, license_name, license_reference,
    authorization_state, allowed_content, allowed_purposes, synthetic, created_by
) VALUES (
    '72000000-0000-0000-0000-000000000001',
    '71000000-0000-0000-0000-000000000001',
    'DB_VERIFY_PENDING_LICENSE', 'DB_VERIFY_LICENSE_REFERENCE', 'pending',
    ARRAY['metadata'], ARRAY['search'], true,
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.governance_change (
    governance_change_id, resource_type, resource_id, change_type,
    after_state, reason, created_by
) VALUES (
    '73000000-0000-0000-0000-000000000001', 'license_grant',
    '72000000-0000-0000-0000-000000000001', 'reviewed',
    '{"authorization_state":"pending","decision":"deny"}',
    'DB verification: unknown authorization must not allow use',
    '10000000-0000-0000-0000-000000000001'
);

DO $governance_default_deny$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM smartlib.data_asset
         WHERE data_asset_id = '71000000-0000-0000-0000-000000000001'
           AND synthetic
    ) THEN
        RAISE EXCEPTION 'synthetic governance asset lost its explicit label';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.license_grant
         WHERE license_grant_id = '72000000-0000-0000-0000-000000000001'
           AND authorization_state = 'approved'
    ) THEN
        RAISE EXCEPTION 'pending license was treated as approved';
    END IF;
END
$governance_default_deny$;

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000002', true);

DO $governance_private_rls$
BEGIN
    IF EXISTS (
        SELECT 1 FROM smartlib.data_asset
         WHERE data_asset_id = '71000000-0000-0000-0000-000000000001'
    ) THEN
        RAISE EXCEPTION 'governance RLS exposed actor A private asset to actor B';
    END IF;
END
$governance_private_rls$;

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

DO $governance_change_is_append_only_for_app$
BEGIN
    BEGIN
        UPDATE smartlib.governance_change
           SET reason = 'MUST_NOT_MUTATE'
         WHERE governance_change_id = '73000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'application role unexpectedly changed governance history';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END
$governance_change_is_append_only_for_app$;

DO $invalid_relation$
BEGIN
    BEGIN
        INSERT INTO smartlib.relation_assertion (
            relation_id, subject_id, predicate, object_id, literal_value,
            fact_class, created_by
        ) VALUES (
            '40000000-0000-0000-0000-000000000001',
            '30000000-0000-0000-0000-000000000001',
            'verify.invalid_target',
            '30000000-0000-0000-0000-000000000002',
            '{"also":"literal"}'::jsonb,
            'business_fact',
            '10000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'relation target constraint did not reject invalid data';
    EXCEPTION
        WHEN check_violation THEN NULL;
    END;
END
$invalid_relation$;

INSERT INTO smartlib.evidence_record (
    evidence_id, object_id, evidence_type, citation, visibility, created_by
) VALUES (
    '41000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    'manual_review',
    'DB_VERIFY_PRIVATE_EVIDENCE',
    'private',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.relation_assertion (
    relation_id, subject_id, predicate, object_id, fact_class, visibility,
    review_state, created_by
) VALUES (
    '40000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000002',
    'person.collaborates_with',
    '30000000-0000-0000-0000-000000000004',
    'human_confirmed',
    'public',
    'approved',
    '10000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.relation_evidence (relation_id, evidence_id) VALUES (
    '40000000-0000-0000-0000-000000000002',
    '41000000-0000-0000-0000-000000000001'
);

INSERT INTO smartlib.outbox_event (
    event_id, aggregate_type, aggregate_id, event_type, payload
) VALUES (
    '50000000-0000-0000-0000-000000000010',
    'relation_assertion',
    '40000000-0000-0000-0000-000000000002',
    'knowledge.relation.created',
    '{"relation_id":"40000000-0000-0000-0000-000000000002","version":1}'::jsonb
);

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000002', true);

DO $relation_evidence_no_reference_leak$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM smartlib.relation_assertion
        WHERE relation_id = '40000000-0000-0000-0000-000000000002'
    ) THEN
        RAISE EXCEPTION 'actor B should see the public relation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.relation_evidence
        WHERE relation_id = '40000000-0000-0000-0000-000000000002'
    ) THEN
        RAISE EXCEPTION 'relation_evidence leaked a private evidence identifier';
    END IF;
END
$relation_evidence_no_reference_leak$;

SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

SAVEPOINT outbox_atomicity;
INSERT INTO smartlib.knowledge_object (
    object_id, object_type, canonical_name, visibility, created_by
) VALUES (
    '30000000-0000-0000-0000-000000000099',
    'resource',
    'DB_VERIFY_OUTBOX_ATOMICITY',
    'private',
    '10000000-0000-0000-0000-000000000001'
);
INSERT INTO smartlib.outbox_event (
    event_id, aggregate_type, aggregate_id, event_type, payload
) VALUES (
    '50000000-0000-0000-0000-000000000099',
    'knowledge_object',
    '30000000-0000-0000-0000-000000000099',
    'knowledge_object.created',
    '{"verification":true}'::jsonb
);
ROLLBACK TO SAVEPOINT outbox_atomicity;

DO $outbox_rollback$
BEGIN
    IF EXISTS (
        SELECT 1 FROM smartlib.knowledge_object
        WHERE object_id = '30000000-0000-0000-0000-000000000099'
    ) OR EXISTS (
        SELECT 1 FROM smartlib.outbox_event
        WHERE event_id = '50000000-0000-0000-0000-000000000099'
    ) THEN
        RAISE EXCEPTION 'domain write and outbox event did not roll back together';
    END IF;
END
$outbox_rollback$;

INSERT INTO smartlib.outbox_event (
    event_id, aggregate_type, aggregate_id, event_type, payload
) VALUES
    (
        '50000000-0000-0000-0000-000000000001',
        'knowledge_object',
        '30000000-0000-0000-0000-000000000001',
        'knowledge.object.created',
        '{"object_id":"30000000-0000-0000-0000-000000000001","version":1}'::jsonb
    ),
    (
        '50000000-0000-0000-0000-000000000002',
        'knowledge_object',
        '30000000-0000-0000-0000-000000000002',
        'knowledge.object.created',
        '{"object_id":"30000000-0000-0000-0000-000000000002","version":1}'::jsonb
    ),
    (
        '50000000-0000-0000-0000-000000000003',
        'knowledge_object',
        '30000000-0000-0000-0000-000000000003',
        'knowledge.object.created',
        '{"object_id":"30000000-0000-0000-0000-000000000003","version":1}'::jsonb
    ),
    (
        '50000000-0000-0000-0000-000000000004',
        'knowledge_object',
        '30000000-0000-0000-0000-000000000004',
        'knowledge.object.created',
        '{"object_id":"30000000-0000-0000-0000-000000000004","version":1}'::jsonb
    );

RESET ROLE;
SET LOCAL ROLE smartlib_projection;

DO $graph_delivery_contract$
DECLARE
    delivery jsonb;
BEGIN
    SELECT smartlib_projection.graph_delivery_json(
        '50000000-0000-0000-0000-000000000010'
    ) INTO delivery;
    IF delivery ->> 'entity_kind' <> 'relation'
       OR delivery ->> 'operation' <> 'upsert'
       OR jsonb_array_length(delivery -> 'nodes') <> 2
       OR jsonb_array_length(delivery -> 'document' -> 'evidence_ids_all') <> 1
       OR jsonb_array_length(delivery -> 'document' -> 'evidence_visibilities') <> 1
       OR jsonb_array_length(delivery -> 'document' -> 'evidence_created_by') <> 1 THEN
        RAISE EXCEPTION 'graph delivery contract is incomplete: %', delivery;
    END IF;
END
$graph_delivery_contract$;

SELECT smartlib_projection.acknowledge_graph_event(
    'hugegraph_graph', '50000000-0000-0000-0000-000000000010'
);

DO $graph_receipt_contract$
BEGIN
    IF EXISTS (
        SELECT 1 FROM smartlib_projection.pending_graph_events('hugegraph_graph', 100)
        WHERE event_id = '50000000-0000-0000-0000-000000000010'
    ) THEN
        RAISE EXCEPTION 'acknowledged graph event remained pending';
    END IF;
END
$graph_receipt_contract$;

SELECT smartlib_projection.refresh_postgres_search_event(event_id)
FROM smartlib_projection.pending_search_events('postgres_search', 100)
WHERE object_id IN (
    '30000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000004'
);

DO $projection_least_privilege$
BEGIN
    BEGIN
        INSERT INTO smartlib_projection.search_document (
            object_id, object_type, canonical_name, visibility, created_by,
            object_version, policy_version, projection_version, source_updated_at, search_vector
        ) VALUES (
            gen_random_uuid(), 'person', 'MUST_NOT_INSERT', 'public',
            '10000000-0000-0000-0000-000000000001', 1, 'none', 'search-document-v1',
            clock_timestamp(), ''::tsvector
        );
        RAISE EXCEPTION 'projection role unexpectedly wrote search_document directly';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END
$projection_least_privilege$;

RESET ROLE;
SET LOCAL ROLE smartlib_app;
SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

DO $search_projection_rls$
BEGIN
    IF (SELECT count(*) FROM smartlib_projection.search_document WHERE canonical_name LIKE 'DB_VERIFY_%') <> 3 THEN
        RAISE EXCEPTION 'search projection RLS expected 3 visible objects for actor A';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib_projection.search_document
        WHERE object_id = '30000000-0000-0000-0000-000000000003'
    ) THEN
        RAISE EXCEPTION 'search projection exposed actor B private object to actor A';
    END IF;
    IF (
        SELECT count(*)
        FROM smartlib_projection.event_receipt
        WHERE projection_name = 'postgres_search'
    ) IS NOT NULL THEN
        RAISE EXCEPTION 'application role unexpectedly read projection receipts';
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN NULL;
END
$search_projection_rls$;

INSERT INTO audit.audit_event (
    event_id, actor_id, action, resource_type, resource_id, decision
) VALUES (
    '60000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'verify.audit',
    'verification',
    'database',
    'recorded'
);

DO $app_audit_update_denied$
BEGIN
    BEGIN
        UPDATE audit.audit_event
        SET details = '{"tampered":true}'::jsonb
        WHERE event_id = '60000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'application role unexpectedly updated audit event';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END
$app_audit_update_denied$;

DO $app_audit_select_denied$
BEGIN
    BEGIN
        PERFORM count(*) FROM audit.audit_event;
        RAISE EXCEPTION 'application role unexpectedly read raw audit events';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END
$app_audit_select_denied$;

RESET ROLE;
SET LOCAL ROLE smartlib_readonly;
SELECT set_config('smartlib.actor_id', '10000000-0000-0000-0000-000000000001', true);

DO $readonly_insert_denied$
BEGIN
    BEGIN
        INSERT INTO smartlib.knowledge_object (
            object_type, canonical_name, visibility, created_by
        ) VALUES (
            'person',
            'DB_VERIFY_READONLY_MUST_FAIL',
            'private',
            '10000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'readonly role unexpectedly inserted data';
    EXCEPTION
        WHEN insufficient_privilege THEN NULL;
    END;
END
$readonly_insert_denied$;

DO $readonly_rls$
BEGIN
    IF (SELECT count(*) FROM smartlib.knowledge_object WHERE canonical_name LIKE 'DB_VERIFY_%') <> 3 THEN
        RAISE EXCEPTION 'readonly RLS did not preserve actor isolation';
    END IF;
END
$readonly_rls$;

RESET ROLE;
SET LOCAL ROLE smartlib_owner;

DO $owner_cannot_mutate_audit$
BEGIN
    BEGIN
        UPDATE audit.audit_event
        SET details = '{"owner_tampered":true}'::jsonb
        WHERE event_id = '60000000-0000-0000-0000-000000000001';
        RAISE EXCEPTION 'append-only trigger did not reject audit update';
    EXCEPTION
        WHEN SQLSTATE '55000' THEN NULL;
    END;
END
$owner_cannot_mutate_audit$;

DO $governed_relation_and_attribute_contracts$
DECLARE
    selected_person uuid;
    selected_project uuid;
    selected_object uuid;
BEGIN
    IF EXISTS (
        SELECT 1 FROM smartlib.relation_assertion relation
        LEFT JOIN smartlib.relation_predicate_definition definition
          ON definition.predicate=relation.predicate
         AND definition.lifecycle_state='active'
        WHERE definition.predicate IS NULL
    ) THEN
        RAISE EXCEPTION 'current relation uses an unregistered or inactive predicate';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.authorship_relation_sync_state
         WHERE sync_state<>'synchronized'
    ) THEN
        RAISE EXCEPTION 'publication_authorship and person.authored are not synchronized';
    END IF;
    IF EXISTS (
        SELECT 1 FROM smartlib.journal_object_sync_state
         WHERE sync_state NOT IN ('synchronized','not_materialized')
    ) THEN
        RAISE EXCEPTION 'journal_identity and materialized journal objects have drifted';
    END IF;

    SELECT object_id INTO selected_person FROM smartlib.knowledge_object
     WHERE object_type='person' LIMIT 1;
    SELECT object_id INTO selected_project FROM smartlib.knowledge_object
     WHERE object_type='project' LIMIT 1;
    SELECT object_id INTO selected_object FROM smartlib.knowledge_object LIMIT 1;

    BEGIN
        INSERT INTO smartlib.relation_assertion
            (subject_id,predicate,object_id,created_by)
        VALUES (selected_person,'verification.unknown_predicate',selected_project,
                '10000000-0000-0000-0000-000000000001');
        RAISE EXCEPTION 'unregistered predicate was accepted';
    EXCEPTION WHEN check_violation OR foreign_key_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO smartlib.relation_assertion
            (subject_id,predicate,object_id,attributes,created_by)
        VALUES (selected_project,'person.leads_project',selected_person,'{}'::jsonb,
                '10000000-0000-0000-0000-000000000001');
        RAISE EXCEPTION 'invalid relation endpoint types were accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        UPDATE smartlib.knowledge_object
           SET attributes=attributes||'{"definitely_unknown_attribute":true}'::jsonb
         WHERE object_id=selected_object;
        RAISE EXCEPTION 'unregistered JSON attribute was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END
$governed_relation_and_attribute_contracts$;

RESET ROLE;
ROLLBACK;

SELECT 'SMARTLIB_DATABASE_VERIFY_OK' AS verification_result;
