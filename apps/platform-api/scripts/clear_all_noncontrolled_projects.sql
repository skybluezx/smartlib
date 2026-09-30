\set ON_ERROR_STOP on

\copy (SELECT row_to_json(row_data)::text FROM (SELECT * FROM smartlib.knowledge_object WHERE object_type='project' AND NOT (attributes->>'record_kind'='individual_grant' AND attributes->>'dataset_id'='2026-nsf-representative-publications') ORDER BY object_id) row_data) TO '/tmp/noncontrolled-projects-objects.jsonl'
\copy (WITH targets AS (SELECT object_id FROM smartlib.knowledge_object WHERE object_type='project' AND NOT (attributes->>'record_kind'='individual_grant' AND attributes->>'dataset_id'='2026-nsf-representative-publications')) SELECT row_to_json(row_data)::text FROM (SELECT relation.* FROM smartlib.relation_assertion relation WHERE relation.subject_id IN (SELECT object_id FROM targets) OR relation.object_id IN (SELECT object_id FROM targets) ORDER BY relation_id) row_data) TO '/tmp/noncontrolled-projects-relations.jsonl'
\copy (WITH targets AS (SELECT object_id FROM smartlib.knowledge_object WHERE object_type='project' AND NOT (attributes->>'record_kind'='individual_grant' AND attributes->>'dataset_id'='2026-nsf-representative-publications')), rels AS (SELECT relation_id FROM smartlib.relation_assertion WHERE subject_id IN (SELECT object_id FROM targets) OR object_id IN (SELECT object_id FROM targets)), evidence_ids AS (SELECT DISTINCT evidence_id FROM smartlib.relation_evidence WHERE relation_id IN (SELECT relation_id FROM rels)) SELECT row_to_json(row_data)::text FROM (SELECT evidence.* FROM smartlib.evidence_record evidence WHERE evidence.evidence_id IN (SELECT evidence_id FROM evidence_ids) ORDER BY evidence_id) row_data) TO '/tmp/noncontrolled-projects-evidence.jsonl'
\copy (WITH targets AS (SELECT object_id FROM smartlib.knowledge_object WHERE object_type='project' AND NOT (attributes->>'record_kind'='individual_grant' AND attributes->>'dataset_id'='2026-nsf-representative-publications')) SELECT row_to_json(row_data)::text FROM (SELECT reference.* FROM smartlib.source_reference reference WHERE reference.object_id IN (SELECT object_id FROM targets) ORDER BY source_reference_id) row_data) TO '/tmp/noncontrolled-projects-source-references.jsonl'

BEGIN;

CREATE TEMP TABLE clear_preserved_projects ON COMMIT DROP AS
SELECT object_id
  FROM smartlib.knowledge_object
 WHERE object_type='project'
   AND attributes->>'record_kind'='individual_grant'
   AND attributes->>'dataset_id'='2026-nsf-representative-publications';

CREATE TEMP TABLE clear_target_projects ON COMMIT DROP AS
SELECT object_id,version
  FROM smartlib.knowledge_object
 WHERE object_type='project'
   AND object_id NOT IN (SELECT object_id FROM clear_preserved_projects);

CREATE TEMP TABLE clear_target_relations ON COMMIT DROP AS
SELECT relation_id,version
  FROM smartlib.relation_assertion
 WHERE subject_id IN (SELECT object_id FROM clear_target_projects)
    OR object_id IN (SELECT object_id FROM clear_target_projects);

CREATE TEMP TABLE clear_target_evidence ON COMMIT DROP AS
SELECT DISTINCT evidence_id
  FROM smartlib.relation_evidence
 WHERE relation_id IN (SELECT relation_id FROM clear_target_relations);

CREATE TEMP TABLE clear_context ON COMMIT DROP AS
SELECT 'clear-all-noncontrolled-projects:' || clock_timestamp()::text AS trace_id;

DO $scope$
DECLARE
    preserved_count integer;
    target_count integer;
    relation_count integer;
    evidence_count integer;
    source_reference_count integer;
BEGIN
    SELECT count(*) INTO preserved_count FROM clear_preserved_projects;
    SELECT count(*) INTO target_count FROM clear_target_projects;
    SELECT count(*) INTO relation_count FROM clear_target_relations;
    SELECT count(*) INTO evidence_count FROM clear_target_evidence;
    SELECT count(*) INTO source_reference_count
      FROM smartlib.source_reference
     WHERE object_id IN (SELECT object_id FROM clear_target_projects);
    IF preserved_count <> 58 OR target_count <> 134 OR relation_count <> 307
       OR evidence_count <> 98 OR source_reference_count <> 134 THEN
        RAISE EXCEPTION 'cleanup scope drifted preserved=%, targets=%, relations=%, evidence=%, references=%',
            preserved_count,target_count,relation_count,evidence_count,source_reference_count;
    END IF;
END
$scope$;

INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT gen_random_uuid(),'relation_assertion',relation.relation_id,'knowledge.relation.updated',relation.version,
       jsonb_build_object('relation_id',relation.relation_id,'version',relation.version),context.trace_id
  FROM clear_target_relations relation CROSS JOIN clear_context context;

INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT gen_random_uuid(),'knowledge_object',project.object_id,'knowledge.object.updated',project.version,
       jsonb_build_object('object_id',project.object_id,'version',project.version),context.trace_id
  FROM clear_target_projects project CROSS JOIN clear_context context;

DELETE FROM smartlib.relation_evidence
 WHERE relation_id IN (SELECT relation_id FROM clear_target_relations);

DELETE FROM smartlib.relation_assertion
 WHERE relation_id IN (SELECT relation_id FROM clear_target_relations);

DELETE FROM smartlib.evidence_record evidence
 WHERE evidence.evidence_id IN (SELECT evidence_id FROM clear_target_evidence)
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.relation_evidence link WHERE link.evidence_id=evidence.evidence_id
   )
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.change_submission supplement
        WHERE supplement.evidence_id=evidence.evidence_id
   );

DELETE FROM smartlib.evidence_record evidence
 WHERE evidence.object_id IN (SELECT object_id FROM clear_target_projects)
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.relation_evidence link WHERE link.evidence_id=evidence.evidence_id
   )
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.change_submission supplement
        WHERE supplement.evidence_id=evidence.evidence_id
   );

DELETE FROM smartlib.evidence_record evidence
 WHERE evidence.source_reference_id IN (
       SELECT source_reference_id FROM smartlib.source_reference
        WHERE object_id IN (SELECT object_id FROM clear_target_projects)
   )
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.relation_evidence link WHERE link.evidence_id=evidence.evidence_id
   )
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.change_submission supplement
        WHERE supplement.evidence_id=evidence.evidence_id
   );

DELETE FROM smartlib.object_policy_tag
 WHERE object_id IN (SELECT object_id FROM clear_target_projects);

DELETE FROM smartlib.source_reference
 WHERE object_id IN (SELECT object_id FROM clear_target_projects);

DELETE FROM smartlib.knowledge_object
 WHERE object_id IN (SELECT object_id FROM clear_target_projects);

DELETE FROM smartlib.source_system source
 WHERE source.code IN ('publication_fulltext_funding','validated_incites_pdf_projects')
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.source_reference reference
        WHERE reference.source_system_id=source.source_system_id
   );

DO $verify$
DECLARE
    all_projects integer;
    preserved_projects integer;
    noncontrolled_projects integer;
    dangling_relations integer;
    related_source_references integer;
    validated_evidence integer;
BEGIN
    SELECT count(*) INTO all_projects
      FROM smartlib.knowledge_object WHERE object_type='project';
    SELECT count(*) INTO preserved_projects
      FROM smartlib.knowledge_object
     WHERE object_type='project'
       AND attributes->>'record_kind'='individual_grant'
       AND attributes->>'dataset_id'='2026-nsf-representative-publications';
    SELECT count(*) INTO noncontrolled_projects
      FROM smartlib.knowledge_object
     WHERE object_type='project'
       AND NOT (attributes->>'record_kind'='individual_grant'
                AND attributes->>'dataset_id'='2026-nsf-representative-publications');
    SELECT count(*) INTO dangling_relations
      FROM smartlib.relation_assertion relation
      LEFT JOIN smartlib.knowledge_object subject ON subject.object_id=relation.subject_id
      LEFT JOIN smartlib.knowledge_object object ON object.object_id=relation.object_id
     WHERE subject.object_id IS NULL OR (relation.object_id IS NOT NULL AND object.object_id IS NULL);
    SELECT count(*) INTO related_source_references
      FROM smartlib.source_system source
     WHERE source.code IN ('publication_fulltext_funding','validated_incites_pdf_projects');
    SELECT count(*) INTO validated_evidence
      FROM smartlib.evidence_record
     WHERE metadata->>'rule_version'='incites-pdf-validated-project-v1';
    IF all_projects <> 58 OR preserved_projects <> 58 OR noncontrolled_projects <> 0
       OR dangling_relations <> 0 OR related_source_references <> 0 OR validated_evidence <> 0 THEN
        RAISE EXCEPTION 'cleanup verification failed projects=%/% noncontrolled=% dangling=% sources=% evidence=%',
            all_projects,preserved_projects,noncontrolled_projects,dangling_relations,
            related_source_references,validated_evidence;
    END IF;
END
$verify$;

SELECT context.trace_id,
       (SELECT count(*) FROM clear_preserved_projects) AS preserved_projects,
       (SELECT count(*) FROM clear_target_projects) AS deleted_projects,
       (SELECT count(*) FROM clear_target_relations) AS deleted_relations,
       (SELECT count(*) FROM clear_target_evidence) AS deleted_evidence
  FROM clear_context context;

COMMIT;
