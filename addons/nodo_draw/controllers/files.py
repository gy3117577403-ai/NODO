from pathlib import Path
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request
from odoo.http.stream import Stream

from ..models import standard_drawings, workbench


def artifact_response(path, download_name):
    stat = path.stat()
    mime = {'.svg':'image/svg+xml','.json':'application/json','.csv':'text/csv; charset=utf-8',
            '.zip':'application/zip'}.get(path.suffix,'application/octet-stream')
    stream = Stream(type='path', path=str(path), size=stat.st_size, mimetype=mime, public=False,
                    download_name=download_name, last_modified=stat.st_mtime)
    response = stream.get_response(as_attachment=path.suffix not in ('.json', '.svg'))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


class DrawFiles(http.Controller):
    @http.route('/nodo/draw/accessory/<int:model_id>/mesh', type='http', auth='user', methods=['GET'])
    def accessory_mesh(self, model_id):
        workbench.guard(request.env)
        item = request.env['nodo.draw.accessory'].search([
            ('id', '=', model_id), ('company_id', '=', request.env.company.id), ('state', '!=', 'retired'),
        ], limit=1)
        path = item._mesh_path() if item else None
        if not path:
            raise NotFound()
        return artifact_response(path, f'{item.code}-V{item.version:02}.json')

    @http.route('/nodo/draw/file/<int:job_id>/<string:key>', type='http', auth='user', methods=['GET'])
    def artifact(self, job_id, key, **kwargs):
        job = request.env['nodo.draw.job'].browse(job_id).exists()
        if not job:
            raise NotFound()
        job.check_access('read')
        status = workbench.read_json(job._folder()/'status.json')
        name = status.get('files', {}).get(key)
        if not name or status['state'] != 'done':
            raise NotFound()
        root = (job._folder()/status['run']).resolve()
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise NotFound()
        return artifact_response(path, f'{job.design_id.source}-V{job.version:02}-{Path(name).name}')

    @http.route('/nodo/draw/reference/<string:kind>/<string:key>/<string:extension>',
                type='http', auth='user', methods=['GET'])
    def original_drawing(self, kind, key, extension, **kwargs):
        workbench.guard(request.env)
        if kind not in standard_drawings.STANDARDS or extension not in ('dwg', 'svg'):
            raise NotFound()
        standard = standard_drawings.catalog(workbench.EXCHANGE)[kind]
        sheet = next((row for row in standard['sheets'] if row['key'] == key), None)
        if not sheet:
            raise NotFound()
        root = (workbench.EXCHANGE / 'reference' / kind).resolve()
        path = (root / f'{key}.{extension}').resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise NotFound()
        response = artifact_response(path, sheet['filename'] if extension == 'dwg' else path.name)
        if extension == 'svg':
            response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return response
