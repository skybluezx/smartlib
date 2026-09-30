SET ROLE smartlib_owner;
INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
VALUES ('object','organization','*','entity_decision_id',ARRAY['string'],false,
 '机构实体准入决定。新机构强制要求，历史机构不回填。','organization-admission-v1');
CREATE FUNCTION smartlib.read_organization_entity_decision(target uuid)
RETURNS SETOF smartlib.organization_entity_decision
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NOT COALESCE(smartlib.actor_has_permission(smartlib.current_actor_id(),'change.decide'),false) THEN
  RAISE EXCEPTION 'Entity decision requires review permission' USING ERRCODE='42501';
 END IF;
 RETURN QUERY SELECT * FROM smartlib.organization_entity_decision WHERE decision_id=target;
END $$;
REVOKE ALL ON FUNCTION smartlib.read_organization_entity_decision(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.read_organization_entity_decision(uuid) TO smartlib_app,smartlib_readonly;
RESET ROLE;
