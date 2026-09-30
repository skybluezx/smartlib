SET ROLE smartlib_owner;
CREATE FUNCTION smartlib.valid_orcid(v text) RETURNS boolean LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE digits text; total integer:=0; i integer; check_digit text;
BEGIN
 IF v !~ '^[0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$' THEN RETURN false; END IF;
 digits:=replace(v,'-','');
 FOR i IN 1..15 LOOP total:=(total+substr(digits,i,1)::integer)*2; END LOOP;
 check_digit:=((12-total%11)%11)::text;
 IF check_digit='10' THEN check_digit:='X'; END IF;
 RETURN right(digits,1)=check_digit;
END $$;

CREATE TABLE smartlib.person_profile (
 object_id uuid PRIMARY KEY REFERENCES smartlib.knowledge_object(object_id),
 given_name text CHECK(length(given_name)<=200), family_name text CHECK(length(family_name)<=200), preferred_language text CHECK(preferred_language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE smartlib.person_identifier (
 identifier_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 object_id uuid NOT NULL REFERENCES smartlib.person_profile(object_id),
 identifier_type text NOT NULL CHECK(identifier_type ~ '^[a-z][a-z0-9_.-]{1,63}$'),
 normalized_value text NOT NULL CHECK(btrim(normalized_value)<>'' AND length(normalized_value)<=500),
 verification_status text NOT NULL DEFAULT 'matched' CHECK(verification_status IN ('matched','rejected')),
 source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(object_id,identifier_type,normalized_value)
);
CREATE UNIQUE INDEX person_identifier_unique_active ON smartlib.person_identifier(identifier_type,normalized_value)
 WHERE verification_status='matched';
CREATE UNIQUE INDEX person_one_active_identifier ON smartlib.person_identifier(object_id,identifier_type)
 WHERE verification_status='matched';
CREATE TABLE smartlib.person_name_variant (
 name_variant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 object_id uuid NOT NULL REFERENCES smartlib.person_profile(object_id),
 name text NOT NULL CHECK(btrim(name)<>'' AND length(name)<=500),
 normalized_name text GENERATED ALWAYS AS (lower(regexp_replace(btrim(name),'\s+',' ','g'))) STORED,
 name_kind text NOT NULL CHECK(name_kind IN ('source_name','alias')),
 verification_status text NOT NULL DEFAULT 'matched' CHECK(verification_status IN ('matched','rejected')),
 source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(object_id,normalized_name,name_kind)
);

CREATE TABLE smartlib.organization_profile (
 object_id uuid PRIMARY KEY REFERENCES smartlib.knowledge_object(object_id),
 organization_type text CHECK(organization_type IN ('university','hospital','research_institute','company','government','nonprofit','department','other')), country_code text CHECK(country_code ~ '^[A-Z]{2}$'),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE smartlib.organization_identifier (
 identifier_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 object_id uuid NOT NULL REFERENCES smartlib.organization_profile(object_id),
 identifier_type text NOT NULL CHECK(identifier_type ~ '^[a-z][a-z0-9_.-]{1,63}$'),
 normalized_value text NOT NULL CHECK(btrim(normalized_value)<>'' AND length(normalized_value)<=500),
 verification_status text NOT NULL DEFAULT 'matched' CHECK(verification_status IN ('matched','rejected')),
 source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(object_id,identifier_type,normalized_value)
);
CREATE UNIQUE INDEX organization_identifier_unique_active ON smartlib.organization_identifier(identifier_type,normalized_value)
 WHERE verification_status='matched';
CREATE UNIQUE INDEX organization_one_active_identifier ON smartlib.organization_identifier(object_id,identifier_type)
 WHERE verification_status='matched';
CREATE TABLE smartlib.organization_name_variant (
 name_variant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 object_id uuid NOT NULL REFERENCES smartlib.organization_profile(object_id),
 name text NOT NULL CHECK(btrim(name)<>'' AND length(name)<=500),
 normalized_name text GENERATED ALWAYS AS (lower(regexp_replace(btrim(name),'\s+',' ','g'))) STORED,
 name_kind text NOT NULL CHECK(name_kind IN ('source_name','alias')),
 verification_status text NOT NULL DEFAULT 'matched' CHECK(verification_status IN ('matched','rejected')),
 source_reference_id uuid REFERENCES smartlib.source_reference(source_reference_id),
 evidence_id uuid REFERENCES smartlib.evidence_record(evidence_id),
 submission_id uuid REFERENCES smartlib.change_submission(submission_id),
 created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(object_id,normalized_name,name_kind)
);

ALTER TABLE smartlib.person_identifier ADD CONSTRAINT person_orcid_check
 CHECK(identifier_type<>'orcid' OR smartlib.valid_orcid(normalized_value));
ALTER TABLE smartlib.organization_identifier ADD CONSTRAINT organization_ror_check
 CHECK(identifier_type<>'ror' OR normalized_value ~ '^0[0-9a-hjkmnp-tv-z]{6}[0-9]{2}$');
CREATE FUNCTION smartlib.validate_identity_owner() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,smartlib AS $$
DECLARE kind text;
BEGIN
 SELECT object_type INTO kind FROM smartlib.knowledge_object WHERE object_id=NEW.object_id AND system_to='infinity';
 IF (TG_TABLE_NAME LIKE 'person_%' AND kind IS DISTINCT FROM 'person')
 OR (TG_TABLE_NAME LIKE 'organization_%' AND (kind IS NULL OR kind NOT IN ('organization','department'))) THEN
 RAISE EXCEPTION 'Identity profile owner has incompatible type' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER person_profile_type BEFORE INSERT OR UPDATE ON smartlib.person_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.validate_identity_owner();
INSERT INTO smartlib.person_profile(object_id,created_by,created_at,updated_at)
 SELECT object_id,created_by,created_at,updated_at FROM smartlib.knowledge_object
 WHERE object_type IN ('person') AND system_to='infinity';
INSERT INTO smartlib.person_name_variant(object_id,name,name_kind,source_reference_id,created_by)
 SELECT o.object_id,o.canonical_name,'source_name',
 (SELECT r.source_reference_id FROM smartlib.source_reference r WHERE r.object_id=o.object_id
 ORDER BY r.created_at,r.source_reference_id LIMIT 1),o.created_by
 FROM smartlib.knowledge_object o WHERE o.object_type IN ('person') AND o.system_to='infinity';

CREATE TRIGGER organization_profile_type BEFORE INSERT OR UPDATE ON smartlib.organization_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.validate_identity_owner();
INSERT INTO smartlib.organization_profile(object_id,created_by,created_at,updated_at)
 SELECT object_id,created_by,created_at,updated_at FROM smartlib.knowledge_object
 WHERE object_type IN ('organization','department') AND system_to='infinity';
INSERT INTO smartlib.organization_name_variant(object_id,name,name_kind,source_reference_id,created_by)
 SELECT o.object_id,o.canonical_name,'source_name',
 (SELECT r.source_reference_id FROM smartlib.source_reference r WHERE r.object_id=o.object_id
 ORDER BY r.created_at,r.source_reference_id LIMIT 1),o.created_by
 FROM smartlib.knowledge_object o WHERE o.object_type IN ('organization','department') AND o.system_to='infinity';

CREATE FUNCTION smartlib.initialize_identity_profile() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NEW.object_type='person' THEN
  INSERT INTO smartlib.person_profile(object_id,created_by) VALUES(NEW.object_id,NEW.created_by);
  INSERT INTO smartlib.person_name_variant(object_id,name,name_kind,created_by)
   VALUES(NEW.object_id,NEW.canonical_name,'source_name',NEW.created_by);
 ELSIF NEW.object_type IN ('organization','department') THEN
  INSERT INTO smartlib.organization_profile(object_id,created_by) VALUES(NEW.object_id,NEW.created_by);
  INSERT INTO smartlib.organization_name_variant(object_id,name,name_kind,created_by)
   VALUES(NEW.object_id,NEW.canonical_name,'source_name',NEW.created_by);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER initialize_identity_profile AFTER INSERT ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.initialize_identity_profile();

ALTER TABLE smartlib.person_profile ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.person_profile TO smartlib_app;
GRANT SELECT ON smartlib.person_profile TO smartlib_readonly;
CREATE POLICY person_profile_read ON smartlib.person_profile FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_profile.object_id));
CREATE POLICY person_profile_insert ON smartlib.person_profile FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_profile.object_id));
CREATE POLICY person_profile_update ON smartlib.person_profile FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_profile.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_profile.object_id));
CREATE TRIGGER person_profile_updated BEFORE UPDATE ON smartlib.person_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER person_profile_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.person_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('object_id');

ALTER TABLE smartlib.person_identifier ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.person_identifier TO smartlib_app;
GRANT SELECT ON smartlib.person_identifier TO smartlib_readonly;
CREATE POLICY person_identifier_read ON smartlib.person_identifier FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_identifier.object_id));
CREATE POLICY person_identifier_insert ON smartlib.person_identifier FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_identifier.object_id));
CREATE POLICY person_identifier_update ON smartlib.person_identifier FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_identifier.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_identifier.object_id));
CREATE TRIGGER person_identifier_updated BEFORE UPDATE ON smartlib.person_identifier
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER person_identifier_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.person_identifier
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('identifier_id');

ALTER TABLE smartlib.person_name_variant ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.person_name_variant TO smartlib_app;
GRANT SELECT ON smartlib.person_name_variant TO smartlib_readonly;
CREATE POLICY person_name_variant_read ON smartlib.person_name_variant FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_name_variant.object_id));
CREATE POLICY person_name_variant_insert ON smartlib.person_name_variant FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_name_variant.object_id));
CREATE POLICY person_name_variant_update ON smartlib.person_name_variant FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_name_variant.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=person_name_variant.object_id));
CREATE TRIGGER person_name_variant_updated BEFORE UPDATE ON smartlib.person_name_variant
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER person_name_variant_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.person_name_variant
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('name_variant_id');

ALTER TABLE smartlib.organization_profile ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.organization_profile TO smartlib_app;
GRANT SELECT ON smartlib.organization_profile TO smartlib_readonly;
CREATE POLICY organization_profile_read ON smartlib.organization_profile FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_profile.object_id));
CREATE POLICY organization_profile_insert ON smartlib.organization_profile FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_profile.object_id));
CREATE POLICY organization_profile_update ON smartlib.organization_profile FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_profile.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_profile.object_id));
CREATE TRIGGER organization_profile_updated BEFORE UPDATE ON smartlib.organization_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER organization_profile_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.organization_profile
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('object_id');

ALTER TABLE smartlib.organization_identifier ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.organization_identifier TO smartlib_app;
GRANT SELECT ON smartlib.organization_identifier TO smartlib_readonly;
CREATE POLICY organization_identifier_read ON smartlib.organization_identifier FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_identifier.object_id));
CREATE POLICY organization_identifier_insert ON smartlib.organization_identifier FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_identifier.object_id));
CREATE POLICY organization_identifier_update ON smartlib.organization_identifier FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_identifier.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_identifier.object_id));
CREATE TRIGGER organization_identifier_updated BEFORE UPDATE ON smartlib.organization_identifier
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER organization_identifier_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.organization_identifier
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('identifier_id');

ALTER TABLE smartlib.organization_name_variant ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE ON smartlib.organization_name_variant TO smartlib_app;
GRANT SELECT ON smartlib.organization_name_variant TO smartlib_readonly;
CREATE POLICY organization_name_variant_read ON smartlib.organization_name_variant FOR SELECT TO smartlib_app,smartlib_readonly
 USING(EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_name_variant.object_id));
CREATE POLICY organization_name_variant_insert ON smartlib.organization_name_variant FOR INSERT TO smartlib_app
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_name_variant.object_id));
CREATE POLICY organization_name_variant_update ON smartlib.organization_name_variant FOR UPDATE TO smartlib_app
 USING(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_name_variant.object_id))
 WITH CHECK(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide')
 AND EXISTS(SELECT 1 FROM smartlib.knowledge_object o WHERE o.object_id=organization_name_variant.object_id));
CREATE TRIGGER organization_name_variant_updated BEFORE UPDATE ON smartlib.organization_name_variant
 FOR EACH ROW EXECUTE FUNCTION smartlib.set_updated_at();
CREATE TRIGGER organization_name_variant_history AFTER INSERT OR UPDATE OR DELETE ON smartlib.organization_name_variant
 FOR EACH ROW EXECUTE FUNCTION smartlib.capture_entity_revision('name_variant_id');

CREATE FUNCTION smartlib.identity_search_aliases(p_id uuid) RETURNS text[] LANGUAGE sql STABLE
SET search_path=pg_catalog,smartlib AS $$
SELECT COALESCE(array_agg(DISTINCT name ORDER BY name),ARRAY[]::text[]) FROM (
 SELECT name FROM smartlib.person_name_variant WHERE object_id=p_id AND verification_status='matched'
 UNION ALL SELECT name FROM smartlib.organization_name_variant WHERE object_id=p_id AND verification_status='matched'
 UNION ALL SELECT jsonb_array_elements_text(CASE WHEN jsonb_typeof(attributes->'aliases')='array'
 THEN attributes->'aliases' ELSE '[]'::jsonb END) FROM smartlib.knowledge_object
 WHERE object_id=p_id AND object_type NOT IN ('person','organization','department')
) names;
$$;

CREATE OR REPLACE FUNCTION smartlib_projection.refresh_postgres_search_event(p_event_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, smartlib, smartlib_projection
AS $function$
DECLARE
    selected_event smartlib.outbox_event%ROWTYPE;
    selected_object smartlib.knowledge_object%ROWTYPE;
    selected_aliases text[];
    selected_policy_tags text[];
    selected_policy_version text;
    result_document jsonb;
BEGIN
    SELECT * INTO selected_event
    FROM smartlib.outbox_event
    WHERE event_id = p_event_id
      AND aggregate_type = 'knowledge_object';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown knowledge object event %', p_event_id USING ERRCODE = '22023';
    END IF;

    SELECT * INTO selected_object
    FROM smartlib.knowledge_object
    WHERE object_id = selected_event.aggregate_id
      AND system_to = 'infinity'::timestamptz;

    IF FOUND THEN
        selected_aliases:=smartlib.identity_search_aliases(selected_object.object_id);

        SELECT
            COALESCE(array_agg(tag.code ORDER BY tag.code), ARRAY[]::text[]),
            COALESCE(string_agg(tag.code || '@' || tag.policy_version, ',' ORDER BY tag.code), 'none')
        INTO selected_policy_tags, selected_policy_version
        FROM smartlib.object_policy_tag AS assignment
        JOIN smartlib.policy_tag AS tag ON tag.policy_tag_id = assignment.policy_tag_id
        WHERE assignment.object_id = selected_object.object_id;

        INSERT INTO smartlib_projection.search_document (
            object_id, object_type, canonical_name, aliases, description, visibility,
            created_by, policy_tags, object_version, policy_version, projection_version,
            source_updated_at, projected_at, search_vector
        ) VALUES (
            selected_object.object_id,
            selected_object.object_type,
            selected_object.canonical_name,
            selected_aliases,
            selected_object.description,
            selected_object.visibility,
            selected_object.created_by,
            selected_policy_tags,
            selected_object.version,
            selected_policy_version,
            'search-document-v1',
            selected_object.updated_at,
            clock_timestamp(),
            setweight(to_tsvector('simple', selected_object.canonical_name), 'A') ||
            setweight(to_tsvector('simple', array_to_string(selected_aliases, ' ')), 'A') ||
            setweight(to_tsvector('simple', COALESCE(selected_object.description, '')), 'B')
        )
        ON CONFLICT (object_id) DO UPDATE SET
            object_type = EXCLUDED.object_type,
            canonical_name = EXCLUDED.canonical_name,
            aliases = EXCLUDED.aliases,
            description = EXCLUDED.description,
            visibility = EXCLUDED.visibility,
            created_by = EXCLUDED.created_by,
            policy_tags = EXCLUDED.policy_tags,
            object_version = EXCLUDED.object_version,
            policy_version = EXCLUDED.policy_version,
            projection_version = EXCLUDED.projection_version,
            source_updated_at = EXCLUDED.source_updated_at,
            projected_at = EXCLUDED.projected_at,
            search_vector = EXCLUDED.search_vector
        WHERE smartlib_projection.search_document.object_version <= EXCLUDED.object_version;

        SELECT smartlib_projection.document_json(selected_object.object_id) INTO result_document;
    ELSE
        DELETE FROM smartlib_projection.search_document
        WHERE object_id = selected_event.aggregate_id;
        result_document = jsonb_build_object(
            'operation', 'delete',
            'object_id', selected_event.aggregate_id,
            'projection_version', 'search-document-v1'
        );
    END IF;

    INSERT INTO smartlib_projection.event_receipt (projection_name, event_id)
    VALUES ('postgres_search', p_event_id)
    ON CONFLICT DO NOTHING;

    INSERT INTO smartlib_projection.projection_state (
        projection_name, last_event_id, last_occurred_at
    ) VALUES (
        'postgres_search', selected_event.event_id, selected_event.occurred_at
    )
    ON CONFLICT (projection_name) DO UPDATE SET
        last_event_id = CASE
            WHEN smartlib_projection.projection_state.last_occurred_at IS NULL
              OR EXCLUDED.last_occurred_at >= smartlib_projection.projection_state.last_occurred_at
            THEN EXCLUDED.last_event_id
            ELSE smartlib_projection.projection_state.last_event_id
        END,
        last_occurred_at = GREATEST(
            smartlib_projection.projection_state.last_occurred_at,
            EXCLUDED.last_occurred_at
        ),
        updated_at = clock_timestamp();

    RETURN jsonb_build_object(
        'operation', CASE WHEN result_document ? 'operation' THEN 'delete' ELSE 'upsert' END,
        'event_id', selected_event.event_id,
        'object_id', selected_event.aggregate_id,
        'document', CASE WHEN result_document ? 'operation' THEN NULL ELSE result_document END
    );
END
$function$;
RESET ROLE;