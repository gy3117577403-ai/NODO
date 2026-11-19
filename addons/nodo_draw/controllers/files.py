from pathlib import Path
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request
from odoo.http.stream import Stream

from ..models.workbench import read_json


class DrawFiles(http.Controller):
    @http.route('/nodo/draw/file/<int:job_id>/<string:key>', type='http', auth='user', methods=['GET'])
    def artifact(self, job_id, key, **kwargs):
        job = request.env['nodo.draw.job'].browse(job_id).exists()
        if not job:
            raise NotFound()
        job.check_access('read')
        status = read_json(job._folder()/'status.json')
        name = status.get('files', {}).get(key)
        if not name or status['state'] != 'done':
            raise NotFound()
        root = (job._folder()/status['run']).resolve()
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise NotFound()
        stat = path.stat()
        mime = {'.svg':'image/svg+xml','.json':'application/json','.csv':'text/csv; charset=utf-8',
                '.zip':'application/zip'}.get(path.suffix,'application/octet-stream')
        stream = Stream(type='path',path=str(path),size=stat.st_size,mimetype=mime,public=False,
                        download_name=f'{job.design_id.source}-V{job.version:02}-{Path(name).name}',
                        last_modified=stat.st_mtime)
        response = stream.get_response(as_attachment=path.suffix not in ('.json','.svg'))
        response.headers['Cache-Control'] = 'private, no-store'
        return response
