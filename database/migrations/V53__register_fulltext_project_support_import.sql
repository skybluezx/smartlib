SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- A paper is a supported output, never the owner/applicant of the grant.
UPDATE smartlib.relation_predicate_definition
SET canonical_label='受项目资助',
    description='论文所述研究工作受到具体项目资助；逆向阅读为项目的资助成果。不得由此推定论文作者是申请人、获批人或负责人，也不等同代表性论著。',
    schema_version='project-support-v2',updated_at=clock_timestamp()
WHERE predicate='publication.supported_by_project';

INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'object','project','individual_grant',key,ARRAY[kind],false,description,'fulltext-project-v1'
FROM (VALUES
 ('grant_number','string','论文原文项目编号；不代表官方核准编号真实性。'),
 ('source','string','项目登记来源。'),
 ('source_import_batch','string','可追溯的导入批次。'),
 ('candidate_project_key','string','审核包候选身份键；不可仅按裸编号跨资助来源合并。'),
 ('source_record_ids','array','支持本对象的原始逐条记录标识。'),
 ('source_authority_names','array','原文及已审核规范化资助来源名称。'),
 ('project_identity_status','string','项目同一性状态，与允许创建对象分离。'),
 ('principal_investigator_status','string','负责人对象关系建立状态；论文作者不能替代项目负责人。'),
 ('funding_source_category','string','可修订的资助来源粗分类代码，非官方行政等级。'),
 ('funding_source_category_label','string','粗分类中文标签。'),
 ('funding_source_classification','object','分类依据、版本、历史、来源引用及待核验事项。'),
 ('governance_notes','array','保留原审核疑问、原文归属冲突及数据使用边界。')
) AS fields(key,kind,description)
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO NOTHING;

INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'relation','publication.supported_by_project','*',key,ARRAY[kind],false,description,'fulltext-project-v1'
FROM (VALUES
 ('relation_label','string','正向语义：论文受项目资助。'),
 ('inverse_relation_label','string','逆向语义：项目的资助成果。'),
 ('source','string','关系依据来源，不把InCites类别匹配当作编号核验。'),
 ('source_import_batch','string','受控导入批次。'),
 ('source_record_id','string','全文审核包逐条记录标识。'),
 ('support_role','string','研究资助成果，非项目归属／负责人关系。'),
 ('principal_investigator_inferred','boolean','本流程固定为false，禁止从作者推断负责人。'),
 ('source_review','object','原始审核状态、原文编号、资助对象表述和未解决问题。'),
 ('funding_source_classification','object','该次论文资助出现的原始分类标签。')
) AS fields(key,kind,description)
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO NOTHING;
RESET ROLE;
