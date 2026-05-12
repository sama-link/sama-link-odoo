# -*- coding: utf-8 -*-
from odoo import models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _hr_incentive_is_incentive_attachment(self):
        """True if file is linked to hr.incentive (res_model or M2M rel table)."""
        self.ensure_one()
        if self.res_model == 'hr.incentive':
            return True
        self.env.cr.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM hr_incentive_ir_attachments_rel r
                WHERE r.attachment_id = %s
            )
            """,
            (self.id,),
        )
        row = self.env.cr.fetchone()
        return bool(row and row[0])

    def _hr_incentive_can_bypass_attachment_check(self, user):
        return any([
            user.has_group('hr_incentives.group_hr_incentives_officer'),
            user.has_group('hr_incentives.group_hr_incentives_manager'),
            user.has_group('hr.group_hr_user'),
            user.has_group('hr.group_hr_manager'),
            user.has_group('samalink_security_groups.group_samalink_hr_officer'),
            user.has_group('samalink_security_groups.group_samalink_administrator'),
            user.has_group('samalink_security_groups.group_sl_general_manager'),
            user.has_group('samalink_security_groups.group_sl_coach_manager'),
        ])

    def check(self, mode, values=None):
        """Allow HR / incentive roles to read incentive attachments (not creator-only)."""
        if not self:
            return super().check(mode, values)
        user = self.env.user
        if not self._hr_incentive_can_bypass_attachment_check(user):
            return super().check(mode, values)
        incentive_linked = self.filtered(
            lambda att: att._hr_incentive_is_incentive_attachment()
        )
        other = self - incentive_linked
        if not other:
            return
        return super(IrAttachment, other).check(mode, values)
