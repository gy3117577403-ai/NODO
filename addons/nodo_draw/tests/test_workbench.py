import copy
import hashlib
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

    def test_snapshot_conflict_delivery_and_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench,'EXCHANGE',Path(tmp)), patch.object(workbench,'online',return_value=True):
            settings = copy.deepcopy(self.design.settings)
            with self.assertRaises(UserError):
                self.design.apply_design(1, settings, 'generate')
            first = self.design.apply_design(1, settings, 'assemble')
            same = self.design.apply_design(self.design.edit_number, self.design.settings, 'assemble')
            self.assertEqual(first['job_id'],same['job_id'])
            with self.assertRaises(UserError):
                self.design.apply_design(1,settings,'save')
            self.design.apply_design(self.design.edit_number,self.design.settings,'generate')
            status = self.design.workspace()
            self.assertEqual(len(status['jobs']),2)
            self.assertEqual(len(list(Path(tmp).glob('*/request.json'))),2)
            job = self.env['nodo.draw.job'].browse(status['jobs'][0]['id'])
            self.assertEqual(job.payload['quantity'],2)
            with patch.object(workbench,'DRAWING_FORMAT',workbench.DRAWING_FORMAT+1):
                regenerated=self.design.apply_design(self.design.edit_number,self.design.settings,'generate')
                self.assertNotEqual(regenerated['job_id'],job.id)
                self.assertEqual(self.design.apply_design(self.design.edit_number,self.design.settings,'generate'),regenerated)
            with self.assertRaises(AccessError):
                job.with_user(self.operator).read(['payload'])
