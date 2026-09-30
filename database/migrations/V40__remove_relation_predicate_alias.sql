SET ROLE smartlib_owner;
SET search_path=smartlib,pg_catalog;
-- No implicit reinterpretation of ambiguous historical funding facts.
-- Retained history lives in the append-only audit/revision tables and old migrations.
LOCK TABLE smartlib.relation_assertion IN SHARE ROW EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM smartlib.relation_assertion
           WHERE predicate IN ('funding_organization.part_of','publication.funded_by')) THEN
  RAISE EXCEPTION 'Legacy funding relations require explicit semantic reconciliation before V40';
 END IF;
END $$;
DROP TABLE smartlib.relation_predicate_alias;
DELETE FROM smartlib.relation_predicate_definition
 WHERE predicate IN ('funding_organization.part_of','publication.funded_by');
-- Explicit contracts for reviewed funding supplements, separate from NSFC awards.
INSERT INTO smartlib.attribute_definition
 (entity_kind,entity_type,record_kind,attribute_key,allowed_json_types,required,description,schema_version)
SELECT 'object',t,'supplement_funding',k,types,required,description,'funding-supplement-v1'
FROM (VALUES ('project'),('organization')) AS targets(t)
CROSS JOIN (VALUES
 ('record_kind',ARRAY['string'],true,'Funding supplement object subtype.'),
 ('source',ARRAY['string'],true,'Source workflow.'),
 ('funder_name',ARRAY['string'],true,'Funder name from reviewed evidence.'),
 ('grant_id',ARRAY['string','null'],false,'Grant identifier when present.'),
 ('country',ARRAY['string','null'],false,'Country from source.'),
 ('metadata',ARRAY['object'],false,'Additional source metadata.')
) AS fields(k,types,required,description);
RESET ROLE;
