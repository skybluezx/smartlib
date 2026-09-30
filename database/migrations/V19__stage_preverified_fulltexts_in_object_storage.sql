SET ROLE smartlib_owner;

ALTER TABLE smartlib.publication_fulltext_preverification
    ADD COLUMN storage_state text NOT NULL DEFAULT 'not_stored'
        CHECK (storage_state IN ('not_stored', 'stored', 'failed')),
    ADD COLUMN storage_uri text,
    ADD COLUMN storage_object_key text,
    ADD COLUMN storage_version_id text,
    ADD COLUMN extracted_text_uri text,
    ADD COLUMN stored_at timestamptz,
    ADD COLUMN storage_error text,
    ADD CONSTRAINT publication_fulltext_preverification_storage_consistency CHECK (
        (storage_state = 'stored'
            AND storage_uri IS NOT NULL
            AND storage_object_key IS NOT NULL
            AND extracted_text_uri IS NOT NULL
            AND stored_at IS NOT NULL)
        OR
        (storage_state <> 'stored')
    );

CREATE INDEX publication_fulltext_preverification_storage_state_idx
    ON smartlib.publication_fulltext_preverification (storage_state, evaluated_at DESC);

COMMENT ON COLUMN smartlib.publication_fulltext_preverification.storage_uri IS
    'S3 URI of a content-addressed PDF staged before canonical publication approval';
COMMENT ON COLUMN smartlib.publication_fulltext_preverification.extracted_text_uri IS
    'S3 URI of the UTF-8 text derivative staged with the PDF';
COMMENT ON COLUMN smartlib.publication_fulltext_preverification.storage_state IS
    'Object-storage state independent of publication identity approval';

RESET ROLE;
