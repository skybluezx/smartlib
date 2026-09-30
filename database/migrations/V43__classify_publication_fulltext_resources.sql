SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

ALTER TABLE smartlib.publication_fulltext_resource
    ADD COLUMN resource_role text NOT NULL DEFAULT 'article'
        CHECK (resource_role IN ('article', 'correction'));

CREATE INDEX publication_fulltext_resource_role_idx
    ON smartlib.publication_fulltext_resource (publication_id, resource_role, created_at DESC);

COMMENT ON COLUMN smartlib.publication_fulltext_resource.resource_role IS
    'Role of the PDF within the publication record: article for the main paper, correction for a later correction or erratum.';

RESET ROLE;
