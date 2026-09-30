-- V14 created these tables before switching to smartlib_owner, so existing
-- databases may still have smartlib_bootstrap as their owner. Repair that
-- historical ownership before this migration reads the verification layers.
ALTER TABLE smartlib.publication_verification_check OWNER TO smartlib_owner;
ALTER TABLE smartlib.publication_verification_layer OWNER TO smartlib_owner;

SET ROLE smartlib_owner;
SET search_path = smartlib, pg_catalog;

ALTER TABLE smartlib.publication_import_item
    DROP CONSTRAINT publication_import_item_verification_state_check;
ALTER TABLE smartlib.publication_import_item
    ADD CONSTRAINT publication_import_item_verification_state_check
    CHECK (verification_state IN (
        'pending', 'normalized', 'auto_verified', 'manual_review',
        'reverification_required', 'verification_conflict',
        'human_verified', 'corrected', 'rejected', 'superseded'
    ));

UPDATE smartlib.publication_import_item AS item
   SET verification_state = CASE
       WHEN EXISTS (
           SELECT 1 FROM smartlib.publication_verification_layer AS layer
            WHERE layer.import_item_id=item.import_item_id AND layer.is_blocking
              AND layer.layer_status='conflict'
       ) OR EXISTS (
           SELECT 1 FROM smartlib.publication_fulltext_preverification AS pre
            WHERE pre.import_item_id=item.import_item_id
              AND pre.preverification_status='conflict'
       ) THEN 'verification_conflict'
       WHEN NOT EXISTS (
           SELECT 1 FROM smartlib.publication_verification_layer AS layer
            WHERE layer.import_item_id=item.import_item_id AND layer.is_blocking
       ) OR EXISTS (
           SELECT 1 FROM smartlib.publication_verification_layer AS layer
            WHERE layer.import_item_id=item.import_item_id AND layer.is_blocking
              AND layer.layer_status IN ('pending','incomplete')
       ) OR EXISTS (
           SELECT 1 FROM smartlib.publication_metadata AS metadata
            WHERE metadata.publication_id=item.matched_publication_id
              AND metadata.identity_state='review_required'
       ) OR EXISTS (
           SELECT 1 FROM smartlib.publication_fulltext_preverification AS pre
            WHERE pre.import_item_id=item.import_item_id
              AND pre.preverification_status='review_required'
       ) THEN 'reverification_required'
       WHEN EXISTS (
           SELECT 1
             FROM smartlib.publication_change_candidate AS candidate
             JOIN smartlib.publication_supplement AS supplement
               ON supplement.supplement_id=candidate.supplement_id
            WHERE supplement.publication_id=item.matched_publication_id
              AND candidate.risk_level='critical' AND candidate.status='accepted'
       ) THEN 'corrected'
       ELSE item.verification_state
   END
 WHERE item.verification_state IN ('auto_verified','human_verified','corrected');

INSERT INTO smartlib.access_permission (code, name, risk_level)
VALUES ('publication_import.submit', '提交单篇或批量论文导入', 'normal')
ON CONFLICT (code) DO NOTHING;

INSERT INTO smartlib.access_role_permission (role_id, permission_id)
SELECT role.role_id, permission.permission_id
  FROM smartlib.access_role role
  JOIN smartlib.access_permission permission ON permission.code='publication_import.submit'
 WHERE role.code='knowledge_admin'
ON CONFLICT DO NOTHING;

COMMENT ON COLUMN smartlib.publication_import_item.verification_state IS
    'Current effective verification state; later blocking evidence reopens or conflicts a prior decision';

RESET ROLE;
