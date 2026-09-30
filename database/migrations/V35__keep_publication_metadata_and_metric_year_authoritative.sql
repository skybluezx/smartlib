SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Keep old interpretations and their decision history; exclude stale matches.
CREATE TRIGGER metric_match_history AFTER INSERT OR UPDATE OR DELETE
ON smartlib.publication_journal_metric_match FOR EACH ROW
EXECUTE FUNCTION smartlib.capture_entity_revision('match_id');

CREATE FUNCTION smartlib.enforce_metric_match_year() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
    IF NEW.match_state='matched' AND NEW.year_policy='publication_year' AND NOT EXISTS (
        SELECT 1 FROM smartlib.publication_metadata m
        JOIN smartlib.journal_metric_record r ON r.record_id=NEW.record_id
        JOIN smartlib.journal_metric_release v ON v.release_id=r.release_id
        WHERE m.publication_id=NEW.publication_id AND m.publication_year=v.metric_year
          AND v.release_state='published' AND v.authority_status='verified'
    ) THEN
        RAISE EXCEPTION 'matched annual metric must use the current publication year and verified published release'
          USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER metric_match_year_guard BEFORE INSERT OR UPDATE
ON smartlib.publication_journal_metric_match FOR EACH ROW EXECUTE FUNCTION smartlib.enforce_metric_match_year();

CREATE FUNCTION smartlib.sync_publication_metadata_authority() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
    UPDATE smartlib.knowledge_object SET canonical_name=NEW.title
      WHERE object_id=NEW.publication_id AND canonical_name IS DISTINCT FROM NEW.title;
    UPDATE smartlib.publication_journal_metric_match x
      SET match_state='review_required',decision_reason=concat_ws('; ',x.decision_reason,
          'Publication metadata changed: annual metric requires revalidation')
      FROM smartlib.journal_metric_record r,smartlib.journal_metric_release v
      WHERE x.publication_id=NEW.publication_id AND x.record_id=r.record_id
        AND r.release_id=v.release_id AND x.match_state='matched'
        AND x.year_policy='publication_year' AND NEW.publication_year IS DISTINCT FROM v.metric_year;
    RETURN NEW;
END $$;
CREATE TRIGGER publication_metadata_authority_sync AFTER INSERT OR UPDATE ON smartlib.publication_metadata
FOR EACH ROW EXECUTE FUNCTION smartlib.sync_publication_metadata_authority();

CREATE FUNCTION smartlib.guard_publication_object_title() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
    IF NEW.object_type='publication' AND EXISTS(SELECT 1 FROM smartlib.publication_metadata
        WHERE publication_id=NEW.object_id AND title IS DISTINCT FROM NEW.canonical_name) THEN
        RAISE EXCEPTION 'update publication title through publication_metadata authority' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER publication_object_title_guard BEFORE UPDATE OF canonical_name ON smartlib.knowledge_object
FOR EACH ROW EXECUTE FUNCTION smartlib.guard_publication_object_title();

UPDATE smartlib.knowledge_object o SET canonical_name=m.title
FROM smartlib.publication_metadata m WHERE m.publication_id=o.object_id AND o.canonical_name IS DISTINCT FROM m.title;
UPDATE smartlib.publication_journal_metric_match x
SET match_state='review_required',decision_reason=concat_ws('; ',x.decision_reason,
    'Annual metric audit: mismatched publication year; excluded pending revalidation')
FROM smartlib.publication_metadata m,smartlib.journal_metric_record r,smartlib.journal_metric_release v
WHERE x.publication_id=m.publication_id AND x.record_id=r.record_id AND r.release_id=v.release_id
    AND x.match_state='matched' AND x.year_policy='publication_year'
    AND (m.publication_year IS DISTINCT FROM v.metric_year OR v.release_state<>'published' OR v.authority_status<>'verified');

REVOKE ALL ON FUNCTION smartlib.enforce_metric_match_year(),smartlib.sync_publication_metadata_authority(),
    smartlib.guard_publication_object_title() FROM PUBLIC;
RESET ROLE;
