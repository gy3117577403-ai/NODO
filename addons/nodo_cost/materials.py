from odoo.addons.nodo_base.sheet_materials import MATERIALS

CATEGORIES = [(key, detail['name']) for key, detail in MATERIALS['categories'].items()]


def stock_key(category, grade, condition, thickness):
    return category, (grade or '').strip().lower(), (condition or '').strip().lower(), thickness
