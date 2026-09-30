SET ROLE smartlib_owner;
-- Prospective gate only: existing organizations and evidence are not rewritten.
CREATE TABLE smartlib.organization_entity_decision (
 decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 canonical_name text NOT NULL CHECK (length(btrim(canonical_name)) > 0),
 evidence_id uuid NOT NULL REFERENCES smartlib.evidence_record(evidence_id),
 rationale text NOT NULL CHECK (length(btrim(rationale)) > 0),
 reviewed_by uuid NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON smartlib.organization_entity_decision FROM PUBLIC,smartlib_app,smartlib_readonly;
CREATE TRIGGER organization_entity_decision_append_only BEFORE UPDATE OR DELETE
 ON smartlib.organization_entity_decision FOR EACH ROW
 EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
CREATE TRIGGER organization_entity_decision_no_truncate BEFORE TRUNCATE
 ON smartlib.organization_entity_decision FOR EACH STATEMENT
 EXECUTE FUNCTION smartlib.enforce_publication_revision_history();
CREATE TRIGGER organization_entity_decision_history AFTER INSERT
 ON smartlib.organization_entity_decision FOR EACH ROW
 EXECUTE FUNCTION smartlib.capture_entity_revision('decision_id');

CREATE FUNCTION smartlib.confirm_organization_entity(name text, evidence uuid, reason text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
DECLARE actor uuid := smartlib.current_actor_id(); decision uuid;
BEGIN
 IF actor IS NULL OR NOT COALESCE(smartlib.actor_has_permission(actor,'change.decide'),false) THEN
  RAISE EXCEPTION 'Organization entity confirmation requires review permission' USING ERRCODE='42501';
 END IF;
 -- A PDF affiliation or a successful string extraction is NOT an identity decision.
 IF NOT EXISTS(SELECT 1 FROM smartlib.evidence_record e WHERE e.evidence_id=evidence
   AND e.evidence_kind='organization_identity' AND e.verification_state='confirmed'
   AND (e.created_by=actor OR e.visibility='public')) THEN
  RAISE EXCEPTION 'Confirmed organization_identity evidence is required' USING ERRCODE='23514';
 END IF;
 INSERT INTO smartlib.organization_entity_decision(canonical_name,evidence_id,rationale,reviewed_by)
 VALUES(btrim(name),evidence,reason,actor) RETURNING decision_id INTO decision;
 RETURN decision;
END $$;
REVOKE ALL ON FUNCTION smartlib.confirm_organization_entity(text,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION smartlib.confirm_organization_entity(text,uuid,text) TO smartlib_app;

CREATE FUNCTION smartlib.enforce_organization_entity_admission() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF NEW.object_type <> 'organization' THEN RETURN NEW; END IF;
 IF TG_OP='UPDATE' THEN
  -- Legacy content edits remain possible; changing a non-organization into one is gated.
  IF OLD.object_type='organization' THEN
   IF (NEW.attributes->>'entity_decision_id') IS DISTINCT FROM (OLD.attributes->>'entity_decision_id') THEN
    RAISE EXCEPTION 'Organization admission decision is immutable' USING ERRCODE='23514';
   END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM smartlib.organization_entity_decision d
   JOIN smartlib.evidence_record e ON e.evidence_id=d.evidence_id
   WHERE d.decision_id::text=NEW.attributes->>'entity_decision_id'
     AND d.canonical_name=NEW.canonical_name
     AND e.evidence_kind='organization_identity' AND e.verification_state='confirmed') THEN
  RAISE EXCEPTION 'Organization requires an explicit entity decision; retain unmatched affiliation as evidence'
   USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER organization_entity_admission BEFORE INSERT OR UPDATE
 ON smartlib.knowledge_object FOR EACH ROW
 EXECUTE FUNCTION smartlib.enforce_organization_entity_admission();
CREATE UNIQUE INDEX organization_entity_decision_single_use ON smartlib.knowledge_object
 ((attributes->>'entity_decision_id')) WHERE object_type='organization' AND attributes ? 'entity_decision_id';
RESET ROLE;
