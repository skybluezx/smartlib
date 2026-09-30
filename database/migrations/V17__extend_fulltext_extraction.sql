SET ROLE smartlib_owner;
SET search_path = smartlib, audit, pg_catalog;

ALTER TABLE smartlib.publication_fulltext_resource
    ADD COLUMN extraction_method text,
    ADD COLUMN extraction_version text,
    ADD COLUMN extracted_text_uri text,
    ADD COLUMN page_count integer CHECK (page_count IS NULL OR page_count > 0),
    ADD COLUMN text_length bigint CHECK (text_length IS NULL OR text_length >= 0),
    ADD COLUMN ocr_page_count integer CHECK (ocr_page_count IS NULL OR ocr_page_count >= 0),
    ADD COLUMN extracted_at timestamptz,
    ADD COLUMN extraction_error text;

COMMENT ON COLUMN smartlib.publication_fulltext_resource.extracted_text_uri IS
    'S3 URI of the complete UTF-8 text derivative; PostgreSQL stores only its controlled reference.';
COMMENT ON COLUMN smartlib.publication_fulltext_resource.extracted_metadata IS
    'Versioned structural extraction result, including abstract, keywords, sections and identifier evidence.';
