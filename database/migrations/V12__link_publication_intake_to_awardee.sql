SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

ALTER TABLE smartlib.publication_import_item
    ADD COLUMN awardee_person_id uuid REFERENCES smartlib.knowledge_object(object_id);

CREATE INDEX publication_import_item_awardee_idx
    ON smartlib.publication_import_item (awardee_person_id, verification_state)
    WHERE awardee_person_id IS NOT NULL;

CREATE TRIGGER publication_import_item_awardee_type
BEFORE INSERT OR UPDATE OF awardee_person_id ON smartlib.publication_import_item
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type('awardee_person_id', 'person');

COMMENT ON COLUMN smartlib.publication_import_item.awardee_person_id IS
    'Exact source-name link to the controlled awardee person; this is not an author-identity assertion';

RESET ROLE;
