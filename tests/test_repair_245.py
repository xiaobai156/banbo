import unittest
from dataclasses import replace

from banbo.application.single_period import build_site_spec
from banbo.cli import _load_runtime
from banbo.domain import Document, DocumentSource, ValidatedResult
from banbo.parsers import build_default_registry
from banbo.domain.validation import validate_evidence


def repair_spec(spec):
    if spec.site_id == 'hw-0003':
        return replace(spec, parser_version='2', parser_id='hw-0003:regex_line:v2',
                       topic_id_pattern=r'/topic/(?P<topic_id>\d+)\.html',
                       options={**spec.options, 'allowed_external_hosts':
                                [f'xia0{i}.cosds.aohjifv.com' for i in range(1, 7)]})
    return replace(spec, strategy='article_sibling_segment', parser_version='4',
                   parser_id='hw-0093:article_sibling_segment:v4', after_documents=0,
                   options={**spec.options, 'end_markers': ['站长宣言'],
                            'end_marker_keep_prefix': True})


class Repair245Tests(unittest.TestCase):
    def setUp(self):
        sites, specs, _ = _load_runtime()
        self.spec = repair_spec(next(s for s in specs if s.site_id == 'hw-0093'))
        self.site = build_site_spec(sites.get('hw-0093'), self.spec,
                                    expected_record_id='459941')
        self.parts = ['勇往直前【绝杀半波】提高速度',
                      '242期绝杀半波红双', '243期绝杀半波红单',
                      '244期绝杀半波蓝单',
                      '245期绝杀半波绿单站长宣言245期绝杀半波红双']

    def documents(self, parts):
        return tuple(Document(str(i), DocumentSource.SCRIPT,
                              f'https://cdn.example/article.js#decoded-{i+1}', i, p,
                              linked_record_id='459941',
                              record_relation='declared_entry_script')
                     for i, p in enumerate(parts))

    def outcome(self, parts=None, issue=245, docs=None, spec=None):
        registry = build_default_registry()
        registry.bind(spec or self.spec)
        evidence = registry.parse(self.site, docs or self.documents(parts or self.parts), issue)
        return validate_evidence(self.site, issue, evidence)

    def test_prefix_row_and_outside_decoy(self):
        result = self.outcome()
        self.assertIsInstance(result, ValidatedResult)
        self.assertEqual(result.value, '绿单')
        self.assertEqual(result.evidence.boundary_issues, (243, 244, 245))

    def test_fragment_count_does_not_limit_article(self):
        parts = [self.parts[0]] + ['<p>历史排版</p>'] * 15 + self.parts[1:]
        self.assertIsInstance(self.outcome(parts), ValidatedResult)

    def test_adjacent_and_missing(self):
        self.assertEqual(self.outcome(issue=244).value, '蓝单')
        for issue in (242, 246, 9999):
            self.assertNotIsInstance(self.outcome(issue=issue), ValidatedResult)

    def test_no_end_no_anchor_wrong_field(self):
        for old, new in [('站长宣言', '结束'), ('勇往直前', '其他作者'),
                         ('绝杀半波', '必杀二尾')]:
            self.assertNotIsInstance(self.outcome([p.replace(old, new) for p in self.parts]),
                                     ValidatedResult)

    def test_same_period_conflict(self):
        parts = self.parts[:-1] + ['245期绝杀半波红双', self.parts[-1]]
        self.assertNotIsInstance(self.outcome(parts), ValidatedResult)

    def test_wrong_record_and_cross_document_anchor(self):
        docs = self.documents(self.parts)
        for field in ({'linked_record_id': '000'},
                      {'source_url': 'https://other.example/data.js#decoded-1'}):
            changed = (docs[0],) + tuple(replace(d, **field) for d in docs[1:])
            self.assertNotIsInstance(self.outcome(docs=changed), ValidatedResult)

    def test_default_excludes_end_document(self):
        options = {**self.spec.options, 'end_marker_keep_prefix': False}
        self.assertNotIsInstance(self.outcome(spec=replace(self.spec, options=options)),
                                 ValidatedResult)

    def test_two_authoritative_articles_conflict(self):
        docs = self.documents(self.parts)
        other = tuple(replace(d, document_id='other-' + d.document_id,
                              source_url=d.source_url.replace('article.js', 'other.js'),
                              order=d.order + 10,
                              content=d.content.replace('绿单', '蓝双')) for d in docs)
        self.assertNotIsInstance(self.outcome(docs=docs + other), ValidatedResult)

    def test_land_record_binding_and_top_window(self):
        sites, specs, _ = _load_runtime()
        spec = repair_spec(next(s for s in specs if s.site_id == 'hw-0003'))
        site = build_site_spec(sites.get('hw-0003'), spec, expected_record_id='680720')
        parts = ['245期稳杀(半)波【红双】', '244期稳杀(半)波【绿单】',
                 '243期稳杀(半)波【蓝单】', '242期稳杀(半)波【绿单】']
        docs = tuple(replace(d, linked_record_id='680720') for d in self.documents(parts))
        registry = build_default_registry()
        registry.bind(spec)
        def result(documents, issue=245):
            return validate_evidence(site, issue, registry.parse(site, documents, issue))
        self.assertEqual(result(docs).value, '红双')
        self.assertEqual(result(docs).evidence.boundary_issues, (245, 244, 243))
        self.assertNotIsInstance(result(docs, 242), ValidatedResult)
        self.assertNotIsInstance(result(docs, 246), ValidatedResult)
        self.assertNotIsInstance(result(tuple(replace(d, linked_record_id='wrong')
                                              for d in docs)), ValidatedResult)
        self.assertNotIsInstance(result(tuple(replace(d, content=d.content.replace('稳杀(半)波', '必杀二尾'))
                                              for d in docs)), ValidatedResult)
        conflict = replace(docs[0], document_id='conflict', order=-1,
                           content='245期稳杀(半)波【蓝双】')
        self.assertNotIsInstance(result((conflict,) + docs), ValidatedResult)


if __name__ == '__main__':
    unittest.main()
