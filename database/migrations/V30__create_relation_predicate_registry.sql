SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

CREATE TABLE IF NOT EXISTS smartlib.relation_predicate_definition (
    predicate text PRIMARY KEY
        CHECK (predicate ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    canonical_label text NOT NULL CHECK (btrim(canonical_label) <> ''),
    description text NOT NULL CHECK (btrim(description) <> ''),
    subject_types text[] NOT NULL CHECK (cardinality(subject_types) > 0),
    target_kind text NOT NULL CHECK (target_kind IN ('object', 'literal', 'either')),
    object_types text[] NOT NULL DEFAULT ARRAY[]::text[],
    inverse_predicate text,
    lifecycle_state text NOT NULL DEFAULT 'active'
        CHECK (lifecycle_state IN ('active', 'deprecated', 'retired')),
    replacement_predicate text,
    schema_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (target_kind = 'literal' AND cardinality(object_types) = 0)
        OR (target_kind IN ('object', 'either') AND cardinality(object_types) > 0)
    ),
    CHECK (replacement_predicate IS NULL OR replacement_predicate <> predicate)
);

CREATE TABLE IF NOT EXISTS smartlib.relation_predicate_alias (
    alias_predicate text PRIMARY KEY
        CHECK (alias_predicate ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    canonical_predicate text NOT NULL
        REFERENCES smartlib.relation_predicate_definition(predicate),
    migration_note text NOT NULL CHECK (btrim(migration_note) <> ''),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (alias_predicate <> canonical_predicate)
);

INSERT INTO smartlib.relation_predicate_definition
    (predicate,canonical_label,description,subject_types,target_kind,object_types,
     lifecycle_state,replacement_predicate,schema_version)
VALUES
    ('person.authored','作者','学者或作者创作、署名于论文；权威来源为 publication_authorship。',ARRAY['person'],'object',ARRAY['publication'],'active',NULL,'relation-v1'),
    ('person.awardee_of','获批人','人员是具体项目的获批人。',ARRAY['person'],'object',ARRAY['project'],'active',NULL,'relation-v1'),
    ('person.leads_project','项目负责人','人员负责具体项目。',ARRAY['person'],'object',ARRAY['project'],'active',NULL,'relation-v1'),
    ('person.affiliated_with','论文时点所属机构','人员在指定论文上下文中所属机构。',ARRAY['person'],'object',ARRAY['organization','department'],'active',NULL,'relation-v1'),
    ('person.collaborates_with','合作','人员之间的合作关系。',ARRAY['person'],'object',ARRAY['person'],'active',NULL,'relation-v1'),
    ('person.member_of_discipline','所属学科','人员归属某一学科。',ARRAY['person'],'object',ARRAY['discipline'],'active',NULL,'relation-v1'),
    ('person.researches','研究','人员研究某一学科或概念。',ARRAY['person'],'object',ARRAY['discipline','concept'],'active',NULL,'relation-v1'),
    ('person.participates_in','参与','人员参与项目或事件。',ARRAY['person'],'object',ARRAY['project','event'],'active',NULL,'relation-v1'),
    ('organization.part_of','机构隶属','机构或院系隶属于上级机构。',ARRAY['organization','department'],'object',ARRAY['organization'],'active',NULL,'relation-v1'),
    ('publication.affiliated_with','论文关联机构','论文署名中出现的机构。',ARRAY['publication'],'object',ARRAY['organization','department'],'active',NULL,'relation-v1'),
    ('publication.classified_as_discipline','论文所属学科','论文被分类到学科节点。',ARRAY['publication'],'object',ARRAY['discipline'],'active',NULL,'relation-v1'),
    ('publication.published_in','发表于','论文发表于期刊；目标必须是已物化的 journal_identity。',ARRAY['publication'],'object',ARRAY['journal'],'active',NULL,'relation-v1'),
    ('publication.supported_by_project','受项目支持','论文明确由具体编号项目支持。',ARRAY['publication'],'object',ARRAY['project'],'active',NULL,'relation-v1'),
    ('publication.acknowledges_funder','致谢资助方','论文仅确认资助来源，尚未定位具体项目。',ARRAY['publication'],'object',ARRAY['organization','funding_program'],'active',NULL,'relation-v1'),
    ('project.under_program','属于资助计划','具体项目属于资助计划或项目类别。',ARRAY['project'],'object',ARRAY['funding_program'],'active',NULL,'relation-v1'),
    ('project.funded_by','由机构资助','具体项目由资助机构资助。',ARRAY['project'],'object',ARRAY['organization'],'active',NULL,'relation-v1'),
    ('project.has_representative_publication','代表性论文','项目关联一篇代表性论文。',ARRAY['project'],'object',ARRAY['publication'],'active',NULL,'relation-v1'),
    ('funding_program.administered_by','由机构管理','资助计划由机构管理。',ARRAY['funding_program'],'object',ARRAY['organization'],'active',NULL,'relation-v1'),
    ('taxonomy.contains','分类体系包含','分类体系或概念根节点包含学科。',ARRAY['concept'],'object',ARRAY['discipline'],'active',NULL,'relation-v1'),
    ('taxonomy.broader','上位学科','学科的上位分类。',ARRAY['discipline'],'object',ARRAY['discipline'],'active',NULL,'relation-v1'),
    ('taxonomy.replaces','替代学科','新版学科节点替代旧版节点。',ARRAY['discipline'],'object',ARRAY['discipline'],'active',NULL,'relation-v1'),
    ('funding_organization.part_of','历史资助方隶属','历史关系名；统一改用 organization.part_of。',ARRAY['organization'],'object',ARRAY['organization'],'deprecated','organization.part_of','relation-v1'),
    ('publication.funded_by','历史论文资助关系','语义不明确的历史关系；具体项目和资助方必须分别建模。',ARRAY['publication'],'object',ARRAY['project','organization','funding_program'],'deprecated','publication.supported_by_project','relation-v1')
ON CONFLICT (predicate) DO UPDATE SET
    canonical_label=EXCLUDED.canonical_label,
    description=EXCLUDED.description,
    subject_types=EXCLUDED.subject_types,
    target_kind=EXCLUDED.target_kind,
    object_types=EXCLUDED.object_types,
    lifecycle_state=EXCLUDED.lifecycle_state,
    replacement_predicate=EXCLUDED.replacement_predicate,
    schema_version=EXCLUDED.schema_version,
    updated_at=clock_timestamp();

INSERT INTO smartlib.relation_predicate_alias
    (alias_predicate,canonical_predicate,migration_note)
VALUES
    ('funding_organization.part_of','organization.part_of','资助机构统一使用 organization 类型及 organization.part_of。'),
    ('publication.funded_by','publication.supported_by_project','旧关系语义不明确；若目标不是 project，必须改用 publication.acknowledges_funder。')
ON CONFLICT (alias_predicate) DO UPDATE SET
    canonical_predicate=EXCLUDED.canonical_predicate,
    migration_note=EXCLUDED.migration_note;

CREATE OR REPLACE FUNCTION smartlib.validate_relation_predicate_contract()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib
AS $function$
DECLARE
    definition smartlib.relation_predicate_definition%ROWTYPE;
    subject_type text;
    object_type_value text;
BEGIN
    SELECT * INTO definition
      FROM smartlib.relation_predicate_definition
     WHERE predicate=NEW.predicate;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unregistered relation predicate: %', NEW.predicate
            USING ERRCODE='23514';
    END IF;
    IF definition.lifecycle_state <> 'active' THEN
        RAISE EXCEPTION 'relation predicate % is %; use %', NEW.predicate,
            definition.lifecycle_state,COALESCE(definition.replacement_predicate,'a registered active predicate')
            USING ERRCODE='23514';
    END IF;

    SELECT object_type INTO subject_type
      FROM smartlib.knowledge_object WHERE object_id=NEW.subject_id;
    IF subject_type IS NULL OR NOT subject_type=ANY(definition.subject_types) THEN
        RAISE EXCEPTION 'predicate % does not allow subject type %; allowed=%',
            NEW.predicate,COALESCE(subject_type,'missing'),definition.subject_types
            USING ERRCODE='23514';
    END IF;

    IF NEW.object_id IS NOT NULL THEN
        IF definition.target_kind='literal' THEN
            RAISE EXCEPTION 'predicate % only allows literal targets',NEW.predicate
                USING ERRCODE='23514';
        END IF;
        SELECT object_type INTO object_type_value
          FROM smartlib.knowledge_object WHERE object_id=NEW.object_id;
        IF object_type_value IS NULL OR NOT object_type_value=ANY(definition.object_types) THEN
            RAISE EXCEPTION 'predicate % does not allow object type %; allowed=%',
                NEW.predicate,COALESCE(object_type_value,'missing'),definition.object_types
                USING ERRCODE='23514';
        END IF;
    ELSIF definition.target_kind='object' THEN
        RAISE EXCEPTION 'predicate % requires an object target',NEW.predicate
            USING ERRCODE='23514';
    END IF;

    IF NEW.predicate='publication.published_in' AND NOT EXISTS (
        SELECT 1 FROM smartlib.journal_identity identity
         WHERE identity.knowledge_object_id=NEW.object_id
    ) THEN
        RAISE EXCEPTION 'publication.published_in target must be materialized from journal_identity'
            USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS relation_predicate_contract_guard ON smartlib.relation_assertion;
CREATE TRIGGER relation_predicate_contract_guard
BEFORE INSERT OR UPDATE OF subject_id,predicate,object_id,literal_value
ON smartlib.relation_assertion
FOR EACH ROW EXECUTE FUNCTION smartlib.validate_relation_predicate_contract();

DO $constraint$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname='relation_assertion_predicate_registry_fkey'
           AND conrelid='smartlib.relation_assertion'::regclass
    ) THEN
        ALTER TABLE smartlib.relation_assertion
            ADD CONSTRAINT relation_assertion_predicate_registry_fkey
            FOREIGN KEY (predicate)
            REFERENCES smartlib.relation_predicate_definition(predicate)
            NOT VALID;
        ALTER TABLE smartlib.relation_assertion
            VALIDATE CONSTRAINT relation_assertion_predicate_registry_fkey;
    END IF;
END
$constraint$;

CREATE OR REPLACE VIEW smartlib.relation_predicate_catalog AS
SELECT definition.predicate,definition.canonical_label,definition.description,
       definition.subject_types,definition.target_kind,definition.object_types,
       definition.lifecycle_state,definition.replacement_predicate,
       count(relation.relation_id)::bigint AS current_relation_count
  FROM smartlib.relation_predicate_definition definition
  LEFT JOIN smartlib.relation_assertion relation USING(predicate)
 GROUP BY definition.predicate,definition.canonical_label,definition.description,
          definition.subject_types,definition.target_kind,definition.object_types,
          definition.lifecycle_state,definition.replacement_predicate;

GRANT SELECT ON smartlib.relation_predicate_definition,
    smartlib.relation_predicate_alias,smartlib.relation_predicate_catalog
TO smartlib_app,smartlib_readonly;

COMMENT ON TABLE smartlib.relation_predicate_definition IS
    'Authoritative relation vocabulary and allowed subject/target object types.';
COMMENT ON TABLE smartlib.relation_predicate_alias IS
    'Deprecated or ambiguous predicate names and their migration guidance.';

RESET ROLE;
