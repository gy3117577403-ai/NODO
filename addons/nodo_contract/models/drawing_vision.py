import logging
from copy import deepcopy
from datetime import timedelta
from time import monotonic, time
from uuid import uuid4

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.drawing_page_vision import (
    MIN_REFINE_SECONDS, WAIT_SECONDS, read_drawing_page, render_drawing_page, reread_drawing_page,
)
from ..services.drawing_vision import confirmed_millimetres, normalize_crop, read_region, valid_region, vision_config


_logger = logging.getLogger(__name__)
ACTIVE = ('queued', 'processing')


class DrawingVision(models.Model):
    _inherit = 'nodo.contract.drawing'

    vision_state = fields.Selection([
        ('queued', '识图排队中'), ('processing', '正在识图'), ('ready', '候选待复核'), ('failed', '识图未完成'),
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
        runs = [run for run in (self.vision_history or []) if run['source'] == source][-8:]
        state = self.vision_state if active else False
        error = job.get('error', '') if active else ''
        notice = job.get('notice', '') if active else ''
        if state in ACTIVE and job.get('deadline_at', time() + 1) <= time():
            if any(run['id'] == job['id'] for run in runs):
                state, notice = 'ready', '识图已到等待上限，保留已返回的候选。'
            else:
                state, error = 'failed', '识图已到等待上限，可重新点击识图。'
        return {
            'source': source, 'configured': not problem, 'configuration_message': problem,
            'state': state, 'stage': job.get('stage', '') if active else '',
            'error': error, 'notice': notice, 'runs': runs,
        }

    def queue_drawing_vision_page(self, source, page, rotation):
        self.ensure_one()
        self._check_editable()
        self.invalidate_recordset()
        if (self.file_kind != 'pdf' or type(page) is not int or not 1 <= page <= self.page_count
                or type(rotation) is not int or rotation not in (0, 90, 180, 270)
                or self.page_count > 1 and self.file_data_page != page):
            raise ValidationError('请打开当前选型对应的 PDF 页后识图。')
        if source != self._vision_source():
            raise ValidationError('原图或选型项目已变化，请重新打开后识图。')
        job = self.sudo().vision_job or {}
        if self.vision_state in ACTIVE and job.get('deadline_at', time() + 1) > time():
            if job.get('source') == source and job.get('page') == page:
                return self.get_drawing_vision()
            raise UserError('这份图纸已有识图任务，请等待完成。')
        self._vision_config()
        self._trusted_write({
            'vision_state': 'queued', 'vision_started_at': False,
            'vision_job': {
                'id': uuid4().hex, 'mode': 'page', 'source': source, 'page': page, 'rotation': rotation,
                'rect': [0, 0, 1, 1], 'requested_by': self.env.uid, 'deadline_at': time() + WAIT_SECONDS,
            },
        })
        self.env.ref('nodo_contract.ir_cron_drawing_vision').sudo()._trigger()
        return self.get_drawing_vision()

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
                    raise UserError('原图或选型项目已变化，请重新打开后识图。')
                if job.get('deadline_at', time() + 1) <= time():
                    raise UserError('识图已到等待上限，请重新点击识图。')
                config = drawing._vision_config()
                drawing._trusted_write({'vision_state': 'processing', 'vision_started_at': fields.Datetime.now()})
        except (AccessError, UserError) as error:
            drawing._finish_drawing_vision(job, error=str(error))
            return
        cron._commit_progress(remaining=1)
        result, error = None, ''
        try:
            if job.get('mode') == 'page':
                drawing._process_page_vision(config, job, cron)
            else:
                result = read_region(config, job['crop'], job['rect'])
        except UserError as exc:
            error = str(exc)
        except Exception as exc:
            _logger.warning('NODO drawing vision failed on %s: %s', drawing.id, type(exc).__name__)
            error = '识图异常结束，请重新点击识图。'
        if job.get('mode') != 'page' or error:
            drawing._publish_vision(job, result, error)
        cron._commit_progress(1, remaining=self.sudo().search_count(pending))

    def _process_page_vision(self, config, job, cron):
        deadline = monotonic() + job['deadline_at'] - time()
        image = render_drawing_page(self.file_data.content, job['page'], job['rotation'], deadline)
        early = None

        def publish_dimensions(result):
            nonlocal early
            result['first_ready_ms'] = round((WAIT_SECONDS - (deadline - monotonic())) * 1000)
            if self._publish_vision(job, result, stage='overview'):
                early = result
                cron._commit_progress(remaining=1)

        try:
            result, regions, areas = read_drawing_page(config, image, deadline, publish_dimensions)
        except UserError:
            if not early:
                raise
            self._publish_vision(job, early, notice='识图未完整返回，保留已返回的尺寸。')
            return
        result['first_ready_ms'] = early['first_ready_ms'] if early else round(
            (WAIT_SECONDS - (deadline - monotonic())) * 1000)
        if not areas or deadline - monotonic() < MIN_REFINE_SECONDS:
            self._publish_vision(job, result)
            return
        if not self._publish_vision(job, result, stage='reread'):
            return
        if not cron._commit_progress(remaining=1):
            self._publish_vision(job, result, notice='整页候选已返回，可继续人工核对。')
            return
        try:
            items, request_id = reread_drawing_page(config, image, regions, areas, deadline)
        except UserError:
            self._publish_vision(job, result, notice='局部复读未完成，保留整页候选。')
            return
        originals = result['items']
        for index, item in enumerate(items, len(originals) + 1):
            item['id'] = str(index)
        found = {item['field'] for item in items}
        self._publish_vision(job, {
            **result, 'items': [*items, *originals],
            'missing_fields': [field for field in result['missing_fields'] if field not in found],
            'reread_request_id': request_id,
        })

    def _publish_vision(self, job, result=None, error='', *, stage='', notice=''):
        self.env.invalidate_all()
        if not self.exists():
            return False
        self.order_id._nodo_lock()
        self.invalidate_recordset()
        if self.vision_state != 'processing' or self.vision_job['id'] != job['id']:
            return False
        if job['source'] != self._vision_source():
            self._finish_drawing_vision(job, error='原图或选型项目已变化，请重新打开后识图。')
            return False
        self._finish_drawing_vision(job, result, error, stage=stage, notice=notice)
        return True

    def _finish_drawing_vision(self, job, result=None, error='', *, stage='', notice=''):
        job = {key: value for key, value in job.items() if key != 'crop'}
        state = 'processing' if stage else 'failed' if error else 'ready'
        values = {'vision_job': {**job, 'error': error, 'stage': stage, 'notice': notice}, 'vision_state': state}
        if result is not None:
            history = self.vision_history or []
            previous = next((run for run in history if run['id'] == job['id']), {})
            decisions = {item['id']: item for item in previous.get('items', []) if item.get('decision')}
            run = {
                **job, **result, 'created_at': fields.Datetime.to_string(fields.Datetime.now()),
                'items': [decisions.get(item['id'], item) for item in result['items']],
            }
            values['vision_history'] = [*(run for run in history if run['id'] != job['id']), run]
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
