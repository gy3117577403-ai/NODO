import re

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import specification as spec, workbench


CATEGORIES = {
    'T5-55': '安装与固定', 'EX-COVER': '防护与通风', 'EX-BASE': '底座与支撑',
    'EX-LOCK-22': '锁具与门控', 'AE-SQ35': '锁具与门控',
}
PREVIEW_KEY = re.compile(r'[a-z0-9][a-z0-9_-]{0,100}-v[1-9][0-9]*')
PREVIEW_FILES = {'mesh': ('meshes', '.json'), 'thumbnail': ('thumbnails', '.png')}
MODEL_TYPES = {'step': '固定 STEP', 'lock': '固定尺寸', 'canopy': '按柜体尺寸', 'base': '按柜体尺寸'}


class DrawAccessory(models.Model):
    _name = 'nodo.draw.accessory'
    _description = '附件库型号版本'
    _order = 'code, version desc'

    company_id = fields.Many2one('res.company', required=True, index=True)
    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    version = fields.Integer(required=True)
    category = fields.Char(required=True)
    state = fields.Selection([('available', '可用于装配'), ('pending', '待工程核对'), ('retired', '已停用')], required=True)
    definition = fields.Json(required=True)
    preview_key = fields.Char(required=True)
    _unique_version = models.Constraint('UNIQUE(company_id,code,version)', '同一公司的附件型号版本已存在。')

    @api.model
    def _init_builtin_catalog(self):
        for company in self.env['res.company'].sudo().search([]):
            self.with_company(company)._seed_catalog()

    @api.model
    def _seed_catalog(self, include_local=False):
        company = self.env.company
        records = self.sudo()
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [f'nodo.draw.catalog/{company.id}'])
        existing = {(item.code, item.version) for item in records.search([('company_id', '=', company.id)])}
        definitions = [(code, definition, 'available', CATEGORIES[code]) for code, definition in spec.LIBRARY.items()]
        if include_local:
            manifest = workbench.read_json(workbench.EXCHANGE / 'catalog' / 'pending.json')
            if not manifest or not isinstance(manifest.get('models'), list):
                raise UserError('请先准备本机待核对型号目录。')
            definitions += [(entry['code'], entry, 'pending', entry['categoryName']) for entry in manifest['models']]
        for code, item, state, category in definitions:
            key = f"{item['id']}-v{item['version']}"
            if not PREVIEW_KEY.fullmatch(key):
                raise UserError('附件预览编号无效。')
            if (code, item['version']) not in existing:
                records.create(dict(company_id=company.id, code=code, name=item['name'], version=item['version'],
                                    category=category, state=state, definition=item, preview_key=key))
                existing.add((code, item['version']))

    @api.model
    def _assembly_library(self):
        company = self.env.company
        records = self.sudo().search([('company_id', '=', company.id)])
        if not records:
            self._seed_catalog()
            records = self.sudo().search([('company_id', '=', company.id)])
        # Explicit revision snapshots make future catalogue changes independent of the design.
        versions = {}
        for item in records:
            if item.state == 'available':
                versions.setdefault(item.code, item.definition)
        return versions

    def _preview_path(self, kind):
        if kind not in PREVIEW_FILES or not PREVIEW_KEY.fullmatch(self.preview_key):
            return None
        folder, suffix = PREVIEW_FILES[kind]
        root = (workbench.EXCHANGE / 'catalog' / folder).resolve()
        path = (root / (self.preview_key + suffix)).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None

    @api.model
    def list_accessory_models(self):
        workbench.guard(self.env)
        items = self.search([('company_id', '=', self.env.company.id), ('state', '!=', 'retired')])
        return [item._card() for item in items]

    def _card(self):
        definition = self.definition
        rules = definition.get('rules', {})
        return dict(id=self.id, code=self.code, name=self.name, version=self.version, state=self.state,
                    category=self.category, model_type=MODEL_TYPES[definition['kind']], aliases=definition.get('aliases', []),
                    faces=definition.get('faces') or rules.get('faces') or [definition.get('face')],
                    kinds=definition.get('cabinetKinds') or ['single', 'double'], max_quantity=definition.get('maxQuantity') or rules.get('maxQuantity'),
                    min_thickness=rules.get('minThickness'), max_thickness=rules.get('maxThickness'),
                    source=definition.get('source', ''), evidence=rules.get('evidence', ''),
                    **{kind: f'/nodo/draw/accessory/{self.id}/{kind}' if self._preview_path(kind) else False
                       for kind in PREVIEW_FILES})
