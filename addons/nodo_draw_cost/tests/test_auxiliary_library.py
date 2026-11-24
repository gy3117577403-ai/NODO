from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('nodo', 'post_install', '-at_install')
class TestAuxiliaryLibrary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = new_test_user(cls.env, login='aux.library.admin@nodo.test', groups='base.group_system')
        cls.engineer = new_test_user(
            cls.env, login='aux.library.eng@nodo.test', groups='nodo_base.group_role_engineering',
        )
        cls.costing = new_test_user(
            cls.env, login='aux.library.cost@nodo.test', groups='nodo_base.group_role_costing',
        )
        cls.rate = cls.env['nodo.cost.auxiliary.price'].with_user(cls.costing).create(dict(
            code='AUX-MOUNT-FIXTURE', name='安装固定件', price_per_unit=3.25,
        ))
        cls.versions = cls.env['nodo.draw.accessory'].sudo().create([
            cls.model_values(cls.env.company, version) for version in (1, 2)
        ])

    @classmethod
    def model_values(cls, company, version):
        return dict(company_id=company.id, code='AUX-MOUNT', name='安装固定件', version=version, category='安装与固定',
                    state='available', definition={'kind': 'step', 'face': 'mount'}, preview_key=f'aux-mount-v{version}')

    def test_exact_version_and_rules_are_available_to_engineering(self):
        self.assertEqual(self.rate.cad_model_status, 'unlinked')
        self.assertEqual(self.rate.with_user(self.engineer).auxiliary_model_preview(), {'status': 'unlinked'})
        first, second = self.versions
        names = self.versions.with_user(self.admin).name_search('AUX-MOUNT')
        self.assertEqual(dict(names), {first.id: 'AUX-MOUNT · 安装固定件 · V01', second.id: 'AUX-MOUNT · 安装固定件 · V02'})
        self.rate.with_user(self.admin).write({'cad_model_id': first.id})

        engineering = self.rate.with_user(self.engineer)
        self.assertEqual(engineering.cad_model_status, 'available')
        self.assertEqual(engineering.cad_model_label, 'AUX-MOUNT · 安装固定件 · V01')
        action = engineering.action_open_cad_model()
        self.assertEqual((action['tag'], action['params']['modelId']), ('nodo_draw.accessory_library', first.id))
        preview = engineering.auxiliary_model_preview()
        self.assertEqual((preview['status'], preview['model']['id']), ('no_mesh', first.id))
        self.assertEqual(preview['model']['faces'], ['mount'])
        with patch.object(type(first), '_preview_path', lambda model, kind: kind == 'mesh'):
            preview = engineering.auxiliary_model_preview()
            self.assertEqual(preview['status'], 'ready')
            self.assertEqual(preview['model']['mesh'], f'/nodo/draw/accessory/{first.id}/mesh')
        self.assertEqual(self.rate.price_per_unit, 3.25)

        first.state = 'retired'
        self.assertEqual(engineering.cad_model_status, 'retired')
        self.assertEqual(self.rate.with_user(self.admin).cad_model_id.id, first.id)
        self.assertEqual(engineering.auxiliary_model_preview(), {'status': 'retired'})
        with self.assertRaises(UserError):
            engineering.action_open_cad_model()

    def test_costing_edits_price_and_reads_model_status(self):
        self.rate.with_user(self.admin).write({'cad_model_id': self.versions[0].id})
        self.rate.price_per_unit = 4.50
        self.assertEqual(self.rate.cad_model_status, 'available')
        self.assertEqual(self.rate.cad_model_label, 'AUX-MOUNT · 安装固定件 · V01')
        with self.assertRaises(AccessError):
            self.rate.action_open_cad_model()
        with self.assertRaises(AccessError):
            self.rate.auxiliary_model_preview()
        with self.assertRaises(AccessError):
            self.rate.write({'cad_model_id': self.versions[1].id})
        with self.assertRaises(AccessError):
            self.rate.with_user(self.engineer).write({'price_per_unit': 1.25})
        self.assertEqual(self.rate.with_user(self.admin).cad_model_id.id, self.versions[0].id)

    def test_model_binding_rejects_another_company_or_retired_version(self):
        other_company = self.env['res.company'].create({'name': '辅料库隔离乙'})
        foreign = self.versions.create(self.model_values(other_company, 1))
        admin_rate = self.rate.with_user(self.admin)
        with self.assertRaises(UserError):
            admin_rate.write({'cad_model_id': foreign.id})
        retired = self.versions[0]
        retired.state = 'retired'
        with self.assertRaises(ValidationError):
            admin_rate.write({'cad_model_id': retired.id})
        self.assertEqual(admin_rate.cad_model_status, 'unlinked')
