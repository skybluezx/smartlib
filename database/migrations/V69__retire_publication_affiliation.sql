-- Author attribution must be resolved from evidence before retiring old facts.
SET ROLE smartlib_owner;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM smartlib.relation_assertion
        WHERE predicate = 'publication.affiliated_with'
          AND system_to = 'infinity'::timestamptz
          AND review_state NOT IN ('superseded', 'rejected')
    ) THEN
        RAISE EXCEPTION 'Convert publication affiliations to evidence-backed person.affiliated_with before migration';
    END IF;
END;
$$;
UPDATE smartlib.relation_predicate_definition
SET lifecycle_state = 'retired',
    replacement_predicate = 'person.affiliated_with',
    updated_at = clock_timestamp()
WHERE predicate = 'publication.affiliated_with';
RESET ROLE;
