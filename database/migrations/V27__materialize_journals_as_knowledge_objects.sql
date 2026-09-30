SET ROLE smartlib_owner;

ALTER TABLE smartlib.knowledge_object
    DROP CONSTRAINT knowledge_object_object_type_check;

ALTER TABLE smartlib.knowledge_object
    ADD CONSTRAINT knowledge_object_object_type_check CHECK (
        object_type IN (
            'person', 'organization', 'department', 'discipline', 'funding_program',
            'project', 'publication', 'journal', 'dataset', 'patent', 'resource',
            'event', 'concept', 'requirement'
        )
    );

ALTER TABLE smartlib.journal_identity
    ADD COLUMN IF NOT EXISTS knowledge_object_id uuid UNIQUE
        REFERENCES smartlib.knowledge_object(object_id);

CREATE UNIQUE INDEX IF NOT EXISTS publication_one_approved_journal_idx
    ON smartlib.relation_assertion (subject_id)
    WHERE predicate = 'publication.published_in'
      AND review_state = 'approved'
      AND system_to = 'infinity'::timestamptz;

COMMENT ON COLUMN smartlib.journal_identity.knowledge_object_id IS
    'Canonical knowledge object used by search, catalog and graph projections';
COMMENT ON INDEX smartlib.publication_one_approved_journal_idx IS
    'A current publication has at most one approved publishing journal';

-- Build missing identities only from governed publication metadata. Identifier-rich
-- identities already loaded by the journal metric pipeline are preferred below.
INSERT INTO smartlib.journal_identity
    (canonical_title, normalized_title, created_by)
SELECT DISTINCT ON (lower(btrim(metadata.journal_name)))
       btrim(metadata.journal_name), lower(btrim(metadata.journal_name)),
       '00000000-0000-4000-8000-000000000001'::uuid
  FROM smartlib.publication_metadata metadata
 WHERE metadata.journal_name IS NOT NULL
   AND length(btrim(metadata.journal_name)) > 0
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.journal_identity identity
        WHERE regexp_replace(regexp_replace(lower(btrim(identity.normalized_title)),
                  '^the[[:space:]]+', ''), '[^a-z0-9]+', '', 'g') =
              regexp_replace(regexp_replace(lower(btrim(metadata.journal_name)),
                  '^the[[:space:]]+', ''), '[^a-z0-9]+', '', 'g')
           OR (metadata.issn IS NOT NULL
               AND metadata.issn IN (identity.issn,identity.eissn))
           OR (metadata.eissn IS NOT NULL
               AND metadata.eissn IN (identity.issn,identity.eissn))
   )
 ORDER BY lower(btrim(metadata.journal_name)),metadata.publication_id;

DROP TABLE IF EXISTS smartlib._selected_publication_journal;
CREATE TABLE smartlib._selected_publication_journal AS
SELECT metadata.publication_id,metadata.publication_year,metadata.journal_name,
       selected.journal_id,selected.canonical_title,selected.issn,selected.eissn
  FROM smartlib.publication_metadata metadata
  JOIN LATERAL (
      SELECT identity.*
        FROM smartlib.journal_identity identity
       WHERE regexp_replace(regexp_replace(lower(btrim(identity.normalized_title)),
                 '^the[[:space:]]+', ''), '[^a-z0-9]+', '', 'g') =
             regexp_replace(regexp_replace(lower(btrim(metadata.journal_name)),
                 '^the[[:space:]]+', ''), '[^a-z0-9]+', '', 'g')
          OR (metadata.issn IS NOT NULL
              AND metadata.issn IN (identity.issn,identity.eissn))
          OR (metadata.eissn IS NOT NULL
              AND metadata.eissn IN (identity.issn,identity.eissn))
       ORDER BY CASE
          WHEN metadata.issn IS NOT NULL
           AND metadata.issn IN (identity.issn,identity.eissn) THEN 0
          WHEN metadata.eissn IS NOT NULL
           AND metadata.eissn IN (identity.issn,identity.eissn) THEN 1
          ELSE 2 END,
          (SELECT count(*) FROM smartlib.journal_metric_record record
            WHERE record.journal_id=identity.journal_id) DESC,
          identity.journal_id
       LIMIT 1
  ) selected ON true
 WHERE metadata.journal_name IS NOT NULL
   AND length(btrim(metadata.journal_name)) > 0;

INSERT INTO smartlib.knowledge_object
    (object_id,object_type,canonical_name,description,visibility,quality_state,
     review_state,attributes,created_by)
SELECT DISTINCT journal_id,'journal',canonical_title,
       '论文发表期刊；年度影响因子与分区通过独立版本化指标记录关联。',
       'restricted','validated','approved',
       jsonb_build_object(
          'record_kind','journal','journal_identity_id',journal_id::text,
          'issn',issn,'eissn',eissn,'source','publication_metadata'
       ),'00000000-0000-4000-8000-000000000001'::uuid
  FROM smartlib._selected_publication_journal
ON CONFLICT (object_id) DO NOTHING;

UPDATE smartlib.journal_identity identity
   SET knowledge_object_id=identity.journal_id
 WHERE identity.journal_id IN (SELECT journal_id FROM smartlib._selected_publication_journal)
   AND identity.knowledge_object_id IS NULL;

INSERT INTO smartlib.relation_assertion
    (subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,
     review_state,model_version,attributes,created_by)
SELECT publication_id,'publication.published_in',journal_id,'business_fact',1,
       'restricted',ARRAY['publication-metadata'],'approved',
       'publication-journal-materialization-v1',
       jsonb_build_object(
          'relation_label','发表于','publication_year',publication_year,
          'journal_name_raw',journal_name,'match_basis','governed_journal_identity'
       ),'00000000-0000-4000-8000-000000000001'::uuid
  FROM smartlib._selected_publication_journal
ON CONFLICT (subject_id) WHERE predicate='publication.published_in'
  AND review_state='approved' AND system_to='infinity'::timestamptz
DO UPDATE SET object_id=excluded.object_id,attributes=excluded.attributes,
              version=smartlib.relation_assertion.version+1
WHERE smartlib.relation_assertion.object_id IS DISTINCT FROM excluded.object_id
   OR smartlib.relation_assertion.attributes IS DISTINCT FROM excluded.attributes;

DROP TABLE IF EXISTS smartlib._orphan_publication_journal;
CREATE TABLE smartlib._orphan_publication_journal AS
SELECT object.object_id,(object.attributes->>'journal_identity_id')::uuid AS journal_id
  FROM smartlib.knowledge_object object
 WHERE object.object_type='journal'
   AND object.attributes->>'source'='publication_metadata'
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.relation_assertion relation
        WHERE relation.object_id=object.object_id
          AND relation.predicate='publication.published_in'
          AND relation.review_state='approved'
   )
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.journal_metric_record record
        WHERE record.journal_id=(object.attributes->>'journal_identity_id')::uuid
   );

UPDATE smartlib.journal_identity identity SET knowledge_object_id=NULL
 WHERE identity.journal_id IN (SELECT journal_id FROM smartlib._orphan_publication_journal);
DELETE FROM smartlib.knowledge_object object
 USING smartlib._orphan_publication_journal orphan
 WHERE object.object_id=orphan.object_id;
DELETE FROM smartlib.journal_identity identity
 USING smartlib._orphan_publication_journal orphan
 WHERE identity.journal_id=orphan.journal_id;
DROP TABLE smartlib._orphan_publication_journal;

INSERT INTO smartlib.outbox_event
    (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT 'knowledge_object',object.object_id,'knowledge.object.updated',object.version,
       jsonb_build_object('id',object.object_id::text,'version',object.version),
       'publication-journal-materialization-v1'
  FROM smartlib.knowledge_object object
 WHERE object.object_type='journal'
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.outbox_event event
        WHERE event.aggregate_type='knowledge_object' AND event.aggregate_id=object.object_id
          AND event.trace_id='publication-journal-materialization-v1'
          AND event.event_version=object.version
   );

INSERT INTO smartlib.outbox_event
    (aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
SELECT 'relation_assertion',relation.relation_id,'knowledge.relation.updated',relation.version,
       jsonb_build_object('id',relation.relation_id::text,'version',relation.version),
       'publication-journal-materialization-v1'
  FROM smartlib.relation_assertion relation
 WHERE relation.predicate='publication.published_in'
   AND relation.review_state='approved'
   AND NOT EXISTS (
       SELECT 1 FROM smartlib.outbox_event event
        WHERE event.aggregate_type='relation_assertion'
          AND event.aggregate_id=relation.relation_id
          AND event.trace_id='publication-journal-materialization-v1'
          AND event.event_version=relation.version
   );

DROP TABLE smartlib._selected_publication_journal;

RESET ROLE;
