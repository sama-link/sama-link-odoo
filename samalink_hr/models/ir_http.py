# -*- coding: utf-8 -*-
"""One-shot DB fix when module upgrade queue does not run (orphan custody views)."""

import logging

from odoo import models

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        registry = self.env.registry
        if getattr(registry, '_samalink_hr_custody_views_checked', False):
            return info
        registry._samalink_hr_custody_views_checked = True
        try:
            from odoo.addons.samalink_hr.hooks import _samalink_deactivate_orphan_custody_employee_views

            _samalink_deactivate_orphan_custody_employee_views(self.env)
        except Exception:
            _logger.exception('samalink_hr: failed to deactivate orphan custody employee views')
        return info
