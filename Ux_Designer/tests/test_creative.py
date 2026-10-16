import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import composer
import creative as ux
import designer as core
import fixtures
import generator
import reference
import styles

STYLE = styles.palette_style("cobalt")


def chart(dtype='string', aggregate=0, query_alias='q', kind='clusteredColumnChart'):
    category = {'Column': {'Expression': {'SourceRef': {'Source': 'p'}}, 'Property': 'Category'}}
    value = {'Aggregation': {'Expression': {'Column': {'Expression': {'SourceRef': {'Source': 'p'}}, 'Property': 'Value'}}, 'Function': aggregate}}
    prototype = {'From': [{'Name': 'p', 'Entity': 'Facts'}], 'Select': [{'Name': 'Facts.Category', **category}, {'Name': 'Total', **value}],
                 'OrderBy': [{'Direction': 2, 'Expression': value}]}
    query = core.strict_json(core.json_text(prototype).replace('"Source":"p"', '"Source":"' + query_alias + '"'))
    query['From'][0]['Name'] = query_alias
    query['Where'] = [{'Condition': {'Literal': {'Value': 'keep-filter'}}}]
    command = {'Commands': [{'SemanticQueryDataShapeCommand': {'Query': query, 'Binding': {'Primary': {'Groupings': [{'Projections': [0, 1]}]}}}}]}
    config = {'name': 'visual1', 'layouts': [{'id': 0, 'position': {'x': 0, 'y': 0, 'width': 1000, 'height': 600, 'z': 7}}],
              'singleVisual': {'visualType': kind, 'prototypeQuery': prototype,
                               'projections': {'Category': [{'queryRef': 'Facts.Category', 'active': True}], 'Y': [{'queryRef': 'Total'}]}}}
    visual = {'x': 0, 'y': 0, 'width': 1000, 'height': 600, 'z': 7, 'config': core.json_text(config), 'query': core.json_text(command), 'filters': '[{"keep":1}]',
              'dataTransforms': core.json_text({'selects': [{'queryName': 'Facts.Category'}, {'queryName': 'Total', 'sort': 2, 'sortOrder': 0}], 'projectionOrdering': {'Category': [0], 'Y': [1]}})}
    index = {('Facts', 'Category'): {'table': 'Facts', 'name': 'Category', 'kind': 'column', 'dataType': dtype},
             ('Facts', 'Value'): {'table': 'Facts', 'name': 'Value', 'kind': 'column', 'dataType': 'int64'}}
    return visual, index


def report(*visuals):
    return {'config': '{}', 'sections': [{'name': 'Page', 'displayName': 'Analysis', 'width': 1280, 'height': 720, 'config': '{}',
                                          'visualContainers': list(visuals)}]}


def run_apply(layout, metadata, raw=None):
    pages = ux.prepare_inventory(layout, metadata)
    decisions = [ux.repair_decision(raw, p) for p in pages]
    geometry, heights = {}, {}
    for page, decision in zip(pages, decisions):
        if page['reflow']:
            heights[page['page']], geometry[page['page']] = composer.arrange(page['width'], page['height'], ux.layout_items(page, decision), 'spotlight')
    edited, changes, inserted, chart_changes = ux.apply_redesign(layout, pages, decisions, STYLE, geometry, heights, {})
    ux.verify(layout, edited, changes, inserted)
    return edited, changes, chart_changes, pages


class ImproveTests(unittest.TestCase):
    def test_text_categories_become_horizontal_bars_never_lines(self):
        visual, metadata = chart()
        evidence = ux.chart_evidence(visual, metadata)
        self.assertNotIn('lineChart', evidence['allowed_types'])
        self.assertEqual(evidence['recommended_type'], 'clusteredBarChart')
        page = ux.prepare_inventory(report(visual), metadata)[0]
        raw = {'palette': 'teal', 'composition': 'balanced', 'visuals': [{'visual': 0, 'chart_type': 'lineChart', 'priority': 1, 'title': 'X', 'reason': 'r'}]}
        self.assertEqual(ux.repair_decision(raw, page)['visuals'][0]['chart_type'], 'clusteredBarChart')
        raw['visuals'][0]['chart_type'] = 'clusteredColumnChart'
        self.assertEqual(ux.repair_decision(raw, page)['visuals'][0]['chart_type'], 'clusteredBarChart')

    def test_date_axis_becomes_line_and_bindings_are_identical(self):
        visual, metadata = chart('dateTime', query_alias='actual')
        layout = report(visual)
        edited, _, changes, _ = run_apply(layout, metadata)
        after = edited['sections'][0]['visualContainers'][0]
        self.assertEqual(changes[0]['to'], 'lineChart')
        before_q, after_q = core.strict_json(visual['query']), core.strict_json(after['query'])
        self.assertEqual(after_q['Commands'][0]['SemanticQueryDataShapeCommand']['Query']['OrderBy'][0]['Expression']['Column']['Expression']['SourceRef']['Source'], 'actual')
        after_q['Commands'][0]['SemanticQueryDataShapeCommand']['Query']['OrderBy'] = before_q['Commands'][0]['SemanticQueryDataShapeCommand']['Query']['OrderBy']
        self.assertEqual(before_q, after_q)
        self.assertEqual(core.parsed_config(visual)['singleVisual']['projections'], core.parsed_config(after)['singleVisual']['projections'])
        self.assertEqual(visual['filters'], after['filters'])

    def test_year_number_and_date_hierarchy_are_time_axes(self):
        self.assertTrue(ux.is_temporal({'name': 'Year', 'dataType': 'int64'}))
        self.assertTrue(ux.is_temporal({'name': 'Yıl', 'dataType': 'int64'}))
        self.assertFalse(ux.is_temporal({'name': 'Age', 'dataType': 'int64'}))
        level = {'HierarchyLevel': {'Expression': {'Hierarchy': {'Expression': {'PropertyVariationSource': {'Property': 'OrderDate'}}, 'Hierarchy': 'Date Hierarchy'}}, 'Level': 'Year'}}
        self.assertTrue(ux.is_temporal(ux.field_info(level, {}, {})))

    def test_pie_only_for_counts_of_boolean_and_never_averages(self):
        visual, metadata = chart('boolean', 5)
        self.assertIn('donutChart', ux.chart_evidence(visual, metadata)['allowed_types'])
        visual, metadata = chart('boolean', 1)
        self.assertNotIn('pieChart', ux.chart_evidence(visual, metadata)['allowed_types'])

    def test_stacked_series_stays_in_bar_family(self):
        visual, metadata = chart()
        config = core.parsed_config(visual)
        config['singleVisual']['visualType'] = 'columnChart'
        config['singleVisual']['projections']['Series'] = [{'queryRef': 'Facts.Other'}]
        visual['config'] = core.json_text(config)
        evidence = ux.chart_evidence(visual, metadata)
        self.assertEqual(evidence['recommended_type'], 'barChart')
        self.assertFalse({'pieChart', 'donutChart', 'lineChart'} & set(evidence['allowed_types']))

    def test_model_metadata_excludes_expressions_and_data_sources(self):
        raw = core.json_text({'model': {'dataSources': [{'connectionString': 'secret'}], 'tables': [{'name': 'Facts', 'columns': [{'name': 'A', 'dataType': 'string', 'expression': 'secret formula'}], 'measures': [{'name': 'B', 'expression': 'secret DAX'}]}]}}).encode()
        self.assertNotIn('secret', core.json_text(list(ux.metadata_index(raw).values())))

    def test_semantic_mutation_and_forged_mask_rejected(self):
        visual, metadata = chart()
        before = report(visual)
        after, changes, _, _ = run_apply(before, metadata)
        bad = copy.deepcopy(after); bad['sections'][0]['visualContainers'][0]['filters'] = '[1]'
        with self.assertRaises(ValueError): ux.verify(before, bad, changes)
        with self.assertRaises(ValueError): ux.verify(before, bad, changes + [('sections', 0, 'visualContainers', 0, 'filters')])
        cfg = core.parsed_config(after['sections'][0]['visualContainers'][0])
        cfg['singleVisual']['projections']['Y'][0]['queryRef'] = 'Other'
        bad = copy.deepcopy(after); bad['sections'][0]['visualContainers'][0]['config'] = core.json_text(cfg)
        with self.assertRaises(ValueError): ux.verify(before, bad, changes)

    def test_header_text_preserved_conditional_color_survives(self):
        visual, metadata = chart()
        config = core.parsed_config(visual)
        original = [{'selector': {'id': 'semantic'}, 'properties': {'defaultColor': core.color('#FF0000')}}]
        config['singleVisual']['objects'] = {'dataPoint': original}
        visual['config'] = core.json_text(config)
        text = copy.deepcopy(visual)
        tconfig = core.parsed_config(text)
        tconfig['singleVisual'] = {'visualType': 'textbox', 'objects': {'general': [{'properties': {'paragraphs': [{'textRuns': [{'value': 'Actual report title'}]}]}}]}}
        text['config'] = core.json_text(tconfig); text.pop('query'); text.pop('dataTransforms')
        edited, _, _, _ = run_apply(report(visual, text), metadata)
        run = core.parsed_config(edited['sections'][0]['visualContainers'][1])['singleVisual']['objects']['general'][0]['properties']['paragraphs'][0]['textRuns'][0]
        self.assertEqual(run['value'], 'Actual report title')
        self.assertEqual(core.parsed_config(edited['sections'][0]['visualContainers'][0])['singleVisual']['objects']['dataPoint'], original)

    def test_garbage_model_answers_are_repaired(self):
        visual, metadata = chart()
        page = ux.prepare_inventory(report(visual, copy.deepcopy(visual)), metadata)[0]
        for raw in [None, {}, {'visuals': 'x'}, {'visuals': [{'visual': 99}]}, {'palette': 'neon', 'visuals': [{'visual': 0, 'chart_type': 'gauge', 'priority': 9, 'title': '{evil}'}]}]:
            decision = ux.repair_decision(raw, page)
            ux.check_decision(decision, page)
            self.assertEqual(sum(r['priority'] == 1 for r in decision['visuals']), 1)
            self.assertIn(decision['palette'], styles.PALETTES)

    def test_arrange_has_no_overlap_and_leads_with_priority(self):
        items = [{'key': i, 'group': g, 'order': (i, 0), 'priority': 1 if i == 5 else 2, 'w': 300, 'h': 200, 'text_len': 20}
                 for i, g in enumerate(['header', 'decor', 'kpi', 'kpi', 'filter', 'chart', 'chart', 'chart', 'chart'])]
        height, rects = composer.arrange(1280, 720, items)
        self.assertTrue(composer.valid(rects, 1280, height))
        charts = [rects[i] for i in (5, 6, 7, 8)]
        self.assertEqual(max(charts, key=lambda r: r['width'] * r['height']), rects[5])

    def test_palettes_keep_text_readable(self):
        for name in styles.PALETTES:
            style = styles.palette_style(name)
            for background in ('background', 'surface', 'header'):
                for text in ('text', 'muted'):
                    self.assertGreaterEqual(styles.contrast(style[text], style[background]), 4.5, (name, background, text))
        style = styles.build_style({'background': '#FFFFFF', 'surface': '#FFFFFF', 'text': '#EEEEEE', 'banner': '#FFFF00'})
        self.assertGreaterEqual(styles.contrast(style['text'], style['surface']), 7)
        self.assertGreaterEqual(styles.contrast(style['banner_text'], style['banner']), 4.5)


def sample_reference(path):
    image = Image.new('RGB', (1600, 900), '#EDEEF3')
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, 1590, 90], fill='#3F3474')
    for i in range(4):
        draw.rectangle([20 + i * 395, 110, 395 + i * 395, 250], fill='#FFFFFF')
    for row in range(2):
        for colm in range(3):
            x, y = 20 + colm * 527, 270 + row * 315
            draw.rectangle([x, y, x + 510, y + 300], fill='#FFFFFF')
            draw.rectangle([x + 40, y + 80, x + 400, y + 120], fill='#B565CC')
    image.save(path)


class ReferenceTests(unittest.TestCase):
    def test_profile_finds_banner_kpis_and_chart_grid(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ref.png'; sample_reference(path)
            profile = reference.reference_profile(path)
        self.assertIsNotNone(profile['banner'])
        self.assertEqual((len(profile['small']), len(profile['large'])), (4, 6))
        self.assertEqual(profile['palette'], 'violet')
        self.assertGreaterEqual(styles.contrast(profile['colors']['banner_text'], profile['colors']['banner']), 4.5)
        self.assertLess(core.luminance(profile['colors']['banner']), .1)

    def test_slots_fit_any_number_of_visuals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ref.png'; sample_reference(path)
            profile = reference.reference_profile(path)
        for kpis in range(0, 9):
            for charts in range(0, 10):
                items = [{'key': 'title', 'group': 'header', 'order': (0, 0), 'priority': 1, 'w': 1280, 'h': 60, 'text_len': 10}]
                items += [{'key': f'k{i}', 'group': 'kpi', 'order': (1, i), 'priority': 2, 'w': 200, 'h': 100, 'text_len': 0} for i in range(kpis)]
                items += [{'key': f'c{i}', 'group': 'chart', 'order': (2, i), 'priority': 1 if i == 0 else 2, 'w': 400, 'h': 300, 'text_len': 0} for i in range(charts)]
                result = composer.fit_to_slots(1280, 720, items, profile) or composer.arrange(1280, 720, items)
                height, rects = result
                self.assertEqual(len(rects), len(items))
                self.assertTrue(composer.valid(rects, 1280, height), (kpis, charts))


class BlankTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.pbit = Path(self.folder.name) / 'rich.pbit'
        fixtures.build(self.pbit)
        parts = zipfile.ZipFile(self.pbit)
        self.cat = generator.catalog(parts.read('DataModelSchema'))
        self.ids = {(f['table'], f['name']): f['id'] for f in self.cat['fields'].values()}

    def tearDown(self):
        self.folder.cleanup()

    def test_catalog_hides_internal_fields(self):
        names = {(f['table'], f['name']) for f in self.cat['fields'].values()}
        self.assertNotIn(('Sales', 'ProductKey'), names)
        self.assertFalse(any(t.startswith('LocalDateTable') for t, _ in names))
        self.assertFalse(any(n.startswith('RowNumber') for _, n in names))
        self.assertEqual(self.cat['fields'][self.ids[('Sales', 'Amount')]]['default_agg'], 'sum')

    def test_plan_repair_enforces_logic(self):
        i = self.ids
        raw = {'palette': 'teal', 'pages': [{'title': 'P', 'kpis': [{'field': i[('Sales', 'Total Sales')], 'agg': 'sum', 'title': 'T'}],
               'slicers': [i[('Sales', 'Amount')], i[('Sales', 'Region')]],
               'charts': [{'type': 'bar', 'category': i[('Sales', 'OrderDate')], 'values': [{'field': i[('Sales', 'Amount')], 'agg': 'sum'}], 'title': '', 'priority': 1},
                          {'type': 'line', 'category': i[('Product', 'Category')], 'values': [{'field': i[('Sales', 'Total Sales')], 'agg': 'none'}], 'title': '', 'priority': 2},
                          {'type': 'donut', 'category': i[('Sales', 'Region')], 'values': [{'field': i[('Sales', 'Amount')], 'agg': 'average'}], 'title': '', 'priority': 2},
                          {'type': 'bar', 'category': i[('Product', 'Category')], 'values': [{'field': i[('Unrelated', 'Score')], 'agg': 'sum'}], 'title': '', 'priority': 2}]}]}
        plan, used = generator.repair_plan(raw, self.cat, ([], []))
        page = plan['pages'][0]
        self.assertTrue(used)
        self.assertEqual(page['kpis'][0]['agg'], 'none')
        self.assertEqual(page['slicers'], [i[('Sales', 'Region')]])
        self.assertEqual([c['type'] for c in page['charts']], ['line', 'bar', 'bar'])

    def test_empty_model_answer_falls_back_to_a_full_plan(self):
        for raw in [None, {'pages': []}]:
            plan, _ = generator.repair_plan(raw, self.cat, ([], []))
            self.assertTrue(plan['pages'][0]['charts'])


class EndToEndTests(unittest.TestCase):
    """Full pipeline with Ollama unreachable: the deterministic designer must still deliver."""
    def setUp(self):
        self.url, core.OLLAMA_URL = core.OLLAMA_URL, 'http://127.0.0.1:9'
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        fixtures.build(self.root / 'rich.pbit')
        sample_reference(self.root / 'ref.png')

    def tearDown(self):
        core.OLLAMA_URL = self.url
        self.folder.cleanup()

    def test_all_three_modes(self):
        import creative
        source = self.root / 'rich.pbit'
        for mode in ('improve', 'reference', 'blank'):
            with self.subTest(mode=mode):
                target = self.root / f'{mode}.pbit'
                if mode == 'blank':
                    result = generator.redesign(source, target)
                else:
                    result = creative.redesign(source, target, mode=mode, reference=self.root / 'ref.png' if mode == 'reference' else None)
                self.assertFalse(result['model_used'])
                with zipfile.ZipFile(source) as a, zipfile.ZipFile(target) as b:
                    self.assertEqual(a.read('DataModelSchema'), b.read('DataModelSchema'))
                    layout, _, _ = core.decode_layout(b.read('Report/Layout'))
                self.assertTrue(layout['sections'])
                if mode != 'blank':
                    self.assertTrue(result['chart_changes'])


if __name__ == '__main__':
    unittest.main()
