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
