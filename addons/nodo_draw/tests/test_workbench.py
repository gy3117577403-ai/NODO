import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from ..models import specification as spec
from ..models import workbench


@tagged('nodo', 'post_install', '-at_install')
class TestDrawWorkbench(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engineer = new_test_user(cls.env, login='cad.engineer@nodo.test', groups='nodo_base.group_role_engineering')
        cls.sales = new_test_user(cls.env, login='cad.sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.operator = new_test_user(cls.env, login='cad.operator@nodo.test', groups='base.group_user')
        cls.model = cls.env['nodo.draw.design']
        cls.raw = copy.deepcopy(spec.SAMPLES[0])
        cls.design = cls.model.browse(cls.model.with_user(cls.sales).handoff_bom(cls.raw)['design_id']).with_user(cls.engineer)

    def test_handoff_is_revisioned_and_idempotent(self):
        self.assertEqual(self.model.with_user(self.sales).handoff_bom(self.raw)['design_id'], self.design.id)
        with self.assertRaises(UserError):
            self.model.with_user(self.sales).handoff_bom({**self.raw, 'width': 411})
        revision = self.model.with_user(self.sales).handoff_bom({**self.raw, 'width':411, 'source_version':'2'})
        self.assertNotEqual(revision['design_id'], self.design.id)
        self.assertEqual(self.design.bom['width'], 380)

    def test_role_and_company_boundaries(self):
        with self.assertRaises(AccessError):
            self.model.with_user(self.operator).handoff_bom(self.raw)
        for user in (self.operator, self.sales):
            with self.assertRaises(AccessError):
                self.design.with_user(user).workspace()
        with self.assertRaises(AccessError):
            self.design.write({'settings': {}})
        other = self.env['res.company'].create({'name':'北屿设计'})
        external = self.model.sudo().with_company(other)
        design = self.model.browse(external.handoff_bom(self.raw)['design_id'])
        with self.assertRaises(AccessError):
            design.with_user(self.engineer).workspace()

    def test_catalog_snapshots_exclude_pending_and_freeze_version(self):
        catalog = self.env['nodo.draw.accessory']
        old = catalog.search([('code', '=', 'T5-55')], limit=1)
        pending = catalog.create(dict(company_id=self.env.company.id, code='PENDING-01', name='待核对型号', version=1,
                                      category='安装与固定', state='pending', definition={**old.definition, 'code': 'PENDING-01'},
                                      preview_key='pending-01-v1'))
        catalog.create(dict(company_id=self.env.company.id, code=old.code, name=old.name, version=2,
                            category=old.category, state='available', definition={**old.definition, 'version': 2},
                            preview_key='fc-plate-t5-v2'))
        cards = catalog.with_user(self.engineer).list_accessory_models()
        self.assertEqual(next(card['state'] for card in cards if card['id'] == pending.id), 'pending')
        handoff = self.model.with_user(self.sales).handoff_bom({**self.raw, 'source_version': 'catalog'})
        updated = self.model.browse(handoff['design_id']).with_user(self.engineer)
        self.assertEqual(updated.library['T5-55']['version'], 2)
        self.assertEqual(self.design.library['T5-55']['version'], 1)
        self.assertNotIn(pending.code, updated.library)
        with self.assertRaises(AccessError):
            catalog.with_user(self.operator).list_accessory_models()
        with self.assertRaises(AccessError):
            pending.with_user(self.engineer).write({'state': 'available'})

    def test_alias_compatibility_and_multiple_positions(self):
        library = copy.deepcopy(spec.LIBRARY)
        library['T5-55'].update(aliases=['样例五孔板'], rules={'minThickness': 1.5, 'maxThickness': 2.5})
        bom = spec.intake({**spec.SAMPLES[1], 'lines': [{'code': '样例五孔板', 'quantity': 2, 'face': 'door_right'}]})
        settings = spec.initial(bom)
        self.assertEqual(spec.match_row(settings, bom['lines'], library, 0), {'code': 'T5-55', 'face': 'door_right', 'issue': ''})
        self.assertIn('缺少定位', spec.assemble(settings, bom['lines'], library)[0])
        self.assertEqual(settings['instances'], [])
        positions = {'a1n1': {'u': -45, 'v': 0}, 'a1n2': {'u': 52, 'v': 3}}
        self.assertFalse(spec.assemble(settings, bom['lines'], library, positions))
        self.assertEqual([part['u'] for part in settings['instances']], [-45, 52])
        settings['thickness'] = {'door': 3}
        self.assertIn('板厚', spec.match_row(settings, bom['lines'], library, 0)['issue'])
        library['AE-SQ35']['aliases'] = ['样例五孔板']
        self.assertIn('多个', spec.match_row(settings, bom['lines'], library, 0)['issue'])
        settings['matches'] = {'0': {'code': 'AE-SQ35'}}
        self.assertIn('柜型', spec.match_row(settings, bom['lines'], library, 0)['issue'])

    def ready_assembly(self, design, settings, issues=None):
        identifier = design.preview_assembly(design.edit_number, settings)
        folder = self.env['nodo.draw.job'].browse(identifier)._folder()
        folder.mkdir(exist_ok=True)
        (folder / 'status.json').write_text(json.dumps({'state': 'done', 'files': {'mesh': 'mesh.json'}, 'issues': issues or []}), 'utf-8')
        return identifier

    def test_assembly_requires_checked_preview_with_identical_geometry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=True):
            design = self.design
            initial = copy.deepcopy(design.settings)
            conflict = self.ready_assembly(design, initial, issues=['附件与板件干涉'])
            with self.assertRaisesRegex(UserError, '校核通过'):
                design.apply_design(1, initial, 'assemble', conflict)
            self.assertEqual(design.settings, initial)
            preview = self.ready_assembly(design, initial)
            with self.assertRaisesRegex(UserError, '重新预览'):
                design.apply_design(1, {**initial, 'width': 396}, 'assemble', preview)
            design.apply_design(1, initial, 'assemble', preview)
            with self.assertRaisesRegex(UserError, '当前参数'):
                design.apply_design(design.edit_number, {**design.settings, 'width': 396}, 'generate')
            self.assertTrue(design.workspace()['assembly_validated'])

    def test_assembly_is_per_cabinet_and_replayable(self):
        settings = spec.initial(spec.intake(self.raw))
        lines = self.design.bom['lines']
        self.assertFalse(spec.assemble(settings, lines, spec.LIBRARY))
        self.assertEqual(len(settings['instances']), 2)
        settings['instances'][0]['u'] = 20
        again = copy.deepcopy(settings)
        spec.assemble(again, lines, spec.LIBRARY)
        self.assertEqual(settings, again)
        params = spec.parameters(settings, spec.LIBRARY, 2)
        self.assertEqual(params['revision'], 'V02')
        self.assertEqual(params['accessories'][0]['u'], 20)
        self.assertEqual(len(params['accessories'][0]['definition']['holes']), 5)

    def test_unknown_model_wrong_face_and_size(self):
        settings = self.design.settings
        lines = spec.intake({**self.raw,'lines':[{'code':'缺少型号','quantity':1}]})['lines']
        self.assertTrue(spec.assemble(settings,lines,spec.LIBRARY))
        settings['matches']={'0':{'code':'T5-55','face':'door_right'}}
        self.assertTrue(spec.assemble(settings,lines,spec.LIBRARY))
        with self.assertRaises(ValueError):
            spec.edit(settings, {**settings,'width':float('nan')},lines,spec.LIBRARY)

    def test_hole_copy_rejects_identical_footprint_on_same_face(self):
        saved = self.design.workspace()
        first = dict(id='H1', face='door', type='circle', u=122.98, v=169.56, diameter=22)
        copied = {**first, 'id': 'H2'}
        values = {**saved['settings'], 'holes': [first, copied]}
        with self.assertRaisesRegex(UserError, 'H2 与 H1 .*相同'):
            self.design.apply_design(saved['edit_number'], values, 'save')
        self.assertEqual(self.design.workspace()['settings'], saved['settings'])

        right_door = {**copied, 'face': 'door_right'}
        valid = {**values, 'kind': 'double', 'holes': [first, right_door]}
        edited = spec.edit(saved['settings'], valid, self.design.bom['lines'], self.design.library)
        self.assertEqual([(h['face'], h['u'], h['v'], h['anchor'], h['anchorV']) for h in edited['holes']],
                         [('door', 122.98, 169.56, 'left', 'bottom'), ('door_right', 122.98, 169.56, 'left', 'bottom')])

    def test_legacy_sheet_settings_keep_saved_values(self):
        original = self.design.settings
        legacy = {key: value for key, value in original.items() if key not in ('materials', 'thickness')}
        legacy.update(material='stainless', body=1.2, door=2.1, mount=2.7)
        self.design.sudo().write({'settings': legacy})
        workspace = self.design.workspace()
        self.assertEqual(workspace['settings']['thickness'], {'body': 1.2, 'door': 2.1, 'mount': 2.7})
        self.assertEqual(workspace['settings']['materials'],
                         {group: {'category': 'stainless'} for group in ('body', 'door', 'mount')})
        self.assertEqual(workspace['sheet_catalog']['materials']['groups']['mount'], 'galvanized')
        self.assertEqual(self.design.settings, legacy)
        result = spec.parameters(legacy, self.design.library, 1)
        self.assertEqual(result['materials'], workspace['settings']['materials'])
        self.assertEqual(result['thickness'], workspace['settings']['thickness'])

    def test_sheet_overrides_reach_the_design_snapshot(self):
        original = self.design.settings
        materials = {
            'body': {'category': 'cold_rolled', 'finish': 'RAL7035'},
            'parts': {'top': {'category': 'stainless', 'grade': '304'}},
            'finishes': {'wrap': 'RAL7035'},
        }
        thickness = {'body': 1.6, 'parts': {'top': 1.8}}
        new = spec.edit(original, {**original, 'materials': materials, 'thickness': thickness},
                        self.design.bom['lines'], self.design.library)
        payload = spec.parameters(new, self.design.library, 2)
        self.assertEqual(payload['materials'], materials)
        self.assertEqual(payload['thickness'], thickness)
        cleared = spec.edit(new, {**new, 'thickness': {'body': 1.6}, 'materials': {'body': materials['body']}},
                            self.design.bom['lines'], self.design.library)
        reset = spec.parameters(cleared, self.design.library, 3)
        self.assertEqual(reset['thickness'], {'body': 1.6})
        self.assertEqual(reset['materials'], {'body': materials['body']})

    def test_invalid_sheet_values_are_rejected(self):
        original = self.design.settings
        for patch in (
            {'materials': {'parts': {'back': {'category': 'cold_rolled'}}}},
            {'materials': {'body': {'category': ['cold_rolled']}}},
            {'materials': {'body': {'category': 'cold_rolled', 'note': '第一行\n第二行'}}},
            {'thickness': {'parts': {'top': 2.1}}},
            {'thickness': {'parts': {'brace': True}}},
            {'thickness': {'body': 3, 'parts': {'wrap': 1.4, 'top': 1.4, 'bottom': 1.4}}},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                spec.edit(original, {**original, **patch}, self.design.bom['lines'], self.design.library)

    def test_square_lock_uses_the_single_door_cutout_datum(self):
        bom = spec.intake(next(row for row in spec.SAMPLES if row['source'] == 'AE-303'))
        settings = spec.initial(bom)
        self.assertFalse(spec.assemble(settings, bom['lines'], spec.LIBRARY))
        self.assertEqual(len(settings['instances']), 4)
        definition = spec.LIBRARY['AE-SQ35']
        asset = spec.DATA / 'hardware' / (definition['assetHash'] + '.step')
        self.assertEqual(hashlib.sha256(asset.read_bytes()).hexdigest(), definition['assetHash'])
        for width in (380, 420):
            settings['width'] = width
            lock = spec.parameters(settings, spec.LIBRARY, 1)['accessories'][0]
            self.assertEqual((lock['anchor'], lock['u'], lock['anchorV'], lock['v']), ('right', 52.5, 'center', 0))
            self.assertEqual(2.5 + (width - 5) - lock['u'], width - 55)
            self.assertEqual(lock['definition']['holes'], [])
            self.assertEqual(lock['definition']['templateOpening']['width'], 21.2)
            self.assertTrue(lock['definition']['mount']['throughPanel'])
        settings['instances'][0]['u'] = 75
        relocated = spec.parameters(settings, spec.LIBRARY, 2)['accessories'][0]['definition']
        self.assertNotIn('templateOpening', relocated)
        self.assertEqual(relocated['holes'], [dict(type='rectangle',u=0,v=0,width=21.2,height=21.2)])
        settings['kind'] = 'double'
        self.assertTrue(spec.match_row(settings, bom['lines'], spec.LIBRARY, 0)['issue'])

    def test_draft_preview_keeps_saved_design_and_history(self):
        original = self.design.settings
        edited = {**original, 'kind': 'double', 'width': 420}
        edit_number = self.design.edit_number
        other_engineer = new_test_user(self.env, login='cad.colleague@nodo.test',
                                       groups='nodo_base.group_role_engineering')
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=True):
            preview_id = self.design.preview_cabinet(edit_number, edited)
            self.assertEqual(self.design.preview_cabinet(edit_number, edited), preview_id)
            preview = self.env['nodo.draw.job'].browse(preview_id).with_user(self.engineer)
            params = preview.payload['parameters']
            self.assertEqual((params['configuration']['kind'], params['width']), ('double', 420))
            self.assertEqual(preview.preview_user_id, self.engineer)
            self.assertFalse(self.design.workspace()['jobs'])
            self.env['nodo.draw.job']._dispatch_queued()
            self.assertFalse(list(Path(tmp).glob('*/request.json')))
            self.assertEqual(self.design.cabinet_preview_status(preview_id)['state'], 'queued')
            self.assertTrue((preview._folder() / 'request.json').is_file())
            with self.assertRaises(AccessError):
                preview.with_user(other_engineer).read(['payload'])
            with self.assertRaises(AccessError):
                self.design.with_user(other_engineer).cabinet_preview_status(preview_id)
            with self.assertRaisesRegex(UserError, '柜宽须在'):
                self.design.preview_cabinet(edit_number, {**edited, 'width': 0})
            workspace = self.design.workspace()
            self.assertEqual(workspace['settings'], original)
            self.assertEqual(workspace['edit_number'], edit_number)
            saved = self.design.apply_design(edit_number, original, 'save')
            self.assertNotEqual(saved['job_id'], preview_id)
            self.assertEqual([job['id'] for job in self.design.workspace()['jobs']], [saved['job_id']])

    def test_base_cabinet_preview_uses_structure_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=True):
            raw = {**self.design.settings, 'holes': [dict(id='H1', face='door', type='circle', u=95, v=110, diameter=18)]}
            preview = self.ready_assembly(self.design, raw)
            self.design.apply_design(self.design.edit_number, raw, 'assemble', preview)
            saved = self.design.settings
            self.assertEqual(len(saved['instances']), 2)
            preview_ids = {}
            jobs = self.env['nodo.draw.job']
            for kind in ('single', 'double'):
                base_id = self.design.preview_cabinet(self.design.edit_number, {**saved, 'kind': kind}, 'base')
                preview_ids[kind] = base_id
                base = jobs.browse(base_id).payload['parameters']
                self.assertEqual(base['configuration']['kind'], kind)
                self.assertEqual((base['width'], base['height'], base['depth']), (380, 300, 210))
                self.assertEqual((base['holes'], base['accessories']), ([], []))
            full_id = self.design.preview_cabinet(self.design.edit_number, saved, 'design')
            full = jobs.browse(full_id).payload['parameters']
            self.assertEqual(len(full['accessories']), 2)
            self.assertEqual(full['holes'][0]['id'], 'H1')
            cabinet_id = self.design.preview_cabinet(self.design.edit_number, saved, 'cabinet')
            cabinet = jobs.browse(cabinet_id).payload['parameters']
            self.assertEqual(cabinet['accessories'], [])
            self.assertEqual(cabinet['holes'], full['holes'])
            self.assertEqual(self.design.preview_cabinet(self.design.edit_number, saved, 'cabinet'), cabinet_id)
            self.assertEqual(self.design.preview_cabinet(self.design.edit_number, saved, 'base'), preview_ids['single'])
            self.assertEqual(self.design.settings, saved)

    def test_original_drawing_reuse_and_parameter_change(self):
        raw = {**self.raw, 'source': '基础柜体', 'lines': []}
        design = self.model.browse(self.model.with_user(self.sales).handoff_bom(raw)['design_id']).with_user(self.engineer)
        single = design.settings
        double = {**single, 'kind': 'double', 'width': 1000, 'height': 700, 'depth': 300}
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=False) as worker:
            for kind, settings in (('single', single), ('double', double)):
                root = Path(tmp) / 'reference' / kind
                root.mkdir(parents=True)
                (root / 'index.json').write_text('[{"key":"basis_01"}]', 'utf-8')
                result = design.apply_design(design.edit_number, settings, 'generate')
                self.assertEqual(result, {'reference_kind': kind, 'issues': []})
            self.assertFalse(design.workspace()['jobs'])
            worker.return_value = True
            customized = {**double, 'width': 1020}
            first = design.apply_design(design.edit_number, customized, 'generate')
            self.assertEqual(design.apply_design(design.edit_number, customized, 'generate'), first)
            design.apply_design(design.edit_number, double, 'generate')
            self.assertEqual(design.apply_design(design.edit_number, customized, 'generate'), first)
            self.assertEqual([job['id'] for job in design.workspace()['jobs']], [first['job_id']])
            material_changed = {**double, 'thickness': {'body': 1.6}}
            second = design.apply_design(design.edit_number, material_changed, 'generate')
            self.assertNotEqual(second['job_id'], first['job_id'])

    def test_snapshot_conflict_delivery_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench,'EXCHANGE',Path(tmp)), patch.object(workbench,'online',return_value=True):
            settings = copy.deepcopy(self.design.settings)
            with self.assertRaises(UserError):
                self.design.apply_design(1, settings, 'generate')
            preview = self.ready_assembly(self.design, settings)
            first = self.design.apply_design(1, settings, 'assemble', preview)
            repeat = self.ready_assembly(self.design, self.design.settings)
            same = self.design.apply_design(self.design.edit_number, self.design.settings, 'assemble', repeat)
            self.assertEqual(first['job_id'],same['job_id'])
            with self.assertRaises(UserError):
                self.design.apply_design(1,settings,'save')
            self.design.apply_design(self.design.edit_number,self.design.settings,'generate')
            status = self.design.workspace()
            self.assertEqual(len(status['jobs']),2)
            self.assertEqual(len(list(Path(tmp).glob('*/request.json'))),1)
            job = self.env['nodo.draw.job'].browse(status['jobs'][0]['id'])
            self.assertEqual(job.payload['quantity'],2)
            with patch.object(workbench,'DRAWING_FORMAT',workbench.DRAWING_FORMAT+1):
                regenerated=self.design.apply_design(self.design.edit_number,self.design.settings,'generate')
                self.assertNotEqual(regenerated['job_id'],job.id)
                self.assertEqual(self.design.apply_design(self.design.edit_number,self.design.settings,'generate'),regenerated)
            with self.assertRaises(AccessError):
                job.with_user(self.operator).read(['payload'])
