# -*- coding: utf-8 -*-
"""Backfill ir.attachment res_model/res_id for existing HR document rows.

post_init_hook runs on install only; this runs when upgrading to 18.0.1.0.1+.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info('oh_employee_documents_expiry 18.0.1.0.1: normalizing legacy attachments')

    docs = env['hr.employee.document'].sudo().search([])
    if docs:
        docs._normalize_attachment_access_metadata()
        _logger.info('Normalized attachments for %s hr.employee.document records', len(docs))

    templates = env['hr.document'].sudo().search([])
    if templates:
        templates._normalize_attachment_access_metadata()
        _logger.info('Normalized attachments for %s hr.document records', len(templates))

    _logger.info('oh_employee_documents_expiry 18.0.1.0.1 migration done')
