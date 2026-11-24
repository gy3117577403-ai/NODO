from decimal import Decimal, ROUND_HALF_UP

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.nodo_cost.models.auxiliary_price import UNITS, VARIANTS
from odoo.addons.nodo_draw.models import sheet_settings, specification, standard_drawings

from .. import auxiliary_rules as rules


def rounded_money(amount):
    return amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def money(amount):
    return float(rounded_money(amount))


def parse_draft(draft):
    if not isinstance(draft, dict) or set(draft) != {'items', 'lock'}:
        raise UserError('辅材选择格式无效。')
    items, lock = draft['items'], draft['lock']
    if not isinstance(items, list) or len(items) > 100:
        raise UserError('一台柜体最多可保存 100 项自选辅材。')
    parsed = {}
    try:
        for row in items:
            if not isinstance(row, dict) or set(row) != {'id', 'quantity'}:
                raise ValueError('自选辅材行格式无效。')
            item_id = specification.count(row['id'], '辅材编号', 2147483647)
            if item_id in parsed:
                raise ValueError('同一辅材的增购数量请填在一行。')
            parsed[item_id] = specification.number(row['quantity'], '每台自选用量', .001, 10000)
    except (ValueError, OverflowError) as error:
        raise UserError(str(error)) from error
    if lock is not None:
        if not (isinstance(lock, dict) and set(lock) == {'scheme', 'reason', 'confirm'}
                and isinstance(lock['scheme'], str) and lock['scheme'] in rules.LOCKS
                and isinstance(lock['reason'], str) and len(lock['reason']) <= 240
                and type(lock['confirm']) is bool):
            raise UserError('锁具换配资料格式无效。')
        lock = dict(lock, reason=lock['reason'].strip())
    return parsed, lock


def option_quantity(quantity, unit):
    exact = Decimal(str(quantity))
    return exact == exact.quantize(Decimal('.001' if unit == 'metre' else '1'))


class DrawAuxiliaryCost(models.Model):
    _inherit = 'nodo.draw.design'

    auxiliary_choices = fields.Json(string='已保存的辅材选配', readonly=True, copy=False)
    auxiliary_revision = fields.Integer(string='辅材选配修订号', readonly=True, copy=False)

    def _auxiliary_spec(self, proposed):
        current = self.settings
        materials = sheet_settings.for_design(current)['materials']
        wrap = materials.get('parts', {}).get('wrap') or materials.get('body', {})
        spec = {key: current[key] for key in ('kind', 'width', 'height', 'depth')}
        spec['material'] = wrap.get('category', sheet_settings.MATERIALS['groups']['body'])
        if proposed is not None:
            if not isinstance(proposed, dict) or set(proposed) - spec.keys():
                raise UserError('辅材核算规格格式无效。')
            spec.update(proposed)
        if spec['kind'] not in (None, '', 'single', 'double') or not isinstance(spec['material'], str):
            raise UserError('辅材核算的门型或材质无效。')
        for key in ('width', 'height', 'depth'):
            if spec[key] is not None:
                try:
                    specification.number(spec[key], '柜体尺寸', 1, 10000)
                except (ValueError, OverflowError) as error:
                    raise UserError('柜体尺寸须为 1 至 10000 mm。') from error
        return spec

    def _auxiliary_calculation(self, proposed, draft):
        spec = self._auxiliary_spec(proposed)
        kind, height = spec['kind'], spec['height']
        variant = rules.MATERIAL_VARIANTS.get(spec['material'])
        profile = standard_drawings.sheet_profile(self.bom, kind)
        saved = self.auxiliary_choices or {'items': [], 'lock': None}
        picked, requested_lock = parse_draft(draft) if draft is not None else (
            {row['id']: row['quantity'] for row in saved['items']},
            dict(scheme=saved['lock']['scheme'], reason=saved['lock']['reason'], confirm=False) if saved['lock'] else None,
        )
        lock_context = dict(spec, profile=profile, rule=rules.RULE_VERSION)
        issues = []
        if not profile:
            issues.append('请先确认适用辅材规则的门型和图版。')
        if height is None:
            issues.append('请填写柜体本体高度后核对条件标配。')
        if not variant:
            issues.append('请确认柜体材质规格。')
        auto_lock = rules.default_lock(height)
        selected_lock = auto_lock
        lock_pending = False
        if requested_lock:
            confirmed = saved['lock']
            if requested_lock['confirm'] and requested_lock['reason'] and not issues and all(spec[k] for k in ('width', 'depth')):
                confirmed = dict(scheme=requested_lock['scheme'], reason=requested_lock['reason'], context=lock_context)
            if (confirmed and confirmed['context'] == lock_context
                    and all(confirmed[key] == requested_lock[key] for key in ('scheme', 'reason'))):
                selected_lock = requested_lock['scheme']
            else:
                lock_pending = True
                issues.append('锁具换配待确认。请补齐柜体尺寸和换配依据后确认，或恢复按柜高选取。')
        standard = rules.standard_rows(kind, height, variant, selected_lock, bool(requested_lock and not lock_pending)) if profile else []
        expected = {row['code']: row for row in standard}
        book = self.env['nodo.cost.auxiliary.price']
        rates = book.with_context(active_test=False).search([
            ('company_id', '=', self.company_id.id), '|', ('active', '=', True), ('id', 'in', list(picked)),
        ])
        by_key = {(rate.code, rate.variant): rate for rate in rates if rate.active}
        by_id = {rate.id: rate for rate in rates}
        unit_labels, variant_labels = dict(UNITS), dict(VARIANTS)
        subtotal = Decimal(0)
        missing = 0
        reference_count = 0

        def priced(row, rate, issue=''):
            nonlocal subtotal, missing, reference_count
            if not issue and (not rate or not rate.active or not rate.price_per_unit):
                issue = '待补价'
            amount = price = None
            if issue:
                missing += 1
            else:
                price = rate.price_per_unit
                amount = Decimal(str(price)) * Decimal(str(row['quantity']))
                subtotal += amount
                reference_count += rate.basis == 'reference'
            return dict(row, unit_label=unit_labels.get(row['unit'], ''),
                        variant_label=variant_labels.get(row['variant'], ''),
                        issue=issue, price=price, amount=money(amount) if amount is not None else None,
                        basis=rate.basis if amount is not None else '', rate_id=rate.id if rate else None,
                        price_source=(rate.source_note or '') if rate else '',
                        model_status=rate.cad_model_status if rate else '')

        def availability(rate, adding=False):
            if not rate or not rate.active:
                return '物料已归档或当前公司查无此档案'
            if adding and not rate.selectable:
                return '物料未开放自选'
            if rate.scope not in ('any', kind) or rate.variant not in ('common', variant):
                return '当前门型或材质不适用'
            if rate.code in rules.ITEMS:
                item = expected.get(rate.code)
                if not item or rate.variant != item['variant'] or rate.unit != item['unit']:
                    return '与当前标配条件或采购规格不符'
            return ''

        standard_rows = []
        lock_codes = rules.LOCKS.get(selected_lock, ())
        for row in standard:
            rate = by_key.get((row['code'], row['variant']))
            issue = '待核对采购单位' if rate and rate.unit != row['unit'] else ''
            if rate and rate.scope not in ('any', kind):
                issue = '单价档案的适用柜型不符'
            standard_rows.append(priced(dict(row, lock_item=row['code'] in lock_codes), rate, issue))
        standard_amount, standard_missing = subtotal, missing

        prior_lock = rules.default_lock(self.settings['height'])
        lock_change = None
        if not requested_lock and profile and prior_lock and auto_lock and prior_lock != auto_lock:
            lock_change = dict(previous=prior_lock, current=auto_lock, difference=None)
            lock_prices = {}
            for code in (*rules.LOCKS[prior_lock], *rules.LOCKS[auto_lock]):
                _, unit, by_material = rules.ITEMS[code]
                rate = by_key.get((code, variant if by_material else 'common'))
                if rate and rate.unit == unit and rate.scope in ('any', kind) and rate.price_per_unit:
                    lock_prices[code] = Decimal(str(rate.price_per_unit))
            if len(lock_prices) == len(rules.LOCKS[prior_lock]) + len(rules.LOCKS[auto_lock]):
                before = sum(lock_prices[code] for code in rules.LOCKS[prior_lock])
                after = sum(lock_prices[code] for code in rules.LOCKS[auto_lock])
                lock_change['difference'] = money(after - before)

        optional_rows = []
        requested = {}
        for row in self.bom['lines']:
            code = row['code'].strip().upper()
            info = requested.setdefault(code, dict(name=row['name'], quantity=0))
            info['quantity'] += row['quantity']
        for code, row in requested.items():
            standard_item = expected.get(code)
            if standard_item and standard_item['quantity'] == row['quantity']:
                continue
            rate = by_key.get((code, variant)) or by_key.get((code, 'common'))
            issue = '交接数量与标配数量不同' if standard_item else availability(rate) if rate else ''
            if code in rules.ITEMS and not standard_item:
                issue = '交接物料与当前标配条件不符'
            if rate and rate.unit == 'metre':
                issue = '交接给出件数，请补核每台采购长度'
            optional_rows.append(priced(dict(row, code=code, source='handoff',
                                             variant=rate.variant if rate else '', unit=rate.unit if rate else 'piece'), rate, issue))
        for item_id, quantity in picked.items():
            rate = by_id.get(item_id)
            issue = availability(rate, adding=True)
            if rate and not option_quantity(quantity, rate.unit):
                issue = '每台用量须为整数' if rate.unit != 'metre' else '用量最多保留三位小数'
            optional_rows.append(priced(dict(id=item_id, code=rate.code if rate else '',
                                             name=rate.name if rate else '辅材档案缺失',
                                             quantity=quantity, source='manual', variant=rate.variant if rate else '',
                                             unit=rate.unit if rate else ''), rate, issue))
        catalog = [dict(id=rate.id, code=rate.code, name=rate.name, unit=unit_labels[rate.unit],
                        measure=rate.unit, variant=variant_labels[rate.variant],
                        price=rate.price_per_unit or None, basis=rate.basis if rate.price_per_unit else '',
                        model_status=rate.cad_model_status,
                        standard_quantity=expected.get(rate.code, {}).get('quantity', 0))
                   for rate in rates if not availability(rate, adding=True)]
        standard_display = rounded_money(standard_amount)
        optional_display = rounded_money(subtotal - standard_amount)
        displayed_subtotal = rounded_money(subtotal)
        groups = dict(standard=dict(amount=float(standard_display), missing=standard_missing),
                      optional=dict(amount=float(optional_display), missing=missing - standard_missing))
        return dict(rule=rules.RULE_VERSION, rule_source=rules.RULE_SOURCE, height=height, kind=kind,
                    variant=variant_labels.get(variant, ''), revision=self.auxiliary_revision,
                    spec_edit=self.edit_number, standard=standard_rows, optional=optional_rows,
                    catalog=catalog, issues=issues, missing=missing, reference_count=reference_count,
                    groups=groups, known_subtotal=float(displayed_subtotal), exact_subtotal=format(subtotal, 'f'),
                    rounding_difference=float(displayed_subtotal - standard_display - optional_display),
                    total=None if issues or missing else float(displayed_subtotal),
                    saved=dict(items=saved['items'], lock=dict(scheme=saved['lock']['scheme'], reason=saved['lock']['reason'],
                                                               confirm=False) if saved['lock'] else None),
                    auto_lock=auto_lock, selected_lock=selected_lock, lock_pending=lock_pending, lock_change=lock_change,
                    lock_context=lock_context)

    def preview_auxiliary_costs(self, spec=None, draft=None):
        self._check_read()
        result = self._auxiliary_calculation(spec, draft)
        result.pop('lock_context')
        return result

    def save_auxiliary_choices(self, expected, revision, draft):
        self._lock_editor(expected)
        self.invalidate_recordset(['auxiliary_choices', 'auxiliary_revision'])
        if type(revision) is not int or revision != self.auxiliary_revision:
            raise UserError('另一窗口已修改辅材选配，请重新载入后核对。')
        picked, lock = parse_draft(draft)
        result = self._auxiliary_calculation(None, draft)
        existing = self.auxiliary_choices or {'items': [], 'lock': None}
        previous_qty = {row['id']: row['quantity'] for row in existing['items']}
        for row in result['optional']:
            if row['source'] == 'manual' and row['issue'] not in ('', '待补价') and previous_qty.get(row['id']) != row['quantity']:
                raise UserError(f"{row['name']} · {row['issue']}。")
        if lock and lock['confirm']:
            if result['lock_pending']:
                raise UserError('请补齐柜体尺寸和锁具换配依据后重新确认。')
            confirmed = dict(scheme=lock['scheme'], reason=lock['reason'], context=result['lock_context'],
                             confirmed_by=self.env.uid, confirmed_at=fields.Datetime.to_string(fields.Datetime.now()))
        elif lock:
            confirmed = existing['lock']
            if not confirmed or any(confirmed[key] != lock[key] for key in ('scheme', 'reason')):
                raise UserError('换配锁具组合需由技术确认并填写依据。')
        else:
            confirmed = None
        selected = dict(items=[dict(id=item_id, quantity=qty) for item_id, qty in sorted(picked.items())], lock=confirmed)
        if selected != existing:
            self.sudo().write(dict(auxiliary_choices=selected, auxiliary_revision=self.auxiliary_revision + 1))
        return self.preview_auxiliary_costs()
