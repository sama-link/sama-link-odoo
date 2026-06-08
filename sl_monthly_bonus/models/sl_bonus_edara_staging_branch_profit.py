import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

from .sl_bonus_edara_staging import _parse_proxy_date, _parse_proxy_dt

_logger = logging.getLogger(__name__)


class SlBonusEdaraStagingBranchProfit(models.Model):
    """RAW staging for branch profitability imported from Edara.

    Authority pattern (HARD invariant): proxy branch profitability is raw
    operational data only. A Finance action promotes it into
    ``sl.bonus.branch.profit`` in state='draft' (NEVER auto-approved). The
    existing draft→approved gate stays the only path to approved, and the
    calculator's ``find_approved`` (state='approved' only) is unchanged.
    """
    _name = 'sl.bonus.edara.staging.branch.profit'
    _description = 'Edara Staging — Branch Profitability (raw)'
    _order = 'period_start desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    edara_row_uid = fields.Char(string='Edara Row UID', index=True, copy=False)
    period_start = fields.Date(string='Month', required=True)
    branch_code = fields.Char(string='Branch Code')
    branch_name = fields.Char(string='Branch Name')
    work_location_id = fields.Many2one('hr.work.location', string='Resolved Branch')
    revenue = fields.Monetary(string='Revenue', currency_field='currency_id')
    cost = fields.Monetary(string='Cost', currency_field='currency_id')
    profit = fields.Monetary(string='Profit', currency_field='currency_id')
    profitability_factor = fields.Float(string='Profitability Factor')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
    )
    source_report = fields.Char(string='Source Report')
    last_updated_at = fields.Datetime(string='Edara Last Updated')
    sync_id = fields.Many2one('sl.bonus.edara.sync', string='Sync Run', ondelete='set null')
    promoted = fields.Boolean(string='Promoted', default=False, readonly=True)
    promoted_profit_id = fields.Many2one(
        'sl.bonus.branch.profit', string='Draft Branch Profit', readonly=True, ondelete='set null',
    )

    _sql_constraints = [
        ('uniq_edara_row_uid_branch_profit',
         'unique(edara_row_uid)',
         'This Edara branch-profit row UID already exists (idempotency guard).'),
    ]

    @api.depends('branch_name', 'branch_code', 'period_start', 'profitability_factor')
    def _compute_name(self):
        for rec in self:
            who = rec.work_location_id.name or rec.branch_name or rec.branch_code or _('Branch')
            period = rec.period_start and rec.period_start.strftime('%Y-%m') or ''
            rec.name = f"{who} — {period} — {rec.profitability_factor or 0.0:.3f}"

    def _resolve_work_location(self, branch_name, branch_code):
        """Best-effort resolution of an hr.work.location by name (case-insensitive)."""
        Loc = self.env['hr.work.location'].sudo()
        if branch_name:
            loc = Loc.search([('name', '=ilike', branch_name)], limit=1)
            if loc:
                return loc
        if branch_code:
            loc = Loc.search([('name', '=ilike', branch_code)], limit=1)
            if loc:
                return loc
        return Loc.browse()

    # ── Proxy ingestion ────────────────────────────────────────────────
    @api.model
    def _ingest_proxy_rows(self, rows, sync, dry_run=False):
        received = len(rows or [])
        created = updated = 0
        for row in (rows or []):
            uid = str(row.get('edara_row_uid') or '').strip()
            if not uid:
                branch = row.get('branch_code') or row.get('branch_name') or '?'
                period = row.get('period') or row.get('period_start') or ''
                uid = f"branch_profit:{branch}:{period}"
            branch_name = row.get('branch_name') or False
            branch_code = row.get('branch_code') or False
            loc = self._resolve_work_location(branch_name, branch_code)
            vals = {
                'edara_row_uid': uid,
                'period_start': _parse_proxy_date(row.get('period') or row.get('period_start'))
                or (sync.period_from if sync else False),
                'branch_code': branch_code,
                'branch_name': branch_name,
                'work_location_id': loc.id if loc else False,
                'revenue': float(row.get('revenue') or 0.0),
                'cost': float(row.get('cost') or 0.0),
                'profit': float(row.get('profit') or 0.0),
                'profitability_factor': float(row.get('profitability_factor') or 0.0),
                'source_report': row.get('source_report') or False,
                'last_updated_at': _parse_proxy_dt(row.get('last_updated_at')),
                'sync_id': sync.id if sync else False,
            }
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
            'skipped': 0, 'unmapped': 0,
        }

    # ── Finance promotion → DRAFT sl.bonus.branch.profit ───────────────
    def action_promote_to_branch_profit(self):
        """Finance action: create/update DRAFT sl.bonus.branch.profit from staging.

        Upsert by (work_location, month). NEVER auto-approves — the existing
        draft→approved gate remains the only path to approved. Rows without a
        resolved work location are skipped (counted in the notification).
        """
        if not (self.env.user.has_group('sl_monthly_bonus.group_bonus_finance')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or self.env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or self.env.user.has_group('base.group_system')):
            raise UserError(_("Only Finance / HR Manager / Admin can promote branch profitability."))
        BranchProfit = self.env['sl.bonus.branch.profit'].sudo()
        records = self or self.search([('promoted', '=', False)])
        promoted = skipped = 0
        for rec in records:
            if not rec.work_location_id or not rec.period_start:
                skipped += 1
                continue
            month = rec.period_start.replace(day=1)
            existing = BranchProfit.search([
                ('work_location_id', '=', rec.work_location_id.id),
                ('period_start', '=', month),
            ], limit=1)
            if existing:
                # Never touch an already-approved authoritative record.
                if existing.state == 'approved':
                    skipped += 1
                    continue
                existing.write({'factor': rec.profitability_factor})
                draft = existing
            else:
                draft = BranchProfit.create({
                    'work_location_id': rec.work_location_id.id,
                    'period_start': month,
                    'factor': rec.profitability_factor,
                    'state': 'draft',
                })
            rec.write({'promoted': True, 'promoted_profit_id': draft.id})
            promoted += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Branch Profitability Promoted (Draft)'),
                'message': _('%(p)s draft record(s) created/updated, %(s)s skipped '
                             '(no resolved branch / already approved).')
                % {'p': promoted, 's': skipped},
                'type': 'success' if promoted else 'warning',
                'sticky': False,
            },
        }
