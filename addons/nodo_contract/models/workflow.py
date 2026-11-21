from contextlib import contextmanager
from contextvars import ContextVar

from odoo.exceptions import AccessError


SALES = 'nodo_base.group_role_sales'
COSTING = 'nodo_base.group_role_costing'
APPROVAL = 'nodo_base.group_role_approval'
ADMIN = 'base.group_system'
COST_GROUPS = ','.join((COSTING, APPROVAL, ADMIN))
OUTPUT_STAGES = ('approved', 'sent', 'accepted', 'sale')

_internal_change = ContextVar('nodo_contract_internal_change', default=False)


def has_role(env, *roles):
    if env.su:
        return True
    return env.user.has_group(ADMIN) or any(env.user.has_group(role) for role in roles)


def internal_change():
    return _internal_change.get()


@contextmanager
def workflow_change():
    token = _internal_change.set(True)
    try:
        yield
    finally:
        _internal_change.reset(token)


def require_role(env, *roles):
    if not has_role(env, *roles):
        raise AccessError('当前岗位无权执行此报价操作。')
