import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from uuid import uuid4

from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)
_WORKER = Path(__file__).with_name('original_worker.py')

CABINET_SERIES = [(code, code) for code in (
    'JA', 'JC', 'JE', 'JK', 'JM', 'JP', 'JP WIDE', 'JQ', 'JS', 'JS WIDE', '操作台',
)]
DOORS = {
    'single_panel': ('前单开门后背板', 'SINGLE', 'PANEL', 1, 0),
    'double_panel': ('前双开门后背板', 'DOUBLE', 'PANEL', 0, 1),
    'single_single': ('前后单开门', 'SINGLE', 'SINGLE', 2, 0),
    'single_double': ('前单开门后双开门', 'SINGLE', 'DOUBLE', 1, 1),
    'double_single': ('前双开门后单开门', 'DOUBLE', 'SINGLE', 1, 1),
    'double_double': ('前后双开门', 'DOUBLE', 'DOUBLE', 0, 2),
}
MATERIALS = [('SECC', 'SECC'), ('SUS304', 'SUS304'), ('SUS316', 'SUS316')]
COATINGS = [('orange', '橘纹'), ('gloss', '平光'), ('none', '不喷塑')]
SETTINGS = {
    'carbon_price': 'nodo_carbon_price',
    'galvanized_price': 'nodo_galvanized_price',
    'stainless_304_price': 'nodo_stainless_304_price',
    'stainless_316_price': 'nodo_stainless_316_price',
    'waste_factor': 'nodo_waste_factor',
}


def allowed_doors(series):
    if series in ('JP', 'JP WIDE', 'JS', 'JS WIDE'):
        return tuple(DOORS)
    return tuple(DOORS)[:2] if series in ('JA', 'JE') else ('single_panel',)


def checked_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OriginalPricing:
    def __init__(self, config_path):
        if not config_path:
            raise UserError('未配置原报价服务。选型已保留，请联系管理员配置原计价客户端和服务后重新核算。')
        try:
            config_file = Path(config_path)
            config = json.loads(config_file.read_text(encoding='utf-8-sig'))
            url = urlsplit(config['api_url'])
            self.api_key = config['api_key']
            self.account = config['account']
            rules = Path(config['rules_dir'])
            self.rules = (config_file.parent / rules).resolve()
            if (
                url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment or url.path != '/api/quotes/calculate-dual'
                or not isinstance(self.api_key, str) or not self.api_key.strip()
                or not isinstance(self.account, str) or not self.account.strip()
            ):
                raise ValueError('invalid pricing service configuration')
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise UserError('原报价服务配置无效。请核对计价 HTTPS 地址、本机凭据和原规则目录。') from None
        if any(not (self.rules / name).is_file() for name in (
            'scheme2_ui.py', 'attachment_v2_client.py', 'freight_state.py',
        )):
            raise UserError('原报价客户端缺少计价、附件或运费规则。请补齐对应版本的原规则目录。')
        self.origin = f'{url.scheme}://{url.netloc}'
        self.headers = {'X-AI-Quote-Key': self.api_key, 'Content-Type': 'application/json'}
        self.opener = build_opener(NoRedirect())

    def _request(self, path, payload=None):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        try:
            request = Request(self.origin + path, headers=self.headers, data=body)
            with self.opener.open(request, timeout=75) as response:
                data = json.load(response)
        except HTTPError as exc:
            raise UserError(f'原报价服务返回 HTTP {exc.code}。本次结果未保存。') from None
        except (OSError, ValueError):
            raise UserError('原报价服务连接或响应异常。请检查服务后重新核算。') from None
        if not isinstance(data, dict):
            raise UserError('原报价服务响应不完整。本次结果未保存。')
        return data

    def _worker(self, operation, payload):
        try:
            result = subprocess.run(
                [sys.executable, '-B', str(_WORKER), str(self.rules)],
                input=json.dumps({'operation': operation, **payload}, ensure_ascii=False, allow_nan=False),
                encoding='utf-8', errors='replace', capture_output=True, timeout=35,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'},
            )
            if result.returncode:
                lines = result.stderr.strip().splitlines()
                if lines and lines[-1].startswith('ValueError: '):
                    raise UserError(lines[-1].removeprefix('ValueError: ')[:260])
                raise UserError('原报价规则无法完成计算，请核对客户端版本及依赖。')
            return json.loads(result.stdout)
        except (subprocess.SubprocessError, OSError, ValueError):
            raise UserError('原报价客户端规则运行失败。本次结果未保存。') from None

    def calculate(self, rows, overrides):
        defaults = self._worker('defaults', {})
        settings = {**defaults, **overrides}
        login = self._request('/api/name-login', {'name': self.account})
        if not login.get('token'):
            raise UserError('原报价服务没有为配置的核算账号建立会话。')
        self.headers['Authorization'] = 'Bearer ' + login['token']
        try:
            products = self._request('/api/products/catalog')
            catalog = self._request('/api/attachments/catalog?v=2')
            if catalog.get('status') != 'ACTIVE' or catalog.get('attachment_contract') != 2 or not catalog.get('data_version'):
                raise UserError('原附件价格目录尚未启用或缺少版本。本次结果未保存。')
            plans = [self._plan(row, settings, products, catalog) for row in rows]
            for plan in plans:
                if plan['payload']['attachments']:
                    preview = self._request('/api/attachments/preview', plan['payload'])
                    self._validate_attachments(preview, plan)
            return {plan['line']: self._calculate_plan(plan) for plan in plans}
        finally:
            try:
                self._request('/api/name-logout', {})
            except UserError:
                _logger.warning('NODO Contract could not close the original pricing session.')
            self.headers.pop('Authorization', None)

    def _plan(self, row, settings, products, catalog):
        series = row['series']
        _, front, rear, single, double = DOORS[row['door']]
        variant = 'SINGLE' if single else 'DOUBLE'
        code = {'JC': 'JC_EXP', 'JQ': 'JQ_EXP', 'JP WIDE': 'JP_WIDE_EXP',
                'JS WIDE': 'JS_WIDE_EXP', '操作台': 'OP_TABLE_EXP'}.get(series)
        if not code:
            code = 'JA_SINGLE' if series == 'JA' else f'{series}_{variant}' if series in ('JE', 'JP', 'JS') else series
        if code not in {entry.get('product_code') for entry in products.get('items', [])}:
            raise ValidationError(f'原价格目录没有当前产品及门型：{series}。')
        profile = row['variant'] or ('WIDE' if 'WIDE' in series else variant)
        if series == 'JC' and profile not in ('LUXURY', 'STANDARD') and not re.search(r'-[12]$', row['model']):
            raise ValidationError('JC 需要明确豪华型或标配型型号。')
        material_key = {'SECC': 'carbon_price', 'SUS304': 'stainless_304_price',
                        'SUS316': 'stainless_316_price'}[row['material']]
        child = {
            'quote_id': 'ODOO_' + uuid4().hex, 'product_code': code, 'variant_code': profile,
            'model_code': row['model'], 'material_code': row['material'],
            'width_mm': row['width'], 'height_mm': row['height'], 'depth_mm': row['depth'],
            'single_door_count': single, 'double_door_count': double,
            'door_position': {'front': front, 'rear': rear}, 'cabinet_body_thickness_mm': row['thickness'],
            'quote_date': row['date'], 'pricing_basis': 'per_unit_set_v1', 'attachments': [],
            'waste_factor': float(settings.get('waste_factor', 1.2)),
            'coating_type': dict(COATINGS)[row['coating']],
            'galvanized_sheet_unit_price_override': settings.get('galvanized_price'),
            'carbon_steel_unit_price_override': settings.get('carbon_price'),
            'material_unit_price_override': settings.get(material_key),
            'surface_treatment_unit_price_override': (settings.get('surface_prices') or {}).get(
                row['coating'], settings.get('surface_price'),
            ),
        }
        if row.get('base_height'):
            child['base_height_mm'] = row['base_height']
        payload = {**child, 'attachment_contract': 2, 'attachment_material_price_contract': 1,
                   'ganged_cabinet_count': 1}
        match = self._worker('match', {'catalog': catalog, 'allocations': row['attachments'],
                                     'cabinets': [child], 'environment': payload})
        if len(match['selected']) > 100:
            raise ValidationError('一行最多计价 100 项附件。')
        payload['attachments'] = match['selected']
        item = {
            **payload, 'name': row['name'], 'specification': row['specification'],
            'quantity': int(row['quantity']), 'quick_discount': row['coefficient'],
            'freight_mode': row['freight_mode'], 'freight_fee': row['freight'],
            'quick_freight_basis': 'separate_unit_freight_v1',
            'quick_freight_mode': row['quote_freight_mode'], 'scheme2_cost_settings': settings,
        }
        if row['quote_freight_mode'] == 'MANUAL':
            item['quick_freight_fee'] = row['quote_freight']
        remark = row['remark'] if row['manual_remark'] else self._original_remark(row, payload)
        return {'line': row['line'], 'payload': payload, 'item': item, 'matched': match['matched'], 'remark': remark,
                'catalog_version': catalog['data_version'], 'matcher_sha256': match['source_sha256']}

    def _original_remark(self, row, payload):
        if not (self.rules / 'quote_configuration_remark.py').is_file():
            raise UserError('原报价备注模板未配置。请补齐原客户端备注规则，或回选型填写人工备注。')
        picked = list(dict.fromkeys(entry['name'] for entry in row['attachments'] if entry['selected']))
        item = {
            'product_family': row['series'], 'material_code': row['material'],
            'scheme2_selected_material': '碳钢板' if row['material'] == 'SECC' else row['material'],
            'coating_type': row['coating'], 'display_color': row['color'],
            'cabinet_body_thickness_mm': row['thickness'],
            'quote_configuration': {'component_list': picked},
            **{name: payload[name] for name in ('single_door_count', 'double_door_count', 'door_position')},
        }
        return self._worker('remark', {'item': item})['remark']

    def _calculate_plan(self, plan):
        response = self._request('/api/quotes/calculate-dual', plan['payload'])
        self._validate_attachments(response, plan)
        if not response.get('quote_line_id') or response.get('quote_id') != plan['payload']['quote_id']:
            raise ValidationError('原服务未返回对应的计价快照。本次金额未保存。')
        for section, names in (('formula_cost', ('material_cost', 'auxiliary_cost', 'labor_cost', 'spray_cost', 'total_cost')),
                               ('quick_quote', ('base_price', 'total_cost'))):
            for name in names:
                value = (response.get(section) or {}).get(name)
                if not checked_number(value) or value < 0:
                    raise ValidationError('原价格库未命中完整计价规则。本次金额未保存。')
        resolved = []
        for flag in response.get('risk_flags') or []:
            if not (flag.get('blocking') or flag.get('severity') in ('blocker', 'error')):
                continue
            if flag.get('code') != 'formula_material_cost_missing' or not _verified_material(response, plan['payload']):
                raise ValidationError('原服务标记为不可报价：' + str(flag.get('message') or flag.get('code') or '缺少完整规则')[:180])
            resolved.append({'code': flag['code'], 'material_version': response['formula_cost']['cabinet_material_version']})
        finished = self._worker('finish', {'item': plan['item'], 'response': response, 'matched': plan['matched']})
        price = finished.get('price_unit')
        if not checked_number(price) or price <= 0 or not finished.get('item', {}).get('quote_cost_display'):
            raise ValidationError('原客户端未返回完整有效的报价。本次金额未保存。')
        return {**finished, 'remark': plan['remark'],
                'catalog_version': plan['catalog_version'], 'matcher_sha256': plan['matcher_sha256'],
                'request': plan['payload'], 'response': response, 'resolved_risks': resolved}

    @staticmethod
    def _validate_attachments(response, plan):
        attachments = response.get('attachments') or []
        if len(attachments) != len(plan['matched']):
            raise ValidationError('原服务返回的附件数量不一致。')
        for attachment in attachments:
            if attachment.get('status') in ('ERROR', 'PENDING_MANUAL') or attachment.get('pending_manual_dimensions'):
                dimensions = '、'.join(p['name'] for p in attachment.get('required_parameters', [])
                                      if p.get('source') == 'MANUAL' and p.get('name'))
                raise ValidationError(f"请补齐附件实际尺寸：{attachment.get('item_name') or ''} {dimensions}".strip())
            if attachment.get('catalog_version') != plan['catalog_version']:
                raise ValidationError('附件目录版本已变化，请重新核算。')
            if not checked_number(attachment.get('quick_amount')) or (
                attachment.get('status') != 'QUICK_ONLY' and not checked_number(attachment.get('formula_amount'))
            ):
                raise ValidationError('原服务返回的附件计价不完整。')


def _verified_material(response, submitted):
    formula = response.get('formula_cost') or {}
    parts = formula.get('cabinet_material_part_details') or []
    if formula.get('cabinet_material_method') != 'AREA_FORMULA' or not formula.get('cabinet_material_version') or not parts:
        return False
    total, weight = Decimal(0), Decimal(0)
    for part in parts:
        material = part.get('material_code')
        if material != (part.get('fixed_material_code') or submitted['material_code']):
            return False
        key = {'SGCC': 'galvanized_sheet_unit_price_override', 'SECC': 'carbon_steel_unit_price_override'}.get(
            material, 'material_unit_price_override',
        )
        numbers = [part.get(name) for name in (
            'material_unit_price', 'billable_weight_kg', 'material_cost', 'area_m2', 'internal_quantity',
            'density_g_cm3', 'net_weight_kg', 'sheet_thickness_mm', 'waste_factor',
        )] + [submitted.get(key)]
        if not all(checked_number(value) for value in numbers):
            return False
        price, billable, cost, area, qty, density, net, thickness, waste, entered = numbers
        if (not part.get('rule_id') or not part.get('source_sheet')
                or min(area, qty, billable, cost, net) < 0 or min(price, density, thickness, waste) <= 0
                or abs(price - entered) > 1e-8 or abs(waste - submitted['waste_factor']) > 1e-8
                or abs(cost - price * billable) > 1e-5 or abs(net - area * thickness * qty * density) > 1e-5
                or abs(billable - net * waste) > 1e-5):
            return False
        total += Decimal(str(cost))
        weight += Decimal(str(billable))
    reported_weight = formula.get('corrected_material_weight_kg')
    return checked_number(reported_weight) and abs(float(weight) - reported_weight) < 1e-7 and (
        total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        == Decimal(str(formula['material_cost'])).quantize(Decimal('.01'))
    )
