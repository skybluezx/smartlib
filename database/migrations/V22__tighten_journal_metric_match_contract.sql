SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

ALTER TABLE smartlib.publication_journal_metric_match
    DROP CONSTRAINT publication_journal_metric_match_check;
ALTER TABLE smartlib.publication_journal_metric_match
    ADD CONSTRAINT publication_journal_metric_match_decision_check
    CHECK (
        match_state NOT IN ('matched', 'rejected')
        OR (
            decided_by IS NOT NULL
            AND decided_at IS NOT NULL
            AND decision_reason IS NOT NULL
            AND btrim(decision_reason) <> ''
        )
    );

CREATE TRIGGER publication_journal_metric_match_publication_type
BEFORE INSERT OR UPDATE OF publication_id ON smartlib.publication_journal_metric_match
FOR EACH ROW EXECUTE FUNCTION smartlib.assert_knowledge_object_type(
    'publication_id', 'publication'
);

COMMENT ON CONSTRAINT publication_journal_metric_match_decision_check
ON smartlib.publication_journal_metric_match IS
    'Terminal match decisions require an identified reviewer, timestamp and non-empty reason';

RESET ROLE;
