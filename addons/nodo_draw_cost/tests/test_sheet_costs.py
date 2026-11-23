import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.addons.nodo_draw.models import specification as spec, workbench


@tagged('nodo', 'post_install', '-at_install')
class TestWorkbenchSheetCost(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engineer = new_test_user(cls.env, login='cost.engineer@nodo.test', groups='nodo_base.group_role_engineering')
        cls.sales = new_test_user(cls.env, login='cost.sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.model = cls.env['nodo.draw.design']
        other = cls.model.with_user(cls.sales).handoff_bom(spec.SAMPLES[0])
        cls.design = cls.model.browse(other['design_id']).with_user(cls.engineer)

    def test_sheet_costs_use_the_bound_model_and_live_prices(self):
        sample = {**spec.SAMPLES[1], 'lines': []}
        design = self.model.browse(self.model.with_user(self.sales).handoff_bom(sample)['design_id']).with_user(self.engineer)
        book = self.env['nodo.cost.sheet.price']
        right = book.create(dict(category='cold_rolled', grade='DC01', supply_condition='A', thickness_mm=2, price_per_kg=5))
        book.create(dict(category='cold_rolled', thickness_mm=2, price_per_kg=30))
        mount = book.create(dict(category='galvanized', thickness_mm=2.5, price_per_kg=9))
        settings = copy.deepcopy(design.workspace()['settings'])
        settings['materials']['parts'] = {'door': {'category':'cold_rolled', 'grade':'dc01', 'condition':'A'}}
        jobs = self.env['nodo.draw.job']
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=True):
            model = jobs.browse(design.preview_cabinet(design.edit_number, settings, 'cabinet'))
            model._folder().mkdir(exist_ok=True)
            (model._folder()/'status.json').write_text(json.dumps({'state':'done', 'files':{'mesh':'mesh.json'}}), 'utf-8')
            usage = jobs.browse(design.request_sheet_usage(design.edit_number, model.id))
            run = usage._folder() / 'run-test'
            run.mkdir(parents=True, exist_ok=True)
            (run/'usage.json').write_text(json.dumps({'sheet_profile': usage.payload['sheet_profile'], 'rows': [
                {'key':'door_right', 'weight':6.12795, 'thickness':2.0, 'material':'早期预览的显示名称'},
                {'key':'mount', 'weight':12.0, 'thickness':2.5},
            ]}), 'utf-8')
            (usage._folder()/'status.json').write_text(json.dumps({'state':'done', 'run':run.name,
                                                                   'files':{'usage':'usage.json'}}), 'utf-8')
            self.assertIn(right.id, [p['id'] for p in design.sheet_price_choices()])
            original_version = design.edit_number
            self.assertEqual(design.current_sheet_costs(usage.id)['total'], 166.37)
            right.price_per_kg = 7
            refreshed = design.current_sheet_costs(usage.id)
            self.assertEqual(refreshed['lines']['door_right']['unit'], 7)
            self.assertEqual(refreshed['total'], 181.07)
            self.assertAlmostEqual(refreshed['weights']['door_right']['loss_weight'], 6.12795 * .2)
            self.assertAlmostEqual(refreshed['billable_weight'], 18.12795 * 1.2)
            mount.active = False
            self.assertIsNone(design.current_sheet_costs(usage.id)['total'])
            self.assertEqual(design.edit_number, original_version)
            self.assertEqual(design.request_sheet_usage(original_version, model.id), usage.id)
            with self.assertRaises(AccessError):
                design.with_user(self.sales).sheet_price_choices()
            with self.assertRaises(AccessError):
                design.with_user(self.sales).current_sheet_costs(usage.id)
            with self.assertRaises(UserError):
                self.design.current_sheet_costs(usage.id)
            design.apply_design(original_version, settings, 'save')
            saved = design.workspace()['settings']
            self.assertEqual(saved['materials']['parts']['door'], settings['materials']['parts']['door'])
            self.assertEqual(design.edit_number, original_version + 1)
            with self.assertRaisesRegex(UserError, '当前版本'):
                design.current_sheet_costs(usage.id)
