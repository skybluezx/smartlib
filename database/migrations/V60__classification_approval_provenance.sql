SET ROLE smartlib_owner;
INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'relation',p,'*',k,ARRAY['string'],false,'用户确认审核结果的责任人与时间；不改变原分类来源类型。','paper-profile-v1'
FROM unnest(ARRAY['publication.classified_as_discipline','publication.has_research_topic']) p
CROSS JOIN unnest(ARRAY['reviewed_by','reviewed_at']) k
ON CONFLICT DO NOTHING;
RESET ROLE;
