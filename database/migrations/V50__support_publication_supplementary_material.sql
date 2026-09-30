SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

ALTER TABLE smartlib.publication_fulltext_resource
    DROP CONSTRAINT publication_fulltext_resource_resource_role_check;
ALTER TABLE smartlib.publication_fulltext_resource
    ADD CONSTRAINT publication_fulltext_resource_resource_role_check
    CHECK (resource_role IN ('article', 'correction', 'supplementary'));

COMMENT ON COLUMN smartlib.publication_fulltext_resource.resource_role IS
    'PDF role: article for the main paper, correction for errata, supplementary for supporting information.';
RESET ROLE;
