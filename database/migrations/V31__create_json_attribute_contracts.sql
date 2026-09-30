SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE IF NOT EXISTS smartlib.attribute_definition (
    entity_kind text NOT NULL CHECK (entity_kind IN ('object','relation')),
    entity_type text NOT NULL CHECK (btrim(entity_type) <> ''),
    record_kind text NOT NULL DEFAULT '*',
    attribute_key text NOT NULL CHECK (attribute_key ~ '^[A-Za-z][A-Za-z0-9_.-]{0,127}$'),
    allowed_json_types text[] NOT NULL CHECK (cardinality(allowed_json_types) > 0),
    required boolean NOT NULL DEFAULT false,
    description text NOT NULL CHECK (btrim(description) <> ''),
    schema_version text NOT NULL,
    lifecycle_state text NOT NULL DEFAULT 'active'
        CHECK (lifecycle_state IN ('active','deprecated','retired')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (entity_kind,entity_type,record_kind,attribute_key),
    CHECK (allowed_json_types <@ ARRAY['object','array','string','number','boolean','null']::text[])
);

INSERT INTO smartlib.attribute_definition
    (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,
     required,description,schema_version)
SELECT 'object',object.object_type,COALESCE(object.attributes->>'record_kind','*'),
       pair.key,array_agg(DISTINCT jsonb_typeof(pair.value) ORDER BY jsonb_typeof(pair.value)),
       false,'V31迁移时从现有合规数据建立的对象属性基线。','attribute-v1'
  FROM smartlib.knowledge_object object
 CROSS JOIN LATERAL jsonb_each(object.attributes) pair
 GROUP BY object.object_type,COALESCE(object.attributes->>'record_kind','*'),pair.key
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO UPDATE SET
    allowed_json_types=EXCLUDED.allowed_json_types,
    schema_version=EXCLUDED.schema_version,
    updated_at=clock_timestamp();

INSERT INTO smartlib.attribute_definition
    (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,
     required,description,schema_version)
SELECT 'relation',relation.predicate,'*',pair.key,
       array_agg(DISTINCT jsonb_typeof(pair.value) ORDER BY jsonb_typeof(pair.value)),
       false,'V31迁移时从现有合规数据建立的关系属性基线。','attribute-v1'
  FROM smartlib.relation_assertion relation
 CROSS JOIN LATERAL jsonb_each(relation.attributes) pair
 GROUP BY relation.predicate,pair.key
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO UPDATE SET
    allowed_json_types=EXCLUDED.allowed_json_types,
    schema_version=EXCLUDED.schema_version,
    updated_at=clock_timestamp();

-- Forward contracts for affiliation entities that may legitimately be absent in
-- a clean database but are created by the full-text affiliation workflow later.
INSERT INTO smartlib.attribute_definition
    (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,
     required,description,schema_version)
VALUES
    ('object','organization','*','synthetic',ARRAY['boolean'],false,'是否为合成测试对象。','affiliation-attribute-v1'),
    ('object','organization','*','source',ARRAY['string'],true,'机构识别来源。','affiliation-attribute-v1'),
    ('object','organization','*','rule_version',ARRAY['string'],false,'机构规范化规则版本。','affiliation-attribute-v1'),
    ('object','organization','*','organization_level',ARRAY['string'],false,'机构或分支机构层级。','affiliation-attribute-v1'),
    ('object','organization','*','parent_organization_id',ARRAY['string','null'],false,'上级机构对象ID。','affiliation-attribute-v1'),
    ('object','organization','*','identity_resolution_status',ARRAY['string'],true,'机构身份规范化状态。','affiliation-attribute-v1'),
    ('object','organization','*','source_raw_examples',ARRAY['array'],false,'支持规范名称的原始署名示例。','affiliation-attribute-v1'),
    ('object','organization','*','provisional_best_effort',ARRAY['boolean'],false,'是否为尽力而为的暂定识别。','affiliation-attribute-v1'),
    ('object','organization','*','needs_confirmation',ARRAY['boolean'],false,'是否仍需人工确认。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','source',ARRAY['string'],true,'任职关系证据来源。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','raw_affiliation',ARRAY['string'],false,'原始机构署名。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','mapping_method',ARRAY['string'],false,'机构匹配方法。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','publication_id',ARRAY['string'],false,'单篇支持论文ID。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','publication_ids',ARRAY['array'],false,'全部支持论文ID。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','evidence_count',ARRAY['number'],false,'支持论文数量。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','assignments',ARRAY['array'],false,'逐篇机构归属明细。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','rule_version',ARRAY['string'],true,'机构关系规则版本。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','provisional_best_effort',ARRAY['boolean'],false,'是否为暂定关系。','affiliation-attribute-v1'),
    ('relation','person.affiliated_with','*','needs_confirmation',ARRAY['boolean'],false,'是否仍需人工确认。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','source',ARRAY['string'],true,'论文机构关系证据来源。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','authors',ARRAY['array'],true,'支持该机构关系的作者明细。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','author_count',ARRAY['number'],true,'关联作者数量。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','rule_version',ARRAY['string'],true,'机构关系规则版本。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','provisional_best_effort',ARRAY['boolean'],false,'是否为暂定关系。','affiliation-attribute-v1'),
    ('relation','publication.affiliated_with','*','needs_confirmation',ARRAY['boolean'],false,'是否仍需人工确认。','affiliation-attribute-v1'),
    ('relation','organization.part_of','*','source',ARRAY['string'],true,'机构层级证据来源。','affiliation-attribute-v1'),
    ('relation','organization.part_of','*','rule_version',ARRAY['string'],true,'机构层级规则版本。','affiliation-attribute-v1')
ON CONFLICT (entity_kind,entity_type,record_kind,attribute_key) DO UPDATE SET
    allowed_json_types=EXCLUDED.allowed_json_types,
    required=EXCLUDED.required,
    description=EXCLUDED.description,
    schema_version=EXCLUDED.schema_version,
    lifecycle_state='active',
    updated_at=clock_timestamp();

UPDATE smartlib.attribute_definition
   SET required=true,description='对象子类型标识；决定适用的属性契约。',updated_at=clock_timestamp()
 WHERE entity_kind='object' AND attribute_key='record_kind'
   AND (entity_type,record_kind) IN (
       ('project','individual_grant'),
       ('funding_program','annual_funding_program'),
       ('journal','journal')
   );

UPDATE smartlib.attribute_definition
   SET required=true,updated_at=clock_timestamp()
 WHERE entity_kind='object'
   AND (
       (entity_type='project' AND record_kind='individual_grant'
        AND attribute_key IN ('dataset_id','dataset_version','year','funding_program_id',
                              'principal_investigator_person_id'))
       OR (entity_type='funding_program' AND record_kind='annual_funding_program'
           AND attribute_key IN ('year','funding_agency','funding_scheme'))
       OR (entity_type='journal' AND record_kind='journal'
           AND attribute_key IN ('journal_identity_id','source'))
   );

UPDATE smartlib.attribute_definition
   SET required=true,updated_at=clock_timestamp()
 WHERE entity_kind='relation' AND record_kind='*'
   AND (
       (entity_type='person.authored'
        AND attribute_key IN ('author_order','roles','role_source','rule_version'))
       OR (entity_type='publication.published_in'
           AND attribute_key IN ('journal_name_raw','match_basis','publication_year','relation_label'))
       OR (entity_type='project.has_representative_publication'
           AND attribute_key IN ('relation_label','year'))
       OR (entity_type IN ('taxonomy.broader','taxonomy.contains','taxonomy.replaces')
           AND attribute_key IN ('dataset_id','dataset_version','scheme'))
   );

CREATE OR REPLACE FUNCTION smartlib.validate_registered_attributes(
    p_entity_kind text,
    p_entity_type text,
    p_record_kind text,
    p_attributes jsonb
)
RETURNS void
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    pair record;
    definition smartlib.attribute_definition%ROWTYPE;
    required_definition record;
    selected_record_kind text := COALESCE(NULLIF(p_record_kind,''),'*');
BEGIN
    IF jsonb_typeof(p_attributes) <> 'object' THEN
        RAISE EXCEPTION 'attributes must be a JSON object' USING ERRCODE='23514';
    END IF;
    FOR pair IN SELECT key,value FROM jsonb_each(p_attributes)
    LOOP
        SELECT * INTO definition
          FROM smartlib.attribute_definition
         WHERE entity_kind=p_entity_kind
           AND entity_type=p_entity_type
           AND record_kind IN (selected_record_kind,'*')
           AND attribute_key=pair.key
           AND lifecycle_state='active'
         ORDER BY CASE WHEN record_kind=selected_record_kind THEN 0 ELSE 1 END
         LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'unregistered % attribute %.%[%]',
                p_entity_kind,p_entity_type,selected_record_kind,pair.key
                USING ERRCODE='23514';
        END IF;
        IF NOT jsonb_typeof(pair.value)=ANY(definition.allowed_json_types) THEN
            RAISE EXCEPTION 'invalid JSON type for %.%[%].%: got %, allowed %',
                p_entity_kind,p_entity_type,selected_record_kind,pair.key,
                jsonb_typeof(pair.value),definition.allowed_json_types
                USING ERRCODE='23514';
        END IF;
    END LOOP;
    FOR required_definition IN
        SELECT DISTINCT ON (attribute_key) attribute_key
          FROM smartlib.attribute_definition
         WHERE entity_kind=p_entity_kind
           AND entity_type=p_entity_type
           AND record_kind IN (selected_record_kind,'*')
           AND required
           AND lifecycle_state='active'
         ORDER BY attribute_key,
                  CASE WHEN record_kind=selected_record_kind THEN 0 ELSE 1 END
    LOOP
        IF NOT p_attributes ? required_definition.attribute_key THEN
            RAISE EXCEPTION 'missing required % attribute %.%[%]',
                p_entity_kind,p_entity_type,selected_record_kind,
                required_definition.attribute_key USING ERRCODE='23514';
        END IF;
    END LOOP;
END
$function$;

CREATE OR REPLACE FUNCTION smartlib.enforce_knowledge_object_attribute_contract()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    PERFORM smartlib.validate_registered_attributes(
        'object',NEW.object_type,COALESCE(NEW.attributes->>'record_kind','*'),NEW.attributes
    );
    RETURN NEW;
END
$function$;

CREATE OR REPLACE FUNCTION smartlib.enforce_relation_attribute_contract()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
BEGIN
    PERFORM smartlib.validate_registered_attributes(
        'relation',NEW.predicate,'*',NEW.attributes
    );
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS knowledge_object_attribute_contract_guard ON smartlib.knowledge_object;
CREATE TRIGGER knowledge_object_attribute_contract_guard
BEFORE INSERT OR UPDATE OF object_type,attributes ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_knowledge_object_attribute_contract();

DROP TRIGGER IF EXISTS relation_attribute_contract_guard ON smartlib.relation_assertion;
CREATE TRIGGER relation_attribute_contract_guard
BEFORE INSERT OR UPDATE OF predicate,attributes ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_relation_attribute_contract();

CREATE OR REPLACE VIEW smartlib.attribute_contract_summary AS
SELECT definition.entity_kind,definition.entity_type,definition.record_kind,
       definition.schema_version,count(*)::bigint AS attribute_count,
       count(*) FILTER (WHERE definition.required)::bigint AS required_attribute_count
  FROM smartlib.attribute_definition definition
 WHERE definition.lifecycle_state='active'
 GROUP BY definition.entity_kind,definition.entity_type,definition.record_kind,
          definition.schema_version;

GRANT SELECT ON smartlib.attribute_definition,smartlib.attribute_contract_summary
TO smartlib_app,smartlib_readonly;
GRANT EXECUTE ON FUNCTION smartlib.validate_registered_attributes(text,text,text,jsonb)
TO smartlib_app,smartlib_readonly;

COMMENT ON TABLE smartlib.attribute_definition IS
    'Versioned top-level JSON attribute vocabulary. Unknown keys and incompatible JSON types are rejected.';

RESET ROLE;
