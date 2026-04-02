from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)


class SurveyUserInput(models.Model):
    """Extend survey.user_input to post notifications on appraisal
    when a survey response is submitted."""
    _inherit = 'survey.user_input'

    def write(self, vals):
        """When survey state changes to 'done', notify the appraisal."""
        res = super().write(vals)
        if vals.get('state') == 'done':
            for record in self:
                if record.appraisal_id:
                    try:
                        record.appraisal_id.message_post(
                            body=f"✅ Survey response completed by "
                                 f"<b>{record.partner_id.name or record.email or 'Anonymous'}</b>.",
                            message_type='comment',
                            subtype_xmlid='mail.mt_note',
                        )
                    except Exception as e:
                        _logger.warning(
                            "Could not post survey completion message "
                            "on appraisal %s: %s",
                            record.appraisal_id.id, e)
        return res
