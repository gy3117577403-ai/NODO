"""Read selectable PDF text locally and dispatch to the original OCR engine when configured."""

import json
import math
import os
import re
import subprocess
import sys
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from odoo.exceptions import UserError, ValidationError
from odoo.tools.pdf import PdfReader

from .drawing_selection import TEXT_LIMIT
from .quote_price import CABINET_SERIES


PDF_LIMIT = 60
FILE_LIMIT = 24 * 1024 * 1024
EXTENSIONS = {
    '.pdf': 'pdf', '.dwg': 'cad', '.dxf': 'cad', '.png': 'image', '.jpg': 'image',
    '.jpeg': 'image', '.bmp': 'image', '.tif': 'image', '.tiff': 'image',
}
DIMENSION = re.compile(r'(?<![\d.])(\d{1,6}(?:\.\d{1,3})?)(?![\d.])')
LABELS = {
    'width_mm': r'(?:总宽|宽度|宽|width)',
    'depth_mm': r'(?:总深|深度|深|depth)',
    'height_mm': r'(?:总高|高度|高|height)',
}


def inspect_file(name, content):
    kind = EXTENSIONS.get(Path(name).suffix.lower())
    if not kind:
        raise ValidationError('请上传 PDF、DWG、DXF 或常用图片格式。')
    if not content or len(content) > FILE_LIMIT:
        raise ValidationError('图纸内容为空，或超过单文件 24 MB。')
    if kind == 'pdf':
        try:
            reader = PdfReader(BytesIO(content))
            count = len(reader.pages)
            if not 0 < count <= PDF_LIMIT:
                raise ValidationError(f'PDF 须为 1 至 {PDF_LIMIT} 页。')
            pages = [{'source_page_number': index, 'raw_text': (page.extract_text() or '')[:TEXT_LIMIT]}
                     for index, page in enumerate(reader.pages, 1)]
        except (ValidationError, UserError):
            raise
        except Exception as error:
            raise ValidationError('无法读取此 PDF，请检查文件是否损坏或已加密。') from error
        return kind, count, pages
    if kind == 'image':
        try:
            with Image.open(BytesIO(content)) as image:
                count = getattr(image, 'n_frames', 1)
                if image.width * image.height > 64_000_000:
                    raise ValidationError('图纸图片超过 6400 万像素。')
                image.verify()
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError('无法读取此图片，请检查文件内容。') from error
        return kind, count, []
    return kind, 0, []


def text_suggestions(page):
    """Accept explicit product codes and dimension labels from the PDF text only."""
    source = page['raw_text'].strip()
    normalized = re.sub(r'\s+', ' ', source.upper())
    if not source:
        return None
    cabinet_codes = sorted((item[0] for item in CABINET_SERIES), key=len, reverse=True)
    match = re.compile(r'(?<![A-Z0-9])(' + '|'.join(map(re.escape, cabinet_codes)) + r')(?![A-Z])')
    series = {item.group(1) for item in match.finditer(normalized)}
    suggested = {key: float(found.group(1)) for key, label in LABELS.items()
                 if (found := re.search(label + r'\s*[:：=]?\s*(\d+(?:\.\d+)?)', normalized, re.I))}
    if len(series) == 1:
        suggested['product_series'] = next(iter(series))
    page_number = page['source_page_number']
    return {
        'name': f'第 {page_number} 页 · 图纸文字', 'page': page_number, 'suggested': suggested,
        'summary': '来源为 PDF 自带文字。请对照原图核对柜型、正侧视图尺寸和附件。',
        'attachment_names': [], 'raw': page,
    }


def rotate_rect(rect, angle):
    x, y, width, height = rect
    if angle == 90:
        return 1 - y - height, x, height, width
    if angle == 180:
        return 1 - x - width, 1 - y - height, width, height
    if angle == 270:
        return y, 1 - x - width, height, width
    return rect


def pdf_dimension_view(content, page_index, rect, rotation, orientation):
    """Read dimension labels intersecting the user's real PDF selection."""
    page = PdfReader(BytesIO(content)).pages[page_index - 1]
    width, height = float(page.cropbox.width), float(page.cropbox.height)
    left, bottom = map(float, page.cropbox.lower_left)
    total_rotation = (int(page.rotation or 0) + rotation) % 360
    tokens = []
    sx, sy, sw, sh = rect

    def visit(text, matrix, transform, font, size):
        if len(tokens) >= 120 or not size or not text.strip():
            return
        a, b, c, d, e, f = matrix
        x, y = transform[4], transform[5]
        px = a * x + c * y + e - left
        py = b * x + d * y + f - bottom
        line = text.strip()
        font_height = abs(float(size)) * math.hypot(a, b)
        box = (px / width, 1 - (py + font_height) / height,
               max(font_height, len(line) * font_height * 0.55) / width, font_height / height)
        drawn = rotate_rect(box, total_rotation)
        mid_x, mid_y = drawn[0] + drawn[2] / 2, drawn[1] + drawn[3] / 2
        if not sx <= mid_x <= sx + sw or not sy <= mid_y <= sy + sh:
            return
        named = next((key for key, label in LABELS.items() if re.search(label, line, re.I)), None)
        if not named and not re.fullmatch(r'[\sØφΦ⌀Rr\d.mmMM]+', line):
            return
        rotated_vertical = abs(transform[1] * a + transform[0] * b) > abs(transform[0] * a)
        axis = ('vertical' if named == 'height_mm' else 'horizontal') if named else (
            'vertical' if rotated_vertical != (total_rotation in (90, 270)) else 'horizontal'
        )
        for found in DIMENSION.finditer(line):
            value = float(found.group(1))
            if value > 0:
                tokens.append({'id': f'pdf-{len(tokens)}', 'rect': drawn, 'text': line[:120],
                               'axis': axis, 'value': value, 'named': bool(named)})

    page.extract_text(visitor_text=visit)

    def best(axis):
        available = [token for token in tokens if token['axis'] == axis]
        named = [token for token in available if token['named']]
        candidates = named or available
        return candidates[0]['id'] if len({token['value'] for token in candidates}) == 1 else None

    if not tokens:
        raise UserError('选框内未读到 PDF 尺寸文字，请把尺寸标注框进来，或在右侧手工填写。')
    return {
        'selection_mode': 'manual', 'reader_version': 'pdf-text', 'page': page_index, 'rotation': rotation,
        'orientation': orientation, 'regions': [rect], 'body': rect, 'tokens': tokens,
        'horizontal': best('horizontal'), 'vertical': best('vertical'),
        'file_sha256': sha256(content).hexdigest(),
    }


def original_config(path):
    if not path:
        raise UserError('原识图运行包未配置。可查看支持的原图并手工选型。')
    try:
        location = Path(path)
        config = json.loads(location.read_text(encoding='utf-8-sig'))
        for key in ('client', 'bundle', 'dependencies', 'pure_dependencies', 'workspace', 'renderer', 'converter'):
            configured = config.get(key)
            config[key] = str((location.parent / configured).resolve()) if configured else ''
        required = ('client', 'bundle', 'dependencies', 'pure_dependencies', 'workspace')
        if any(not config[key] or not Path(config[key]).is_dir() for key in required):
            raise ValueError('missing original recognition paths')
        if not (Path(config['client']) / 'v3_core' / 'manifest.json').is_file():
            raise ValueError('missing original recognition manifest')
    except (OSError, TypeError, ValueError, AttributeError) as error:
        raise UserError('原识图运行包配置不完整，请核对原客户端、模型和依赖目录。') from error
    return config


def original_read(operation, content, extension, config, **kwargs):
    suffixes = {'recognition': 'RECOGNITION', 'dimension': 'DIMENSION', 'orientation': 'ORIENTATION'}
    with TemporaryDirectory(prefix='nodo-drawing-', dir=config['workspace']) as folder:
        source = Path(folder) / ('drawing' + extension)
        source.write_bytes(content)
        worker = Path(__file__).with_name(f'original_drawing_{operation}.py')
        try:
            output = subprocess.run(
                [sys.executable, '-B', str(worker)],
                input=json.dumps({**config, 'path': str(source), **kwargs}, ensure_ascii=False),
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=180 if operation == 'recognition' else 55,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            )
            prefix = f'ODOO_{suffixes[operation]}_RESULT='
            line = next(row for row in reversed(output.stdout.splitlines()) if row.startswith(prefix))
            result = json.loads(line[len(prefix):])
            if output.returncode or not isinstance(result, dict):
                raise ValueError('invalid drawing result')
            if result.get('error'):
                raise UserError(str(result['error'])[:400])
            return result
        except (OSError, StopIteration, ValueError, subprocess.SubprocessError) as error:
            raise UserError('原识图组件未返回有效结果，请检查图纸和原运行包。') from error
