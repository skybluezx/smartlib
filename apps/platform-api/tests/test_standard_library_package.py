"""Acceptance checks for the current source-backed release package."""
import json
import unittest
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
PACKAGE=ROOT/'outputs/standard_library_20260909/package.json'


@unittest.skipUnless(PACKAGE.exists(),'release package not staged')
class StandardPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package=json.loads(PACKAGE.read_text())
        cls.objects={r['id']:r for r in cls.package['objects']}

    def test_unique_standard_keys_and_ids(self):
        rows=self.package['objects']
        self.assertEqual(len(self.objects),len(rows))
        self.assertEqual(len({(r['attributes']['scheme'],r['attributes']['scheme_version'],
                               r['attributes']['scheme_code']) for r in rows}),len(rows))

    def test_relation_endpoints_and_version_boundaries(self):
        for edge in self.package['relations']:
            a=self.objects[edge['subject']]['attributes'];b=self.objects[edge['object']]['attributes']
            self.assertEqual((a['scheme'],a['scheme_version']),(b['scheme'],b['scheme_version']))
            self.assertNotEqual(edge['subject'],edge['object'])
            self.assertTrue(edge['predicate'].startswith('taxonomy.'))

    def test_hierarchy_is_acyclic(self):
        graph=defaultdict(list)
        for edge in self.package['relations']:
            if edge['predicate']=='taxonomy.broader':graph[edge['subject']].append(edge['object'])
        done=set();active=set()
        def visit(node):
            if node in done:return
            self.assertNotIn(node,active)
            active.add(node)
            for parent in graph[node]:visit(parent)
            active.remove(node);done.add(node)
        for node in list(graph):visit(node)

    def test_source_and_names_complete(self):
        sources={r['path'] for r in self.package['sources']}
        for row in self.objects.values():
            self.assertTrue(row['name'].strip());self.assertIn(row['source_path'],sources)
            self.assertEqual(len(row['attributes']['source_checksum']),64)

    def test_mesh_preserves_colliding_tree_positions_without_merging(self):
        rows={r['attributes']['scheme_code']:r for r in self.objects.values()
              if r['attributes']['scheme']=='MESH'}
        self.assertNotEqual(rows['D047991']['id'],rows['D048013']['id'])
        for code in ['D047991','D048013']:
            self.assertTrue(rows[code]['attributes']['standard_quality_notes'])
            self.assertEqual(rows[code]['type'],'concept')

    def test_acceptance_codes_not_application_codes(self):
        rows=[r for r in self.objects.values() if r['attributes']['code_kind']=='acceptance_code']
        self.assertEqual({r['attributes']['scheme_code'] for r in rows},{'T01','T02','T03','T04','T05'})


if __name__=='__main__':unittest.main()
