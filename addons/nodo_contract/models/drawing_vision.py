import logging
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.drawing_vision import confirmed_millimetres, normalize_crop, read_region, valid_region, vision_config


_logger = logging.getLogger(__name__)
ACTIVE = ('queued', 'processing')


class DrawingVision(models.Model):
    _inherit = 'nodo.contract.drawing'

    vision_state = fields.Selection([
        ('queued', '补读排队中'), ('processing', '正在补读'), ('ready', '候选待复核'), ('failed', '补读未完成'),
    ], readonly=True, index=True, copy=False)
    vision_job = fields.Json(readonly=True, copy=False, groups='base.group_system')
    vision_history = fields.Json(readonly=True, copy=False)
    vision_started_at = fields.Datetime(readonly=True, copy=False)

    def _vision_config(self):
        path = self.env['ir.config_parameter'].sudo().get_str(f'nodo_contract.vision.config.{self.company_id.id}')
        return vision_config(path)

    def _vision_source(self):
        return {'sha256': self.sha256, 'candidate_id': self.active_recognition_id.id or 0,
                'recognition_token': self.recognition_token or ''}

    @api.readonly
    def get_drawing_vision(self):
        self.ensure_one()
        self.check_access('read')
        source = self._vision_source()
        job = self.sudo().vision_job or {}
        active = job.get('source') == source
        problem = ''
        try:
            self._vision_config()
        except UserError as error:
            problem = str(error)
        return {
            'source': source, 'configured': not problem, 'configuration_message': problem,
            'state': self.vision_state if active else False,
            'error': job.get('error', '') if active else '',
            'runs': [run for run in (self.vision_history or []) if run['source'] == source][-8:],
        }

    def queue_drawing_vision(self, source, page, rotation, rect, crop):
        self.ensure_one()
        self._check_editable()
        self.invalidate_recordset()
        if (self.file_kind != 'pdf' or type(page) is not int or not 1 <= page <= self.page_count
                or type(rotation) is not int or rotation not in (0, 90, 180, 270)
                or not valid_region(rect) or rect[2] * rect[3] >= 0.88):
            raise ValidationError('请在当前 PDF 页内框选要补读的局部。')
        if source != self._vision_source():
            raise ValidationError('原图或选型项目已变化，请重新框选。')
        if self.vision_state in ACTIVE:
            raise UserError('这份图纸已有待处理的补读，请等候结果。')
        self._vision_config()
        self._trusted_write({
            'vision_state': 'queued', 'vision_started_at': False,
            'vision_job': {
                'id': uuid4().hex, 'source': self._vision_source(), 'page': page, 'rotation': rotation,
                'rect': rect, 'crop': normalize_crop(crop), 'requested_by': self.env.uid,
            },
        })
        self.env.ref('nodo_contract.ir_cron_drawing_vision').sudo()._trigger()
        return self.get_drawing_vision()

    @api.model
    def _cron_process_drawing_vision(self):
        pending = [('vision_state', '=', 'queued')]
        stale = self.sudo().search([('vision_state', '=', 'processing'),
                                   ('vision_started_at', '<', fields.Datetime.now() - timedelta(minutes=4))])
        for drawing in stale.try_lock_for_update():
            drawing.invalidate_recordset()
            if drawing.vision_state == 'processing':
                drawing._finish_drawing_vision(drawing.vision_job, error='补读已中断，请重新提交选区。')
        drawing = self.sudo().search(pending, limit=1)
        if not drawing:
            return
        cron = self.env['ir.cron']
        job = drawing.vision_job
        try:
            with self.env.cr.savepoint():
                drawing.with_user(job['requested_by']).with_context(
                    allowed_company_ids=[drawing.company_id.id],
                )._check_editable()
                drawing.invalidate_recordset()
                if drawing.vision_state != 'queued' or drawing.vision_job['id'] != job['id']:
                    return
                if job['source'] != drawing._vision_source():
                    raise UserError('原图或选型项目已变化，请重新框选。')
                config = drawing._vision_config()
                drawing._trusted_write({'vision_state': 'processing', 'vision_started_at': fields.Datetime.now()})
        except (AccessError, UserError) as error:
            drawing._finish_drawing_vision(job, error=str(error))
            return
        cron._commit_progress(remaining=1)
        result, error = None, ''
        try:
            result = read_region(config, job['crop'], job['rect'])
        except UserError as exc:
            error = str(exc)
        except Exception as exc:
            _logger.warning('NODO drawing vision failed on %s: %s', drawing.id, type(exc).__name__)
            error = '智能补读异常结束，请重新提交选区。'
        self.env.invalidate_all()
        if drawing.exists():
            drawing.order_id._nodo_lock()
            drawing.invalidate_recordset()
            if drawing.vision_state == 'processing' and drawing.vision_job['id'] == job['id']:
                drawing._finish_drawing_vision(job, result, error)
        cron._commit_progress(1, remaining=self.sudo().search_count(pending))

    def _finish_drawing_vision(self, job, result=None, error=''):
        job = {key: value for key, value in job.items() if key != 'crop'}
        values = {'vision_job': {**job, 'error': error}, 'vision_state': 'failed' if error else 'ready'}
        if result is not None:
            run = {**job, **result, 'created_at': fields.Datetime.to_string(fields.Datetime.now())}
            values['vision_history'] = [*(self.vision_history or []), run]
        self._trusted_write(values)

    def review_drawing_vision(self, run_id, item_id, decision, expected=None):
        self.ensure_one()
        self._check_editable()
        self.invalidate_recordset()
        if decision not in ('apply', 'apply_mm', 'keep', 'note'):
            raise ValidationError('请选择有效的复核操作。')
        history = deepcopy(self.vision_history or [])
        run = next((entry for entry in history if entry['id'] == run_id and entry['source'] == self._vision_source()), None)
        item = next((entry for entry in run['items'] if entry['id'] == item_id), None) if run else None
        if not item:
            raise ValidationError('这条补读证据不属于当前选型。')
        if item.get('decision'):
            raise UserError('此项已复核，请刷新查看记录。')
        if decision in ('apply', 'apply_mm'):
            target = item['target']
            candidate = confirmed_millimetres(item) if decision == 'apply_mm' else item['candidate']
            if not target or candidate is None:
                raise ValidationError('此补读项需要按原图人工核对，可保存为备注。')
            if (self[target] or None) != expected:
                raise UserError('选型值已变化，请核对当前值后再采用。')
            self.write({target: candidate})
            if decision == 'apply_mm':
                item.update(reviewed_unit='mm', reviewed_value=candidate)
                decision = 'apply'
        elif decision == 'note':
            if item['status'] != 'explicit':
                raise ValidationError('此项原文待核，请对照原图后手工填写。')
            note = f"第 {run['page']} 页 · {item['label']}：{item['text']}"
            notes = (self.selection_notes or '').splitlines()
            if note not in notes:
                self.write({'selection_notes': '\n'.join([*notes, note])})
        item.update(decision=decision, reviewed_by=self.env.uid,
                    reviewed_at=fields.Datetime.to_string(fields.Datetime.now()))
        self._trusted_write({'vision_history': history})
        return self.get_drawing_vision()
