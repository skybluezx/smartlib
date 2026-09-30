SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

ALTER TABLE smartlib.publication_authorship
    ADD COLUMN affiliation_organization_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[];

CREATE INDEX publication_authorship_organizations_idx
    ON smartlib.publication_authorship USING gin (affiliation_organization_ids);

UPDATE smartlib.publication_authorship authorship
   SET affiliation_organization_ids=COALESCE((
       SELECT array_agg(DISTINCT organization.object_id ORDER BY organization.object_id)
         FROM jsonb_array_elements(authorship.affiliation_evidence->'assignments') assignment
         JOIN smartlib.knowledge_object organization
           ON organization.object_type='organization'
          AND lower(organization.canonical_name)=lower(assignment->>'organization_name')
   ),ARRAY[]::uuid[])
 WHERE authorship.affiliation_evidence ? 'assignments';

COMMENT ON COLUMN smartlib.publication_authorship.affiliation_organization_ids IS
    'Normalized organization objects assigned to this author in this publication; raw affiliation text remains in affiliation_raw and affiliation_evidence.';

RESET ROLE;
