SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Creation is not completeness certification. Keep the project subtype, but
-- allow unknown business metadata and not-yet-resolved identities to be absent.
-- Non-null identity references remain guarded by enforce_object_identity_contract.
UPDATE smartlib.attribute_definition
   SET required=false,
       allowed_json_types=ARRAY(SELECT DISTINCT t FROM unnest(allowed_json_types || ARRAY['null']) t ORDER BY t),
       description=description || ' V51：可在项目创建后补全；允许缺省或null，非空对象引用仍须有效。',
       schema_version='project-incremental-v1',updated_at=clock_timestamp()
 WHERE entity_kind='object' AND entity_type='project' AND record_kind='individual_grant'
   AND attribute_key IN ('dataset_id','dataset_version','year','funding_program_id','principal_investigator_person_id');

-- Register a creation baseline even when V31 ran against an empty project set.
INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
VALUES
 ('object','project','individual_grant','record_kind',ARRAY['string'],true,'项目对象子类型；信息不完整不改变实体类型。','project-incremental-v1')
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO NOTHING;

-- No knowledge objects, evidence, relationships or existing values are changed.
RESET ROLE;
