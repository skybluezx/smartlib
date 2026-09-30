SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;
INSERT INTO smartlib.attribute_definition(entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'object','funding_program','funding_category',key,ARRAY[kind],key='record_kind',description,'funding-category-v1'
FROM (VALUES
 ('record_kind','string','项目种类：按审核过的计划或来源名称汇聚，不是具体项目。'),
 ('category_basis','string','种类的识别口径；来源汇聚不等同正式计划身份核准。'),
 ('source_import_batch','string','种类建立及分类迁移批次。'),
 ('source_names','array','保留的资助名称及同义表述。'),
 ('funding_source_category','string','资助来源粗分类代码，唯一权威存于种类对象。'),
 ('funding_source_category_label','string','资助来源粗分类标签。'),
 ('funding_source_classification','object','可修订的分类版本、理由及来源证据。'),
 ('governance_notes','array','分类与项目身份疑问分离；不能以种类推定项目负责人。')
)f(key,kind,description) ON CONFLICT DO NOTHING;
INSERT INTO smartlib.attribute_definition(entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'relation','project.under_program','*',key,ARRAY[kind],false,description,'funding-category-v1'
FROM (VALUES
 ('relation_label','string','具体项目属于项目种类。'),
 ('source_import_batch','string','迁移批次。'),
 ('source_record_ids','array','原始全文逐条记录。'),
 ('membership_basis','string','根据原文名称或手工项目来源暂定归类。'),
 ('governance_notes','array','保留项目归属待确认事项。')
)f(key,kind,description) ON CONFLICT DO NOTHING;
UPDATE smartlib.relation_predicate_definition SET canonical_label='属于项目种类',description='具体项目归入资助计划或按资助来源暂定的项目种类；目标为funding_program，不是资助机构对象。',schema_version='funding-category-v1',updated_at=clock_timestamp() WHERE predicate='project.under_program';

-- Read-only history/evidence may retain old labels, but live projects must not own them.
CREATE FUNCTION smartlib.guard_funding_classification_owner() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NEW.object_type='project' AND NEW.attributes ?| ARRAY['funding_source_category','funding_source_category_label','funding_source_classification'] THEN
  RAISE EXCEPTION 'funding source classification belongs to the funding_program, not an individual project' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER project_classification_owner BEFORE INSERT OR UPDATE OF attributes ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_funding_classification_owner();
RESET ROLE;
