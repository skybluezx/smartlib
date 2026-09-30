SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Publication for internal analysis is not a claim of source verification.
ALTER TABLE smartlib.journal_metric_release DROP CONSTRAINT journal_metric_release_check1;
ALTER TABLE smartlib.journal_metric_release ADD CONSTRAINT journal_metric_publication_review_check CHECK ((
 release_state <> 'published' OR
 (authority_status='verified' AND verified_by IS NOT NULL AND verified_at IS NOT NULL) OR
 (metric_system='jcr' AND authority_status='unverified'
  AND metadata->>'publication_mode'='internal_provisional'
  AND metadata->>'publication_authorized_by' IS NOT NULL
  AND metadata->>'publication_authorized_at' IS NOT NULL)
) IS TRUE);

CREATE FUNCTION smartlib.journal_metric_analysis_eligible(p_release_id uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
 SELECT coalesce((SELECT r.release_state='published' AND
   (r.authority_status='verified' OR
    (r.metric_system='jcr' AND r.authority_status='unverified'
     AND r.metadata->>'publication_mode'='internal_provisional'
     AND smartlib.analysis_state_eligible('pending')))
 FROM smartlib.journal_metric_release r WHERE r.release_id=p_release_id),false)
$$;
REVOKE ALL ON FUNCTION smartlib.journal_metric_analysis_eligible(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.journal_metric_analysis_eligible(uuid) TO smartlib_app,smartlib_readonly,smartlib_projection;

CREATE FUNCTION smartlib.publish_provisional_jcr_release(p_release_id uuid,p_reason text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE r smartlib.journal_metric_release; actual integer;
BEGIN
 IF NOT smartlib.actor_has_permission(smartlib.current_actor_id(),'journal_metric.publish') THEN
  RAISE EXCEPTION 'journal metric publish permission required';
 END IF;
 IF NOT smartlib.analysis_state_eligible('pending') THEN RAISE EXCEPTION 'deferred review policy disabled'; END IF;
 IF p_reason IS NULL OR btrim(p_reason)='' THEN RAISE EXCEPTION 'explicit internal publication reason required'; END IF;
 SELECT * INTO r FROM smartlib.journal_metric_release WHERE release_id=p_release_id FOR UPDATE;
 IF NOT FOUND OR r.metric_system<>'jcr' OR r.authority_status='rejected'
   OR r.release_state NOT IN ('staged','validated','published') THEN
  RAISE EXCEPTION 'not an eligible JCR release';
 END IF;
 IF r.release_state='published' THEN RETURN; END IF;
 -- Existing legal/source statuses remain unchanged. No redistribution rights are granted.
 IF EXISTS (
  SELECT 1 FROM smartlib.data_asset_version v
  JOIN smartlib.data_asset a USING(data_asset_id)
  JOIN smartlib.source_system s USING(source_system_id)
  LEFT JOIN smartlib.license_grant l USING(data_asset_id)
  WHERE v.data_asset_version_id=r.data_asset_version_id AND
   (s.authorization_state NOT IN ('pending','approved') OR
    l.authorization_state NOT IN ('pending','approved') OR
    l.valid_to<=clock_timestamp() OR l.valid_from>clock_timestamp())
 ) THEN RAISE EXCEPTION 'source or license disallows internal publication'; END IF;
 SELECT count(*) INTO actual FROM smartlib.journal_metric_record WHERE release_id=p_release_id;
 IF actual=0 OR actual<>r.expected_record_count THEN RAISE EXCEPTION 'journal metric row count mismatch'; END IF;
 UPDATE smartlib.journal_metric_release SET release_state='published',
 metadata=metadata || jsonb_build_object('publication_mode','internal_provisional',
  'publication_authorized_by',smartlib.current_actor_id(),
  'publication_authorized_at',clock_timestamp(),'publication_reason',p_reason,
  'post_publication_review_required',true,'external_redistribution_authorized',false)
 WHERE release_id=p_release_id;
END $$;
REVOKE ALL ON FUNCTION smartlib.publish_provisional_jcr_release(uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.publish_provisional_jcr_release(uuid,text) TO smartlib_app;

CREATE OR REPLACE FUNCTION smartlib.enforce_metric_match_year() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NEW.match_state='matched' AND NEW.year_policy='publication_year' AND NOT EXISTS (
  SELECT 1 FROM smartlib.publication_metadata m
  JOIN smartlib.journal_metric_record r ON r.record_id=NEW.record_id
  JOIN smartlib.journal_metric_release v ON v.release_id=r.release_id
  WHERE m.publication_id=NEW.publication_id AND m.publication_year=v.metric_year
    AND smartlib.journal_metric_analysis_eligible(v.release_id)
 ) THEN RAISE EXCEPTION 'matched annual metric requires current publication year and eligible published release' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
COMMENT ON FUNCTION smartlib.journal_metric_analysis_eligible(uuid) IS
 'Shared journal metric admission for matching, publication details and all analysis modules; provisional JCR follows shared pending policy.';
RESET ROLE;
