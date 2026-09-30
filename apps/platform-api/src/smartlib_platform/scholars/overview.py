"""Complete, visibility-scoped scholar statistics, independent of graph limits."""

def load_overview(connection, scholar_id):
    # RLS remains active. Only current, approved/pending records and endpoints participate.
    eligible = """WITH objects AS (
      SELECT * FROM smartlib.knowledge_object
      WHERE system_to='infinity' AND smartlib.analysis_state_eligible(review_state)
    ), relations AS (
      SELECT * FROM smartlib.analysis_relation
    ), papers AS (
      SELECT DISTINCT r.object_id FROM relations r JOIN objects o ON o.object_id=r.object_id
      WHERE r.subject_id=%s AND r.predicate='person.authored' AND o.object_type='publication'
    ) """
    counts = connection.execute(eligible + """SELECT
      (SELECT count(*) FROM papers) publication,
      (SELECT count(DISTINCT r.object_id) FROM relations r JOIN objects o ON o.object_id=r.object_id
       WHERE r.subject_id=%s AND r.predicate IN ('person.leads_project','person.participates_in','person.awardee_of')
         AND o.object_type='project') project,
      (SELECT count(DISTINCT r.subject_id) FROM relations r JOIN objects o ON o.object_id=r.subject_id
       WHERE r.predicate='person.authored' AND r.object_id IN (SELECT object_id FROM papers)
         AND r.subject_id<>%s AND o.object_type='person') person,
      (SELECT count(DISTINCT r.object_id) FROM relations r
       WHERE r.subject_id IN (SELECT object_id FROM papers) AND r.predicate='publication.has_research_topic'
         AND EXISTS(SELECT 1 FROM smartlib.relation_evidence e WHERE e.relation_id=r.relation_id)) concept
    """, (scholar_id, scholar_id, scholar_id)).fetchone()
    papers = connection.execute(eligible + """SELECT DISTINCT ON (o.object_id)
      o.object_id,o.canonical_name,COALESCE(m.abstract,o.description) description,r.review_state,r.relation_id,
      m.publication_year AS year,
      COALESCE(ids.doi,o.attributes->>'doi') doi,
      COALESCE(ids.pmid,o.attributes->>'pmid') pmid,
      COALESCE(ids.pmcid,o.attributes->>'pmcid') pmcid,
      (SELECT count(*) FROM smartlib.relation_evidence e WHERE e.relation_id=r.relation_id) evidence_count
      FROM papers p JOIN objects o ON o.object_id=p.object_id
      JOIN relations r ON r.object_id=o.object_id AND r.subject_id=%s AND r.predicate='person.authored'
      LEFT JOIN smartlib.publication_metadata m ON m.publication_id=o.object_id
      LEFT JOIN LATERAL (SELECT
        max(normalized_value) FILTER (WHERE identifier_type='doi') doi,
        max(normalized_value) FILTER (WHERE identifier_type='pmid') pmid,
        max(normalized_value) FILTER (WHERE identifier_type='pmcid') pmcid
        FROM smartlib.publication_identifier WHERE publication_id=o.object_id
          AND verification_status IN ('matched','pending')) ids ON true
      ORDER BY o.object_id,CASE WHEN r.review_state='approved' THEN 0 ELSE 1 END,r.relation_id
    """, (scholar_id, scholar_id)).fetchall()
    return {'counts': dict(counts), 'papers': sorted(papers, key=lambda p: (-(p['year'] or 0), p['canonical_name'])),
            'scope': 'current_visible_approved_and_pending', 'truncated': False}
