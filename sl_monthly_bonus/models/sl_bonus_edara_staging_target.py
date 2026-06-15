import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

from .sl_bonus_edara_staging import _parse_proxy_date, _parse_proxy_dt

_logger = logging.getLogger(__name__)


class SlBonusEdaraStagingTarget(models.Model):
    """RAW staging for sales targets imported from Edara.

    Authority pattern (HARD invariant): proxy sales targets are raw data only and
    NEVER affect calculation directly. HR reviews and PROMOTES them into the
    authoritative ``sl.bonus.target`` (the only model the calculator reads via
    ``find_for``). This staging model is never consulted by the calculator.
    """
    _name = 'sl.bonus.edara.staging.target'
    _description = 'Edara Staging — Sales Targets (raw)'
    _order = 'period_start desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    edara_row_uid = fields.Char(string='Edara Row UID', index=True, copy=False)
    period_start = fields.Date(string='Month', required=True)
    edara_employee_id = fields.Char(string='Edara Employee ID')
    employee_code = fields.Char(string='Employee Code')
    employee_id = fields.Many2one('hr.employee', string='Resolved Employee')
    target_amount = fields.Monetary(string='Target Amount', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    target_type = fields.Char(string='Target Type')
    branch_code = fields.Char(string='Branch Code')
    source_report = fields.Char(string='Source Report')
    last_updated_at = fields.Datetime(string='Edara Last Updated')
    sync_id = fields.Many2one('sl.bonus.edara.sync', string='Sync Run', ondelete='set null')
    mapping_status = fields.Selection([
        ('mapped', 'Mapped'),
        ('unmapped', 'Unmapped'),
    ], string='Mapping Status', default='mapped', index=True)
    mapping_reason = fields.Char(string='Mapping Note')
    promoted = fields.Boolean(string='Promoted', default=False, readonly=True)
    promoted_target_id = fields.Many2one(
        'sl.bonus.target', string='Authoritative Target', readonly=True, ondelete='set null',
    )

    _sql_constraints = [
        ('uniq_edara_row_uid_target',
         'unique(edara_row_uid)',
         'This Edara target row UID already exists (idempotency guard).'),
    ]

    @api.depends('employee_code', 'edara_employee_id', 'period_start', 'target_amount')
    def _compute_name(self):
        for rec in self:
            who = rec.employee_id.name or rec.employee_code or rec.edara_employee_id or _('Target')
            period = rec.period_start and rec.period_start.strftime('%Y-%m') or ''
            rec.name = f"{who} — {period} — {rec.target_amount or 0.0:.2f}"

    # ── Proxy ingestion ────────────────────────────────────────────────
    @api.model
    def _ingest_proxy_rows(self, rows, sync, dry_run=False):
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        received = len(rows or [])
        created = updated = unmapped = 0
        for row in (rows or []):
            uid = str(row.get('edara_row_uid') or '').strip()
            if not uid:
                # Targets are aggregate; derive a deterministic uid when absent.
                emp = row.get('edara_employee_id') or row.get('employee_code') or '?'
                period = row.get('period') or row.get('period_start') or ''
                uid = f"target:{emp}:{period}"
            edara_emp = str(row.get('edara_employee_id') or row.get('employee_code') or '') or False
            emp_rec = Mapping.resolve_employee(edara_emp, 'sales') if edara_emp else self.env['hr.employee']
            vals = {
                'edara_row_uid': uid,
                'period_start': _parse_proxy_date(row.get('period') or row.get('period_start'))
                or (sync.period_from if sync else False),
                'edara_employee_id': str(row.get('edara_employee_id') or '') or False,
                'employee_code': row.get('employee_code') or False,
                'employee_id': emp_rec.id if emp_rec else False,
                'target_amount': float(row.get('target_amount') or 0.0),
                'target_type': row.get('target_type') or False,
                'branch_code': row.get('branch_code') or False,
                'source_report': row.get('source_report') or False,
                'last_updated_at': _parse_proxy_dt(row.get('last_updated_at')),
                'sync_id': sync.id if sync else False,
                'mapping_status': 'mapped' if emp_rec else 'unmapped',
                'mapping_reason': False if emp_rec else _(
                    "No Edara mapping for external id '%s' (role: sales).") % (edara_emp or '?'),
            }
            if not emp_rec:
                unmapped += 1
            if dry_run:
                continue
            existing = self.sudo().search([('edara_row_uid', '=', uid)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
            else:
                self.sudo().create(vals)
                created += 1
        return {
            'received': received, 'created': created, 'updated': updated,
            'skipped': 0, 'unmapped': unmapped,
        }

    # ── HR promotion → authoritative sl.bonus.target ───────────────────
    def action_promote_to_target(self):
        """HR action: create/update authoritative sl.bonus.target from staging.

        Only rows with a resolved employee + a period are promoted. Tiers are
        left to HR configuration. Existing targets are upserted by
        (employee, month). Returns a notification.
        """
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only HR Manager / Admin can promote sales targets."))
        Target = self.env['sl.bonus.target'].sudo()
        records = self or self.search([('promoted', '=', False)])
        promoted = skipped = 0
        for rec in records:
            if not rec.employee_id or not rec.period_start:
                skipped += 1
                continue
            # One target per employee (valid for all time): upsert by employee.
            existing = Target.search([
                ('employee_id', '=', rec.employee_id.id),
            ], limit=1)
            if existing:
                existing.write({'target_amount': rec.target_amount})
                target = existing
            else:
                target = Target.create({
                    'employee_id': rec.employee_id.id,
                    'period_start': rec.period_start,
                    'target_amount': rec.target_amount,
                })
            rec.write({'promoted': True, 'promoted_target_id': target.id})
            promoted += 1
            self.env['sl.bonus.audit.log'].sudo().log_change(
                model='sl.bonus.target', res_id=target.id,
                action='promote_target_from_edara',
                old_value='', new_value=str(rec.target_amount),
                reason=_('Promoted from Edara staging target #%s') % rec.id,
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sales Targets Promoted'),
                'message': _('%(p)s promoted, %(s)s skipped (no resolved employee/period).')
                % {'p': promoted, 's': skipped},
                'type': 'success' if promoted else 'warning',
                'sticky': False,
            },
        }
