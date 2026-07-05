import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class IrRule(models.Model):
    _inherit = 'ir.rule'

    # Core is @api.model + ormcached on (uid, su, model_name, mode, company
    # context). This wrapper is deliberately NOT re-cached: its only extra
    # cost is one cached has_group() per call, and super() keeps its cache.
    @api.model
    def _compute_domain(self, model_name, mode='read'):
        if (
            mode == 'read'
            and not self.env.su
            and self.env.uid
            and self.env['ir.model.access']._sl_is_reviewer()
        ):
            # [] is the core contract for "no restriction": bypasses all
            # global rules (multi-company included) and group rules; the
            # _inherits parent recursion lands in this override again.
            return []
        return super()._compute_domain(model_name, mode)
