# -*- coding: utf-8 -*-
"""Backfill ir.attachment res_model/res_id for existing hr.incentive rows."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info('hr_incentives 1.0.1: normalizing legacy incentive attachments')

    incentives = env['hr.incentive'].sudo().search([])
    if incentives:
        incentives._normalize_incentive_attachment_metadata()
        _logger.info('Normalized attachments for %s hr.incentive records', len(incentives))

    _logger.info('hr_incentives 1.0.1 migration done')
