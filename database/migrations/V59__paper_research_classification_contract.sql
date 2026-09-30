SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;
INSERT INTO smartlib.relation_predicate_definition
 (predicate,canonical_label,description,subject_types,target_kind,object_types,schema_version)
VALUES ('publication.has_research_topic','论文研究主题','论文到版本化MeSH主题的标引或推断，不代表学者正式学科归属。',
 ARRAY['publication'],'object',ARRAY['concept'],'paper-classification-v1')
ON CONFLICT DO NOTHING;
INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'relation',p,'*',k,ARRAY[t],false,'论文分类来源、版本、内容证据与推断边界。','paper-classification-v1'
FROM unnest(ARRAY['publication.classified_as_discipline','publication.has_research_topic']) p
CROSS JOIN (VALUES
 ('scheme','string'),('scheme_version','string'),('code','string'),('classification_role','string'),
 ('source_kind','string'),('method_version','string'),('source_import_batch','string'),('evidence_excerpt','string'),
 ('fulltext_resource_id','string'),('fulltext_checksum','string'),('review_note','string'),('score_interpretation','string'),
 ('rationale','string'),('content_basis','string'),('special_note','string'),('major_topic','boolean'),
 ('qualifiers','array'),('external_record_url','string'),('external_source_path','string'),
 ('assignment_year_known','boolean'),('matched_phrase','string'),('semantic_override','boolean'),('external_source_record','object')
) fields(k,t) ON CONFLICT DO NOTHING;
RESET ROLE;
