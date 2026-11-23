"""AE reference BOM from the JA1/JA2 and JE1/JE2 workbook formulas."""

RULE_VERSION = 'AE-AUX-01'
RULE_SOURCE = '原 JA／JE 辅材表'

HINGE = '30209000001'
SEAL = '30215000004'
RING = '30315000020'
LOCKS = {
    'MS813': ('30102000002',),
    'MS821': ('30104000002', '30199000155', '30199000156'),
}
# The legacy hinge price belongs to 30209000001. The drawn hinge tube has a separate code.
ITEMS = {
    HINGE: ('AE 箱铰链配件', 'piece', True),
    SEAL: ('AE 箱双门密封胶', 'piece', False),
    RING: ('吊环', 'piece', True),
    '30102000002': ('MS813 小方锁', 'piece', True),
    '30104000002': ('MS821 大锁', 'piece', True),
    '30199000155': ('配套锁杆（155）', 'piece', False),
    '30199000156': ('配套锁杆（156）', 'piece', False),
}
MATERIAL_VARIANTS = {'cold_rolled': 'steel', 'galvanized': 'steel', 'stainless': 'stainless'}


def default_lock(height):
    if height is None:
        return ''
    return 'MS821' if height > 800 else 'MS813'


def standard_rows(kind, height, variant, lock, substituted):
    def row(code, quantity, condition='', source='fixed'):
        name, unit, by_material = ITEMS[code]
        return dict(code=code, name=name, variant=variant if by_material else 'common',
                    unit=unit, quantity=quantity, condition=condition, source=source)

    rows = [row(HINGE, 6 if kind == 'double' else 3)]
    if kind == 'double':
        rows.append(row(SEAL, 2))
    if lock:
        if substituted:
            reason = '技术确认换配'
        else:
            reason = '柜体高 > 800 mm' if lock == 'MS821' else '柜体高 ≤ 800 mm'
        rows.extend(row(code, 1, reason, 'conditional') for code in LOCKS[lock])
    if kind == 'single' and height is not None and height > 1000:
        rows.append(row(RING, 2, '单开门且柜体高 > 1000 mm', 'conditional'))
    return rows
