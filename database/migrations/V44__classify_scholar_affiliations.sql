SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;

-- Authority is explicitly configured for a source, never inferred from review approval.
ALTER TABLE smartlib.source_system ADD COLUMN personnel_authority boolean NOT NULL DEFAULT false;
INSERT INTO smartlib.relation_predicate_definition
 (predicate,canonical_label,description,subject_types,target_kind,object_types,schema_version)
VALUES ('person.authoritatively_affiliated_with','人事权威机构',
 '人事来源确认的机构归属；有效期来自来源记录，不从论文年份推断。',
 ARRAY['person'],'object',ARRAY['organization','department'],'affiliation-v2');

INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,attribute_key,allowed_json_types,description,schema_version)
VALUES ('relation','person.authoritatively_affiliated_with','raw_affiliation',ARRAY['string'],
 '人事来源机构原文。','affiliation-v2');

CREATE FUNCTION smartlib.validate_personnel_affiliations() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,smartlib AS $$
BEGIN
 IF EXISTS (
   SELECT 1 FROM smartlib.relation_assertion r
   WHERE r.predicate='person.authoritatively_affiliated_with'
     AND r.review_state='approved' AND r.system_to='infinity'::timestamptz
     AND (r.context_object_id IS NOT NULL OR NOT EXISTS (
       SELECT 1 FROM smartlib.relation_evidence re
       JOIN smartlib.evidence_record e USING(evidence_id)
       JOIN smartlib.source_reference ref USING(source_reference_id)
       JOIN smartlib.source_system s USING(source_system_id)
       WHERE re.relation_id=r.relation_id AND e.object_id=r.subject_id
         AND ref.object_id=r.subject_id AND e.evidence_type='business_record'
         AND e.verification_state='confirmed' AND s.personnel_authority
         AND s.authorization_state='approved'
         AND ref.system_to='infinity'::timestamptz
     ))
 ) THEN
   RAISE EXCEPTION 'Personnel affiliation requires confirmed person-specific evidence from an authorized personnel source, without publication context'
     USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER personnel_relation_guard AFTER INSERT OR UPDATE ON smartlib.relation_assertion
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.validate_personnel_affiliations();
CREATE CONSTRAINT TRIGGER personnel_evidence_link_guard AFTER INSERT OR UPDATE OR DELETE ON smartlib.relation_evidence
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.validate_personnel_affiliations();
CREATE CONSTRAINT TRIGGER personnel_evidence_guard AFTER UPDATE OR DELETE ON smartlib.evidence_record
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.validate_personnel_affiliations();
CREATE CONSTRAINT TRIGGER personnel_source_guard AFTER UPDATE OR DELETE ON smartlib.source_system
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.validate_personnel_affiliations();
CREATE CONSTRAINT TRIGGER personnel_reference_guard AFTER UPDATE OR DELETE ON smartlib.source_reference
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION smartlib.validate_personnel_affiliations();
COMMENT ON COLUMN smartlib.source_system.personnel_authority IS
 'Only explicitly authorized personnel sources can support authoritative scholar affiliations. Defaults false; no existing source is promoted.';
RESET ROLE;
