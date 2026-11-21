# 京能 c3c1209 的自定义计价适配。公式和附件规则从配置的原报价客户端加载。
import ast, builtins, copy, hashlib, importlib, json, math, symtable, sys
from pathlib import Path
sys.dont_write_bytecode = True
source = Path(sys.argv[1])
sys.path.insert(0, str(source))
data = json.load(sys.stdin)

class OriginalFunctions:
    # Reuse only requested non-UI functions from the mixed client modules.
    # No Qt import, application construction, or replacement pricing formula.
    def __init__(self, name):
        self.path = source / (name + '.py')
        self.text = self.path.read_text(encoding='utf-8-sig')
        self.nodes = {}
        self.prior = {}
        self.ns = {'__name__': 'odoo_quote_original_functions', '__builtins__': builtins.__dict__}
        body = ast.parse(self.text).body
        nodes = [child for node in body for child in (node.body if isinstance(node, ast.Try) else [node])]
        for node in nodes:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)]
            elif isinstance(node, ast.ImportFrom):
                names = [n.asname or n.name for n in node.names]
            elif isinstance(node, ast.Import):
                names = [n.asname or n.name.split('.')[0] for n in node.names]
            for key in names:
                if key in self.nodes:
                    self.prior[key] = self.nodes[key]
                self.nodes[key] = node
        self.loading = set()
    def get(self, name):
        if name in self.ns:
            return self.ns[name]
        if hasattr(builtins, name):
            return getattr(builtins, name)
        if name in self.loading:
            return None
        node = self.nodes.get(name)
        if node is None:
            raise ValueError('原规则依赖缺失：' + name)
        if isinstance(node, ast.ClassDef):
            raise ValueError('计价路径不允许加载界面类：' + name)
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith(('PySide6', 'shiboken6')):
            raise ValueError('计价路径不允许加载界面依赖')
        if isinstance(node, ast.Assign) and name in self.prior and any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == name for n in ast.walk(node.value)):
            self.nodes[name] = self.prior[name]
            self.get(name)
            self.nodes[name] = node
        self.loading.add(name)
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            table = symtable.symtable(ast.unparse(node), str(self.path), 'exec')
            deps = set()
            def visit(table):
                for symbol in table.get_symbols():
                    if symbol.is_referenced() and symbol.is_global():
                        deps.add(symbol.get_name())
                for child in table.get_children():
                    visit(child)
            visit(table)
            for dependency in deps - {name}:
                if dependency not in self.ns and not hasattr(builtins, dependency):
                    self.get(dependency)
        unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
        ast.fix_missing_locations(unit)
        exec(compile(unit, str(self.path), 'exec'), self.ns)
        self.loading.remove(name)
        return self.ns[name]

operation = data['operation']
if operation == 'defaults':
    original = OriginalFunctions('scheme2_ui')
    document = ast.parse(original.text)
    definition = next(node for node in ast.walk(document) if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Attribute) and target.attr == 'scheme2_defaults' for target in node.targets))
    if not isinstance(definition.value, ast.Dict):
        raise ValueError('原程序默认计价参数结构已变化，请核对版本')
    names = {node.id for node in ast.walk(definition.value) if isinstance(node, ast.Name)}
    for name in names:
        original.get(name)
    output = eval(compile(ast.Expression(body=definition.value), str(original.path), 'eval'), original.ns)
    surfaces = original.get('SURFACE_DEFAULT_PRICES')
    output['surface_prices'] = {key: surfaces[label] for key, label in [('orange', '橘纹'), ('gloss', '平光'), ('none', '无')]}
elif operation == 'match':
    original = OriginalFunctions('attachment_v2_client')
    match = original.get('match_catalog_attachment')
    selected_input = original.get('selected_input')
    selected, explanations = [], []
    for allocation in data['allocations']:
        if not allocation.get('selected', True):
            continue
        index = allocation.get('cabinet_index')
        if allocation.get('scope') == 'cabinet':
            if type(index) is not int or index < 0 or index >= len(data['cabinets']):
                raise ValueError('附件柜位无效：' + allocation['name'])
            target = data['cabinets'][index]
        else:
            target = data['environment']
        family = target['product_code'].split('_')[0]
        box_products = OriginalFunctions('scheme2_ui').get('CONTROL_BOX_ATTACHMENT_PRODUCTS')
        choices = [row for row in data['catalog']['items'] if row['item_name'] == allocation['name']
                   and not (row.get('category_level1') == '控制箱附件' and family not in box_products)
                   and not (row.get('category_level1') == '控制柜附件' and family not in {'JS', 'JP', 'JM'})]
        categories = {row.get('category_level1', '') for row in choices}
        if len(categories) > 1 and not allocation.get('category_level1'):
            raise ValueError('附件有多个适用分类，请明确分类后计价：' + allocation['name'])
        selection = {'item_name': allocation['name'], 'category_level1': allocation.get('category_level1') or (next(iter(categories)) if len(categories) == 1 else ''),
                     'quantity': allocation['quantity'], 'attachment_price_sign': 1,
                     'manual_inputs': allocation.get('manual_inputs') or {}}
        if allocation.get('model_code'):
            selection['model_code'] = allocation['model_code']
        dimensions = tuple(target[key] for key in ('width_mm', 'height_mm', 'depth_mm'))
        found = match(selection, data['catalog']['items'], dimensions, target['product_code'],
                      target.get('base_height_mm'), target['material_code'])
        if not found:
            raise ValueError('附件未匹配到唯一有效规格，请完善规格/型号：' + allocation['name'])
        if original.get('installation_board')(selection) or original.get('is_base_attachment')(selection):
            resolved = original.get('resolve_installation_board')(selection, found, data['catalog']['data_version'])
        elif original.get('size_match_attachment_name')(selection):
            resolved = original.get('resolve_size_matched_attachment')(selection, found, data['catalog']['data_version'])
        else:
            resolved = {**found, **selection, 'catalog_version': data['catalog']['data_version']}
        if allocation.get('scope') == 'cabinet' and len(data['cabinets']) > 1:
            resolved['ganged_cabinet_index'] = index
        selected.append(selected_input(resolved, target.get('base_height_mm')))
        explanations.append(resolved)
    output = {'selected': selected, 'matched': explanations}
elif operation == 'finish':
    original = OriginalFunctions('scheme2_ui')
    item = data['item']
    response = data['response']
    item.update(formula=copy.deepcopy(response['formula_cost']), quick=copy.deepcopy(response['quick_quote']),
                attachments=copy.deepcopy(response.get('attachments') or []),
                quote_line_id=response.get('quote_line_id'), attachment_contract=2,
                manufacturing_cost_basis='quoted_unit_4pct_v1', tax_cost_basis='quoted_less_display_costs_15pct_v1',
                gross_margin_basis='production_plus_cost_freight_v1')
    # The server owns formula prices. Only validated size-generated sale overrides
    # from the original matcher are merged, using the original client function.
    matcher = OriginalFunctions('attachment_v2_client')
    if len(item['attachments']) != len(data['matched']):
        raise ValueError('附件计算结果数量与选择不一致')
    remaining = list(item['attachments'])
    merged = []
    for selected in data['matched']:
        costs = [row for row in remaining if row.get('attachment_price_id') == selected.get('attachment_price_id')
                 and row.get('ganged_cabinet_index') == selected.get('ganged_cabinet_index')
                 and float(row.get('quantity', 1)) == float(selected.get('quantity', 1))]
        if not costs:
            raise ValueError('附件结果与匹配规格不一致：' + str(selected.get('item_name', '')))
        cost = costs[0]
        remaining.remove(cost)
        merged.append(matcher.get('merge_cost')(selected, cost))
    item['attachments'] = merged
    if item.get('freight_mode') == 'AUTO':
        import freight_state
        item['freight_basis'] = freight_state.AUTO_FREIGHT_BASIS
        freight_state.sync_item_freight(item)
    original.get('_recalculate_item_management')(item)
    if item['formula'].get('tax_cost_error') or item['formula'].get('total_cost') is None:
        raise ValueError(item['formula'].get('tax_cost_error') or '成本结果不完整')
    values = original.get('_row_values')(item)
    headings = original.get('HEADERS')
    order = original.get('COST_DISPLAY_ORDER')
    money_columns = original.get('MONEY_COLUMNS')
    frozen = {heading: (original.get('_money')(values[order[column]]) if column in money_columns else str(values[order[column]]))
              for column, heading in enumerate(headings)}
    item['quote_cost_display'] = {'schema': 1, 'values': frozen,
                                 'price_breakdown': original.get('_cost_price_components')(item)}
    item['quote_display'] = {'unit_price': values[15], 'total': values[16], 'quantity': item['quantity']}
    output = {'item': item, 'price_unit': values[15], 'line_total': values[16]}
elif operation == 'remark':
    from quote_configuration_remark import build_configuration_remark
    output = {'remark': build_configuration_remark(data['item'])}
else:
    raise ValueError('未知计价处理步骤')
if operation != 'remark':
    output['source_sha256'] = hashlib.sha256(original.path.read_bytes()).hexdigest()
print(json.dumps(output, ensure_ascii=False, allow_nan=False))
