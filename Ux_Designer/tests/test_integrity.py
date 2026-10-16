import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from designer import (apply_design, check_plan, color, decode_layout, inspect, json_text,
                      literal, read_package, set_property, validate_style, verify_layout, write_package,
                      normalize_plan, BOUNDS)

STYLE = {"background":"#F5F7FA","surface":"#FFFFFF","text":"#202C3C","muted":"#536174",
         "border":"#DFE5ED","header":"#EFF3F8","font":"Segoe UI","title_size":16,"body_size":12,"radius":10,"reason":"Test"}

def fixture():
    visual = {"x":20,"y":20,"width":400,"height":300,"z":7,"filters":"[]","query":"original query","dataTransforms":"original transforms",
              "config":json_text({"name":"v1","layouts":[{"id":0,"position":{"x":20,"y":20,"width":400,"height":300,"z":7}}],
                  "singleVisual":{"visualType":"tableEx","projections":{"Values":[{"queryRef":"Sales.Revenue"}]},"prototypeQuery":{"Select":["original"]}}})}
    return {"config":"{}","sections":[{"name":"page1","displayName":"Report","width":1280,"height":720,"filters":"[]","config":"{}","visualContainers":[visual]}]}

def transformed():
    before=fixture()
    after,changes=apply_design(before,inspect(before),STYLE,{"placements":[{"page":0,"visual":0,"x":24,"y":24,"width":1000,"height":640}]})
    return before,after,changes

class IntegrityTests(unittest.TestCase):
    def test_style_and_layout_pass_original_unchanged(self):
        a,b,c=transformed();verify_layout(a,b,c)
        self.assertEqual(a,fixture());self.assertNotEqual(a,b)

    def test_semantic_mutations_are_rejected(self):
        for field in ('filters','query','dataTransforms','z'):
            with self.subTest(field=field):
                a,b,c=transformed();b['sections'][0]['visualContainers'][0][field]='changed'
                with self.assertRaises(ValueError):verify_layout(a,b,c)

    def test_binding_changes_inside_config_rejected(self):
        a,b,c=transformed();v=b['sections'][0]['visualContainers'][0];cfg=json.loads(v['config'])
        cfg['singleVisual']['projections']['Values'][0]['queryRef']='Sales.Different';v['config']=json_text(cfg)
        with self.assertRaises(ValueError):verify_layout(a,b,c)

    def test_empty_semantic_fields_not_ignored(self):
        a,b,c=transformed();b['sections'][0].pop('filters')
        with self.assertRaises(ValueError):verify_layout(a,b,c)
        a,b,c=transformed();v=b['sections'][0]['visualContainers'][0];cfg=json.loads(v['config'])
        cfg['singleVisual']['newSemanticProperty']={};v['config']=json_text(cfg)
        with self.assertRaises(ValueError):verify_layout(a,b,c)

    def test_forged_allowlist_rejected(self):
        a,b,c=transformed();c.append(('sections',0,'filters'))
        with self.assertRaises(ValueError):verify_layout(a,b,c)

    def test_conditional_and_selected_formatting_preserved(self):
        for group in [[{'properties':{'color':{'solid':{'color':{'expr':{'Measure':'Status'}}}}}}],
                      [{'selector':{'id':'selected'},'properties':{'color':color('#00FF00')}}]]:
            container={'background':group};original=copy.deepcopy(container);changes=[]
            set_property(container,'background','color',color('#FFFFFF'),changes,())
            self.assertEqual(container,original);self.assertFalse(changes)

    def test_geometry_rejects_clipping_shrink_duplicate(self):
        inv=inspect(fixture())
        for rect in [dict(x=1000,y=20,width=400,height=300),dict(x=20,y=20,width=100,height=300)]:
            with self.assertRaises(ValueError):check_plan({'placements':[{'page':0,'visual':0,**rect}]},inv)
        rect={'page':0,'visual':0,'x':20,'y':20,'width':400,'height':300}
        with self.assertRaises(ValueError):check_plan({'placements':[rect,rect]},inv)

    def test_new_overlap_rejected(self):
        layout=fixture();second=copy.deepcopy(layout['sections'][0]['visualContainers'][0]);second['x']=500
        layout['sections'][0]['visualContainers'].append(second)
        plan={'placements':[{'page':0,'visual':i,'x':20,'y':20,'width':400,'height':300} for i in range(2)]}
        with self.assertRaises(ValueError):check_plan(plan,inspect(layout))

    def test_bookmarks_freeze_editing(self):
        layout=fixture();layout['config']=json_text({'bookmarks':[{'name':'keep'}]})
        self.assertFalse(inspect(layout)[0]['visuals'][0]['editable'])

    def test_color_contrast_enforced(self):
        validate_style(STYLE)
        with self.assertRaises(ValueError):validate_style({**STYLE,'text':'#CCCCCC'})

    def test_utf_encodings_round_trip(self):
        for enc,bom in [('utf-8',b''),('utf-8',b'\xef\xbb\xbf'),('utf-16-le',b''),('utf-16-le',b'\xff\xfe'),('utf-16-be',b'\xfe\xff')]:
            value,encoding,prefix=decode_layout(bom+json_text(fixture()).encode(enc))
            self.assertEqual(value,fixture());self.assertEqual((encoding,prefix),(enc,bom))

    def test_package_preserves_semantic_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target=Path(directory)/'input.pbit',Path(directory)/'output.pbit'
            model=b'verbatim model including roles and measures'
            manifest=b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/SecurityBindings" ContentType=""/><Override PartName="/Report/Layout" ContentType=""/></Types>'
            with zipfile.ZipFile(source,'w') as z:
                for name,data in {'Report/Layout':json_text(fixture()).encode('utf-16-le'),'DataModelSchema':model,'SecurityBindings':b'old-integrity','[Content_Types].xml':manifest,'Connections':b'opaque'}.items():z.writestr(name,data)
            original,entries,parts,comment,layout,encoding,prefix=read_package(source)
            _,after,changes=transformed();verify_layout(layout,after,changes)
            write_package(target,entries,parts,comment,prefix+json_text(after).encode(encoding))
            with zipfile.ZipFile(target) as z:
                self.assertEqual(z.read('DataModelSchema'),model);self.assertEqual(z.read('Connections'),b'opaque')
                self.assertNotIn('SecurityBindings',z.namelist());self.assertNotIn(b'SecurityBindings',z.read('[Content_Types].xml'))
            self.assertEqual(source.read_bytes(),original)
            with self.assertRaises(ValueError):write_package(target,entries,parts,comment,b'new')

    def test_non_pbit_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fake.pbit';path.write_bytes(b'not a template')
            with self.assertRaises(ValueError):read_package(path)

    def test_overflow_proposal_fitted_without_shrinking_source(self):
        inv = inspect(fixture())
        proposal = {'placements': [{'page': 0, 'visual': 0, 'x': 1200, 'y': 650, 'width': 1600, 'height': 900}]}
        before = copy.deepcopy(proposal)
        plan, adjustments = normalize_plan(proposal, inv)
        self.assertEqual(plan['placements'][0], {'page': 0, 'visual': 0, 'x': 0, 'y': 0, 'width': 1280, 'height': 720})
        self.assertEqual(proposal, before)
        self.assertEqual(adjustments[0]['action'], 'fitted_to_canvas')
        check_plan(plan, inv)

    def test_existing_fractional_overflow_is_corrected(self):
        layout = fixture()
        visual = layout['sections'][0]['visualContainers'][0]
        visual.update(x=677.8536585365854, y=75.51219512195122,
                      width=602.3414634146342, height=284.4878048780488)
        inv = inspect(layout)
        raw = {'placements': [{'page': 0, 'visual': 0, **{k: visual[k] for k in BOUNDS}}]}
        plan, adjustments = normalize_plan(raw, inv)
        rect = plan['placements'][0]
        self.assertLessEqual(rect['x'] + rect['width'], 1280)
        self.assertEqual(rect['width'], visual['width'])
        self.assertEqual(rect['height'], visual['height'])
        self.assertTrue(adjustments)
        check_plan(plan, inv)

    def test_shrink_proposal_restores_minimum_dimensions(self):
        inv = inspect(fixture())
        plan, _ = normalize_plan({'placements': [{'page': 0, 'visual': 0, 'x': 24, 'y': 24, 'width': 100, 'height': 100}]}, inv)
        self.assertEqual((plan['placements'][0]['width'], plan['placements'][0]['height']), (400, 300))

    def test_fixed_header_prevents_unsafe_layout(self):
        layout = fixture()
        layout['sections'][0]['visualContainers'][0]['y'] = 80
        fixed = copy.deepcopy(layout['sections'][0]['visualContainers'][0])
        fixed.update(x=0, y=0, width=1280, height=60)
        cfg = json.loads(fixed['config']); cfg['singleVisual']['visualType'] = 'textbox'; fixed['config'] = json_text(cfg)
        layout['sections'][0]['visualContainers'].append(fixed)
        inv = inspect(layout)
        plan, adjustments = normalize_plan({'placements': [{'page': 0, 'visual': 0, 'x': 0, 'y': 0, 'width': 1280, 'height': 720}]}, inv)
        self.assertEqual(plan['placements'][0]['y'], 80)
        self.assertEqual(adjustments[0]['action'], 'original_layout_fitted')
        check_plan(plan, inv)

    def test_geometry_repair_never_repairs_unknown_or_duplicate_ids(self):
        inv = inspect(fixture())
        row = {'page': 0, 'visual': 0, 'x': 5000, 'y': 20, 'width': 400, 'height': 300}
        for rows in [[{**row, 'visual': 10}], [row, row], [], [{**row, 'width': float('nan')}]]:
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):normalize_plan({'placements': rows}, inv)

    def test_independent_page_keeps_valid_llama_layout(self):
        layout = fixture()
        layout['sections'].append(copy.deepcopy(layout['sections'][0]))
        inv = inspect(layout)
        rows = [{'page': i, 'visual': 0, 'x': 24 if i else 1200, 'y': 24, 'width': 800, 'height': 600} for i in range(2)]
        plan, adjustments = normalize_plan({'placements': rows}, inv)
        self.assertEqual(plan['placements'][1], rows[1])
        self.assertEqual([x['page'] for x in adjustments], [0])

    def test_unrepairable_source_overflow_retained_without_new_overlap(self):
        layout = fixture()
        visual = layout['sections'][0]['visualContainers'][0]
        visual.update(x=900, y=20, width=400, height=300)
        fixed = copy.deepcopy(visual); fixed.update(x=0, width=900)
        cfg = json.loads(fixed['config']); cfg['singleVisual']['visualType'] = 'textbox'; fixed['config'] = json_text(cfg)
        layout['sections'][0]['visualContainers'].append(fixed)
        inv = inspect(layout)
        plan, adjustments = normalize_plan({'placements': [{'page': 0, 'visual': 0, 'x': 1000, 'y': 20, 'width': 400, 'height': 300}]}, inv)
        self.assertEqual(plan['placements'][0]['x'], 900)
        self.assertEqual(adjustments[0]['action'], 'original_layout_preserved')
        check_plan(plan, inv)

if __name__=='__main__':unittest.main()
