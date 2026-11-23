import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.addons.nodo_draw.models import specification, workbench


@tagged('nodo', 'post_install', '-at_install')
class TestSheetCostVersion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engineer = new_test_user(cls.env, login='version.engineer@nodo.test', groups='nodo_base.group_role_engineering')
        cls.colleague = new_test_user(cls.env, login='version.reader@nodo.test', groups='nodo_base.group_role_engineering')
        cls.sales = new_test_user(cls.env, login='version.sales@nodo.test', groups='nodo_base.group_role_sales')
        cls.costing = new_test_user(cls.env, login='version.costing@nodo.test', groups='nodo_base.group_role_costing')
        designs = cls.env['nodo.draw.design']
        cls.design = designs.browse(designs.with_user(cls.sales).handoff_bom(
            {**specification.SAMPLES[1], 'lines': []})['design_id']).with_user(cls.engineer)
        cls.rate = cls.env['nodo.cost.sheet.price'].create(dict(category='cold_rolled', thickness_mm=2, price_per_kg=5))
        cls.archive = cls.env['nodo.draw.sheet.cost.version']

    @contextmanager
    def measured(self, settings=None):
        design = self.design
        with tempfile.TemporaryDirectory() as tmp, patch.object(workbench, 'EXCHANGE', Path(tmp)), \
                patch.object(workbench, 'online', return_value=True):
            jobs = self.env['nodo.draw.job']
            model = jobs.browse(design.preview_cabinet(design.edit_number, settings or design.workspace()['settings'], 'cabinet'))
            model._folder().mkdir(exist_ok=True)
            (model._folder() / 'status.json').write_text(json.dumps({'state':'done', 'files':{'mesh':'mesh.json'}}))
            usage = jobs.browse(design.request_sheet_usage(design.edit_number, model.id))
            run = usage._folder() / 'run-test'
            run.mkdir(parents=True)
            rows = [dict(key=key, name=name, code=key, material='冷轧板', thickness=2, quantity=1,
                         area=weight / 15.7, weight=weight, needs_review=True)
                    for key, name, weight in [('door', '左门板', 6.031095738), ('door_right', '右门板', 5.825763423)]]
            data = dict(rows=rows, area=sum(r['area'] for r in rows), weight=sum(r['weight'] for r in rows),
                        density=7.85, pieces=2)
            (run / 'usage.json').write_text(json.dumps(data))
            (usage._folder() / 'status.json').write_text(json.dumps({'state':'done', 'run':run.name,
                                                                     'files':{'usage':'usage.json'}}))
            yield usage.id

    def save(self, usage):
        prices = self.design.current_sheet_costs(usage)
        return self.design.save_sheet_cost_version(self.design.edit_number, usage, prices['fingerprint'])

    def test_archived_costs_and_deltas_survive_price_restore_and_private_file_removal(self):
        design = self.design
        edit = design.edit_number
        with self.measured() as usage:
            first = self.save(usage)
            self.assertEqual(first, self.save(usage))
            self.rate.price_per_kg = 6
            second = self.save(usage)
            self.rate.price_per_kg = 5
        reader = design.with_user(self.colleague)
        self.assertEqual([v['number'] for v in reader.sheet_cost_versions()], [2, 1])
        v1, v2 = [reader.read_sheet_cost_version(i) for i in (first, second)]
        self.assertEqual(v1['saved_by'], self.engineer.display_name)
        self.assertEqual([v1['snapshot']['total'], v2['snapshot']['total']], [59.28, 71.14])
        self.assertIsNone(v1['comparison'])
        self.assertEqual(v2['comparison']['delta'], 11.86)
        self.assertEqual([line['delta'] for line in v2['comparison']['lines']], [6.031, 5.826])
        for version, unit in [(v1, 5), (v2, 6)]:
            self.assertEqual(version['snapshot']['area_basis'], 'outer_including_holes')
            self.assertEqual(version['snapshot']['trial'], 2)
            self.assertTrue(all(r['needs_review'] and r['unit'] == unit for r in version['snapshot']['rows']))
        self.assertEqual(design.edit_number, edit)

    def test_versions_reject_stale_amount_missing_price_and_unpersisted_geometry(self):
        design = self.design
        with self.measured() as usage:
            seen = design.current_sheet_costs(usage)['fingerprint']
            self.rate.price_per_kg = 6
            with self.assertRaisesRegex(UserError, '价格已变化'):
                design.save_sheet_cost_version(design.edit_number, usage, seen)
            self.rate.active = False
            with self.assertRaisesRegex(UserError, '补齐'):
                self.save(usage)
            self.rate.active = True
            with self.assertRaisesRegex(UserError, '另一窗口'):
                design.save_sheet_cost_version(design.edit_number + 1, usage, seen)
        draft = {**design.workspace()['settings'], 'width':1100}
        with self.measured(draft) as usage:
            with self.assertRaisesRegex(UserError, '柜体参数不同'):
                self.save(usage)
        self.assertFalse(design.sheet_cost_versions())

    def test_archive_company_role_and_design_boundaries(self):
        design = self.design
        with self.measured() as usage:
            first = self.save(usage)
            for user in (self.sales, self.costing, self.colleague):
                with self.assertRaises((UserError, AccessError)):
                    design.with_user(user).save_sheet_cost_version(design.edit_number, usage, 'invalid')
        version = self.archive.browse(first)
        for user in (self.sales, self.costing):
            with self.assertRaises(AccessError):
                design.with_user(user).read_sheet_cost_version(first)
            with self.assertRaises(AccessError):
                version.with_user(user).read(['payload'])
        with self.assertRaises(AccessError):
            self.archive.with_user(self.engineer).create(dict(design_id=design.id, company_id=design.company_id.id,
                number=3, fingerprint='client', payload={'total':0}))
        with self.assertRaises(UserError):
            version.with_user(self.engineer).write({'number':6})
        with self.assertRaises((UserError, AccessError)):
            version.with_user(self.engineer).unlink()
        foreign_company = self.env['res.company'].create({'name':'板料版本核对乙'})
        foreign_user = new_test_user(self.env, login='version.other@nodo.test', company_id=foreign_company.id,
            company_ids=[(6, 0, [foreign_company.id])], groups='nodo_base.group_role_engineering')
        with self.assertRaises(AccessError):
            design.with_user(foreign_user).read_sheet_cost_version(first)
        self.assertFalse(self.archive.with_user(foreign_user).search([('id','=',first)]))
        other = self.env['nodo.draw.design'].with_user(self.sales).handoff_bom(specification.SAMPLES[0])
        with self.assertRaisesRegex(UserError, '此柜体'):
            design.browse(other['design_id']).read_sheet_cost_version(first)
