SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- MeSH is a concept vocabulary, not an education discipline catalogue.
UPDATE smartlib.relation_predicate_definition
SET object_types=ARRAY['discipline','concept'], schema_version='taxonomy-v2',updated_at=clock_timestamp()
WHERE predicate='taxonomy.contains';
UPDATE smartlib.relation_predicate_definition
SET subject_types=ARRAY['discipline','concept'],object_types=ARRAY['discipline','concept'],
    schema_version='taxonomy-v2',updated_at=clock_timestamp()
WHERE predicate IN ('taxonomy.broader','taxonomy.replaces');

INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'object',kind,'*',key,ARRAY[value],false,'研究分类标准：带版本的来源与结构属性。','research-standard-v1'
FROM unnest(ARRAY['concept','discipline']) kind
CROSS JOIN (VALUES
 ('standard_library','string'),('scheme_version','string'),('aliases','array'),
 ('tree_numbers','array'),('allowable_qualifiers','array'),('source_locator','object'),
 ('source_checksum','string'),('standard_quality_notes','array'),('code_kind','string')
) fields(key,value)
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO NOTHING;

CREATE UNIQUE INDEX research_standard_version_code_unique ON smartlib.knowledge_object
 ((attributes->>'scheme'),(attributes->>'scheme_version'),(attributes->>'scheme_code'))
WHERE attributes->>'standard_library'='research-classification'
  AND system_to='infinity'::timestamptz;

CREATE FUNCTION smartlib.validate_research_standard_relation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,smartlib AS $$
DECLARE a jsonb; b jsonb;
BEGIN
 IF NEW.predicate NOT IN ('taxonomy.contains','taxonomy.broader') THEN RETURN NEW; END IF;
 SELECT attributes INTO a FROM smartlib.knowledge_object WHERE object_id=NEW.subject_id;
 SELECT attributes INTO b FROM smartlib.knowledge_object WHERE object_id=NEW.object_id;
 IF a->>'standard_library'='research-classification' OR b->>'standard_library'='research-classification' THEN
   IF a->>'standard_library' IS DISTINCT FROM b->>'standard_library'
      OR a->>'scheme' IS DISTINCT FROM b->>'scheme'
      OR a->>'scheme_version' IS DISTINCT FROM b->>'scheme_version'
      OR NEW.subject_id=NEW.object_id THEN
     RAISE EXCEPTION 'Standard hierarchy must stay within one scheme and version';
   END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER research_standard_relation_guard BEFORE INSERT OR UPDATE
ON smartlib.relation_assertion FOR EACH ROW EXECUTE FUNCTION smartlib.validate_research_standard_relation();
RESET ROLE;
