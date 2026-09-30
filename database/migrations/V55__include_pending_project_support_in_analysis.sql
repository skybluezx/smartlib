SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Product decision: project support extracted from publication full text may be
-- used for exploratory analytics before verification. Review state remains
-- pending and continues to be exposed to consumers as a data-quality boundary.
INSERT INTO smartlib.attribute_definition
    (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,
     description,schema_version)
VALUES
    ('object','project','individual_grant','analysis_enabled',ARRAY['boolean'],false,
     '是否允许本对象参与分析；不改变核验状态。','pending-project-analysis-v1'),
    ('object','project','individual_grant','analysis_policy',ARRAY['string'],false,
     '允许待核对象参与分析时采用的显式统计策略。','pending-project-analysis-v1'),
    ('relation','publication.supported_by_project','*','analysis_enabled',ARRAY['boolean'],false,
     '是否允许本关系参与分析；不改变核验状态。','pending-project-analysis-v1'),
    ('relation','publication.supported_by_project','*','analysis_policy',ARRAY['string'],false,
     '允许待核关系参与分析时采用的显式统计策略。','pending-project-analysis-v1')
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO UPDATE
SET allowed_json_types=EXCLUDED.allowed_json_types,
    description=EXCLUDED.description,
    schema_version=EXCLUDED.schema_version;

WITH updated_projects AS (
    UPDATE smartlib.knowledge_object project
       SET attributes=project.attributes || jsonb_build_object(
               'analysis_enabled',true,
               'analysis_policy','include_pending_project_support_v1'
           ),
           version=project.version+1,
           updated_at=clock_timestamp()
     WHERE project.object_type='project'
       AND project.system_to='infinity'::timestamptz
       AND EXISTS (
           SELECT 1
             FROM smartlib.relation_assertion relation
            WHERE relation.object_id=project.object_id
              AND relation.predicate='publication.supported_by_project'
              AND relation.review_state='pending'
              AND relation.system_to='infinity'::timestamptz
       )
       AND (
           coalesce((project.attributes->>'analysis_enabled')::boolean,false)=false
           OR project.attributes->>'analysis_policy'
              IS DISTINCT FROM 'include_pending_project_support_v1'
       )
    RETURNING object_id,version
)
INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT md5('pending-project-analysis-v1:object:' || object_id::text)::uuid,
       'knowledge_object',object_id,'knowledge.object.updated',version,
       jsonb_build_object('object_id',object_id,'version',version),
       'pending-project-analysis-v1'
  FROM updated_projects
ON CONFLICT (event_id) DO NOTHING;

WITH updated_relations AS (
    UPDATE smartlib.relation_assertion relation
       SET attributes=relation.attributes || jsonb_build_object(
               'analysis_enabled',true,
               'analysis_policy','include_pending_project_support_v1'
           ),
           version=relation.version+1,
           updated_at=clock_timestamp()
     WHERE relation.predicate='publication.supported_by_project'
       AND relation.review_state='pending'
       AND relation.system_to='infinity'::timestamptz
       AND (
           coalesce((relation.attributes->>'analysis_enabled')::boolean,false)=false
           OR relation.attributes->>'analysis_policy'
              IS DISTINCT FROM 'include_pending_project_support_v1'
       )
    RETURNING relation_id,version
)
INSERT INTO smartlib.outbox_event
    (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT md5('pending-project-analysis-v1:relation:' || relation_id::text)::uuid,
       'relation_assertion',relation_id,'knowledge.relation.updated',version,
       jsonb_build_object('relation_id',relation_id,'version',version),
       'pending-project-analysis-v1'
  FROM updated_relations
ON CONFLICT (event_id) DO NOTHING;

RESET ROLE;
