from odoo import models
from odoo.exceptions import ValidationError


class HrVersion(models.Model):
    _inherit = 'hr.version'

    def write(self, vals):
        if 'job_id' not in vals:
            return super().write(vals)

        self.check_access('write')
        job_id = vals['job_id'] or False
        reassigned = self.filtered(lambda version: version.employee_id and version.job_id.id != job_id)
        result = super().write(vals)
        if job_id:
            for version in reassigned:
                job = version.job_id
                if not job.active or job.company_id != version.company_id or job.department_id != version.department_id:
                    raise ValidationError('请选择该员工所在公司和部门的在用岗位。')
        elif reassigned and 'job_title' not in vals:
            # The native computation leaves the previous display title when the job is cleared.
            reassigned.job_title = False
        return result
