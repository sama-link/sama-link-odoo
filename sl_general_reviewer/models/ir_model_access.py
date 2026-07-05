import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)

REVIEWER_GROUP = 'sl_general_reviewer.group_general_reviewer_manager'


class IrModelAccess(models.Model):
    _inherit = 'ir.model.access'

    def _sl_is_reviewer(self):
        """True when the current uid belongs to the General Reviewer Manager
        group. Safe in uid-less envs and for public/portal users; has_group
        is ormcache-backed in 18, so this is cheap and does not recurse into
        ACL checks. Returns False while the group doesn't exist yet
        (mid-install)."""
        if not self.env.uid:
            return False
        return self.env.user.has_group(REVIEWER_GROUP)

    # Same cache key as the core method (@tools.ormcache('self.env.uid',
    # 'mode') in odoo/addons/base/models/ir_model.py). Re-decorating keeps
    # the per-call cost at a cache lookup instead of rebuilding the union on
    # every check(). Invalidation matches core: ACL/rule/group/user changes
    # and registry reloads all call env.registry.clear_cache().
    #
    # No self.env.su branch here: 'su' is not part of the cache key, so
    # branching on it would poison the (uid, mode) entry; superuser envs
    # bypass ACLs in check() before this set is ever consulted.
    @tools.ormcache('self.env.uid', 'mode')
    def _get_allowed_models(self, mode='read'):
        allowed = super()._get_allowed_models(mode)
        if mode == 'read' and self._sl_is_reviewer():
            return allowed | set(self.env.registry.models)
        return allowed
