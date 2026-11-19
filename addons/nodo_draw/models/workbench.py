import json
import os
import time
import uuid
from pathlib import Path

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from . import specification as spec

EXCHANGE = Path('/mnt/nodo-draw')
DRAWING_FORMAT = 2


def read_json(path):
    try:
        return json.loads(path.read_text('utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def online():
    return time.time() - read_json(EXCHANGE / 'worker.json').get('time', 0) < 25


def guard(env, sales=False):
    groups = ['nodo_base.group_role_engineering','base.group_system']
    if sales:
        groups.append('nodo_base.group_role_sales')
    if not env.su and not any(env.user.has_group(group) for group in groups):
        raise AccessError('当前账号没有技术工作台权限。')


class DrawDesign(models.Model):
    _name = 'nodo.draw.design'
    _description = '柜体设计'
    _order = 'id'
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    source = fields.Char(required=True)
    source_version = fields.Char(required=True)
    bom = fields.Json(required=True)
    library = fields.Json(required=True)
    settings = fields.Json(required=True)
    edit_number = fields.Integer(default=1, required=True)
    _source_unique = models.Constraint('UNIQUE(company_id,source,source_version)', '交接明细版本已存在。')

    @api.model
    def handoff_bom(self, payload):
        """JSON-2 sales boundary. One immutable intake per company, logical line and revision."""
        guard(self.env, sales=True)
        try:
            bom = spec.intake(payload)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        company = self.env.company
        key = f"{company.id}/{bom['source']}/{bom['source_version']}"
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [key])
        records = self.sudo()
        design = records.search([('company_id','=',company.id),('source','=',bom['source']),
                                 ('source_version','=',bom['source_version'])],limit=1)
        if design:
            if design.bom != bom:
                raise UserError('同一来源版本的内容已变化，请使用新交接版本。')
        else:
            design = records.create(dict(company_id=company.id, name=bom['title'], source=bom['source'],
                                    source_version=bom['source_version'], bom=bom, library=spec.LIBRARY,
                                    settings=spec.initial(bom)))
        return {'design_id':design.id, 'source':design.source}

    @api.model
    def list_designs(self):
        guard(self.env)
        return self.search_read([('company_id','=',self.env.company.id)],['name','source','source_version'],
                                order='source, id desc')

    def _check_read(self):
        self.ensure_one()
        guard(self.env)
        if not self.exists():
            raise UserError('设计不存在。')
        self.check_access('read')

    def workspace(self):
        self._check_read()
        jobs = self.env['nodo.draw.job'].search([('design_id','=',self.id)],order='id desc')
        # Dispatch only on a separate request or by cron after the design transaction commits.
        jobs.filtered(lambda j: not j.final_state)._dispatch()
        return dict(id=self.id,name=self.name,bom=self.bom,library=self.library,settings=self.settings,
                    edit_number=self.edit_number,online=online(),jobs=[j._info() for j in jobs])

    def apply_design(self, expected, values, operation):
        self._check_read()
        if operation not in ('save','assemble','generate'):
            raise UserError('无效的设计操作。')
        self.env.cr.execute('SELECT id FROM nodo_draw_design WHERE id=%s FOR UPDATE', [self.id])
        self.invalidate_recordset(['settings','edit_number'])
        if self.edit_number != expected:
            raise UserError('另一窗口已修改此设计，请重新载入，核对后再保存。')
        issues = []
        try:
            new = spec.edit(self.settings, values, self.bom['lines'], self.library)
            if operation == 'assemble':
                issues = spec.assemble(new, self.bom['lines'], self.library)
            if operation == 'generate':
                import copy
                required = copy.deepcopy(new)
                problems = spec.assemble(required, self.bom['lines'], self.library)
                if problems or required['instances'] != new['instances']:
                    raise ValueError('请先完成一键装配。' + '、'.join(problems))
        except ValueError as exc:
            raise UserError(str(exc)) from exc
        if new != self.settings:
            self.sudo().write({'settings':new,'edit_number':self.edit_number+1})
        jobs = self.env['nodo.draw.job'].sudo()
        kind = 'build' if operation == 'generate' else 'preview'
        current = jobs.search([('design_id','=',self.id),('edit_number','=',self.edit_number),
                               ('operation','=',kind)],order='id desc',limit=1)
        compatible = current and (kind == 'preview' or current.payload.get('drawing_format') == DRAWING_FORMAT)
        if compatible and current._info()['state'] != 'failed':
            return {'job_id':current.id, 'issues':issues}
        if not online():
            raise UserError('CAD 计算服务尚未就绪，请启动本机技术工作台服务后重试。')
        previous = jobs.search([('design_id','=',self.id),('operation','=','build')],order='version desc',limit=1)
        version = (previous.version or 0) + 1
        p = spec.parameters(new, self.library, version)
        job = jobs.create(dict(design_id=self.id,company_id=self.company_id.id,operation=kind,
                               edit_number=self.edit_number,version=version,
                               payload={'operation':kind,'parameters':p,'drawing_format':DRAWING_FORMAT,'quantity':self.bom['quantity'],
                                        'source':self.source,'source_version':self.source_version}))
        return {'job_id':job.id,'issues':issues}


class DrawJob(models.Model):
    _name = 'nodo.draw.job'
    _description = '工程生成批次'
    design_id = fields.Many2one('nodo.draw.design', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True, index=True)
    operation = fields.Selection([('preview','模型预览'),('build','一键出图')],required=True)
    edit_number = fields.Integer(required=True)
    version = fields.Integer(required=True)
    token = fields.Char(required=True, default=lambda self: uuid.uuid4().hex, copy=False)
    payload = fields.Json(required=True)
    final_state = fields.Char(index=True)
    _token_unique = models.Constraint('UNIQUE(token)', '生成编号须唯一。')

    def _folder(self):
        return EXCHANGE / self.token

    @api.model
    def _dispatch_queued(self):
        self.sudo().search([('final_state','=',False)],order='id',limit=200)._dispatch()

    def _dispatch(self):
        for job in self:
            folder = job._folder()
            folder.mkdir(parents=True, exist_ok=True)
            request = folder / 'request.json'
            if not request.exists():
                temp = folder / (uuid.uuid4().hex+'.tmp')
                temp.write_text(json.dumps(job.payload,ensure_ascii=False), 'utf-8')
                os.replace(temp, request)
            state = read_json(folder / 'status.json').get('state')
            if state in ('done','failed') and job.final_state != state:
                job.sudo().write({'final_state':state})

    def _info(self):
        self.ensure_one()
        folder = self._folder()
        status = read_json(folder / 'status.json')
        state = status.get('state','queued')
        data = dict(id=self.id,operation=self.operation,edit_number=self.edit_number,version=self.version,state=state,
                    stage=status.get('stage','等待计算'),progress=status.get('progress',0))
        if state == 'running':
            progress = read_json(folder / status['run'] / 'progress.json')
            data.update({k:progress[k] for k in ('stage','progress') if k in progress})
        if state == 'done':
            data.update({k:status[k] for k in ('sheets','cut_count','parts','step_solids','issues','dims','limits') if k in status})
            data['files'] = list(status['files'])
        if state == 'failed':
            data['error'] = status.get('error','计算未完成')
        return data
