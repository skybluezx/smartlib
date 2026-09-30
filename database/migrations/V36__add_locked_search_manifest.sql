SET ROLE smartlib_owner;
CREATE FUNCTION smartlib.lock_search_authority_manifest() RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE result text;
BEGIN
    LOCK TABLE smartlib.knowledge_object IN SHARE MODE;
    SELECT md5(COALESCE(string_agg(object_id::text||':'||version::text,',' ORDER BY object_id),''))
        INTO result FROM smartlib.knowledge_object;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION smartlib.lock_search_authority_manifest() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.lock_search_authority_manifest() TO smartlib_app;
RESET ROLE;
