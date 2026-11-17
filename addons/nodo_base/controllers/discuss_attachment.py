from os import SEEK_END

from odoo import http
from odoo.addons.mail.controllers.attachment import AttachmentController
from odoo.http import request


class DiscussAttachmentController(AttachmentController):

    @http.route()
    def mail_attachment_upload(self, ufile, thread_id, thread_model, is_pending=False, **kwargs):
        if thread_model == 'discuss.channel':
            limit_mb = request.env['discuss.channel']._nodo_file_limit_mb()
            stream = ufile.stream
            position = stream.tell()
            size = stream.seek(0, SEEK_END)
            stream.seek(position)
            if size > limit_mb * 1024**2:
                return request.make_json_response({
                    'error': {'message': f'单个文件不能超过 {limit_mb} MB。'},
                }, status=413)
        return super().mail_attachment_upload(ufile, thread_id, thread_model, is_pending, **kwargs)
