import json,unittest
from pathlib import Path
from collections import Counter

ROOT=Path(__file__).resolve().parents[3]/'outputs/paper_classification_269_20260909'
@unittest.skipUnless(
 (ROOT/'assignments.json').exists(),
 '历史269篇论文分类批次未提供；保留原批次对账测试，不以替代数据冒充',
)
class PaperClassificationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=json.loads((ROOT/'assignments.json').read_text());cls.rows=cls.p['rows']
 def test_269_unique_papers_and_one_primary(self):
  self.assertEqual(len(self.p['papers']),269)
  count=Counter(r['publication_id'] for r in self.rows if r['attributes']['scheme']=='NSFC_APPLICATION_CODE' and r['attributes']['classification_role']=='primary')
  self.assertEqual(len(count),269);self.assertEqual(set(count.values()),{1})
 def test_every_paper_has_mesh(self):
  self.assertEqual(len({r['publication_id'] for r in self.rows if r['attributes']['scheme']=='MESH'}),269)
 def test_no_fabricated_external_indexing(self):
  for r in self.rows:
   a=r['attributes']
   if a['scheme']=='MESH' and a['source_kind']=='external_indexing':
    self.assertIn('pubmed.ncbi.nlm.nih.gov',a['external_record_url']);self.assertIn('archive_source_path',r)
   if a['scheme']=='NSFC_APPLICATION_CODE':self.assertEqual(a['source_kind'],'algorithmic_inference')
 def test_pending_and_unique_and_source_bound(self):
  self.assertEqual(len({r['id'] for r in self.rows}),len(self.rows))
  for r in self.rows:
   self.assertEqual(r['review_state'],'pending');self.assertEqual(len(r['source_checksum']),64)
   self.assertTrue(r['attributes']['evidence_excerpt']);self.assertTrue(r['source_uri'].startswith('s3://'))
 def test_no_metaphorical_mesh_inference(self):
  bad={'Clothing','Drive','Negotiating','Economics','Social Control, Formal','Lipoylation'}
  for r in self.rows:
   if r['attributes']['scheme']=='MESH' and r['attributes']['source_kind']=='algorithmic_inference':self.assertNotIn(r['name'],bad)
 def test_no_unrelated_entity_relations(self):
  self.assertEqual({r['predicate'] for r in self.rows},{'publication.has_research_topic','publication.classified_as_discipline'})

if __name__=='__main__':unittest.main()
