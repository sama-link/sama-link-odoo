import logging
from datetime import date
from calendar import monthrange
from babel.dates import format_date
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError

_logger = logging.getLogger(__name__)


def _format_month_localized(value, lang):
    """Return a human-readable month-year string in the user's UI language.

    Used by both ``sl.bonus.batch`` and ``sl.bonus.batch.line`` to surface
    e.g. "أبريل 2026" in an Arabic session and "April 2026" in English.
    Falls back to ``%B %Y`` if babel doesn't recognize the locale.
    """
    if not value:
        return ''
    # Odoo Arabic ships as ar_001; babel knows ar / ar_SA / ar_EG. Strip
    # the geographical refinement and try the base language first.
    locale = (lang or 'en_US').replace('@', '_')
    candidates = [locale, locale.split('_')[0], 'en']
    for loc in candidates:
        try:
            return format_date(value, format='LLLL y', locale=loc)
        except Exception:
            continue
    return value.strftime('%B %Y')


class SlBonusBatch(models.Model):
    """Monthly bonus batch (header). One batch per (company, month)."""
    _name = 'sl.bonus.batch'
    _description = 'Monthly Bonus Batch'
    _order = 'period_start desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        'res.company', required=True,
        default=lambda self: self.env.company,
    )
    period_start = fields.Date(string='Period Start', required=True)
    period_end = fields.Date(string='Period End', required=True)
    period_label = fields.Char(string='Month (YYYY-MM)', compute='_compute_period_label', store=True,
                               help='Technical identifier (YYYY-MM). For display, prefer period_display.')
    # Human-readable month name in the user's UI language. Not stored — the
    # locale comes from request context, so a stored value would be wrong for
    # other users.
    period_display = fields.Char(string='Month', compute='_compute_period_display')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('data_ready', 'Data Ready'),
        ('computed', 'Computed'),
        ('hr_review', 'HR Review'),
        ('approved', 'Approved'),
        ('locked', 'Locked'),
    ], default='draft', tracking=True, copy=False, string='State')
    line_ids = fields.One2many(
        'sl.bonus.batch.line', 'batch_id',
        string='Bonus Lines', copy=False,
    )
    employee_ids = fields.Many2many(
        'hr.employee', 'sl_bonus_batch_employee_rel', 'batch_id', 'employee_id',
        string='Employees',
        help='Optional. If set, Compute generates lines ONLY for these employees '
             '(like appraisal batches). Leave empty to compute for all active '
             'employees in the company.',
    )
    # Reference appraisal batch — when set, ALL evaluation lookups during
    # compute are constrained to this batch's appraisals. Set automatically
    # by ``sl.bonus.add.from.appraisal.wizard``. Editable in draft/data_ready
    # only (the view enforces that with `readonly`).
    appraisal_batch_id = fields.Many2one(
        'hr.appraisal.batch',
        string='Evaluation Batch Reference',
        copy=False, tracking=True,
        help='When set, every employee in this bonus batch must have an '
             'appraisal inside this appraisal batch — the calculator uses '
             'only those appraisals for evaluation %. Employees with no '
             'matching appraisal are excluded with a clear reason. Leave '
             'empty to fall back to the default behavior of using the most '
             'recent finalized appraisal that overlaps the period.',
    )
    line_count = fields.Integer(compute='_compute_counts', store=True)
    total_amount = fields.Monetary(
        string='Total', compute='_compute_counts', store=True,
        currency_field='currency_id',
    )
    excluded_count = fields.Integer(compute='_compute_counts', store=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )
    created_by = fields.Many2one(
        'res.users', readonly=True, default=lambda self: self.env.user,
    )
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_on = fields.Datetime(readonly=True)
    locked_by = fields.Many2one('res.users', readonly=True)
    locked_on = fields.Datetime(readonly=True)
    last_computed_on = fields.Datetime(readonly=True)
    last_computed_by = fields.Many2one('res.users', readonly=True)
    note = fields.Text(string='Note')

    _sql_constraints = [
        ('uniq_company_period',
         'unique(company_id, period_start, period_end)',
         'A bonus batch for this company and period already exists.'),
    ]

    @api.depends('period_start')
    def _compute_period_label(self):
        for rec in self:
            rec.period_label = rec.period_start and rec.period_start.strftime('%Y-%m') or ''

    @api.depends('period_start')
    @api.depends_context('lang')
    def _compute_period_display(self):
        lang = self.env.context.get('lang') or self.env.user.lang or 'en_US'
        for rec in self:
            rec.period_display = _format_month_localized(rec.period_start, lang)

    @api.depends('line_ids', 'line_ids.bonus_amount', 'line_ids.is_excluded')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.total_amount = sum(l.bonus_amount for l in rec.line_ids if not l.is_excluded)
            rec.excluded_count = sum(1 for l in rec.line_ids if l.is_excluded)

    @api.constrains('period_start', 'period_end')
    def _check_period(self):
        for rec in self:
            if rec.period_end < rec.period_start:
                raise ValidationError(_("Period End must be after Period Start."))

    @api.constrains('line_ids')
    def _check_no_duplicate_employee_in_lines(self):
        """Block adding the same employee twice into a single batch.

        This is the in-batch sibling of sl.bonus.batch.line._check_unique_employee_period
        (which guards across batch-owned and independent lines). Catches the
        case where two lines for the same employee are introduced in the same
        write (e.g. via the wizard or the Add-all-employees button).
        """
        for rec in self:
            seen = set()
            for ln in rec.line_ids:
                emp_id = ln.employee_id.id
                if not emp_id:
                    continue
                if emp_id in seen:
                    raise ValidationError(_(
                        "Employee %s appears more than once in batch '%s'. "
                        "Each employee may have only one line per batch."
                    ) % (ln.employee_id.name, rec.name))
                seen.add(emp_id)

    # ── Permission helpers ────────────────────────────────────────────
    def _is_admin(self):
        return self.env.user.has_group('sl_monthly_bonus.group_bonus_admin') \
            or self.env.user.has_group('base.group_system')

    def _is_hr(self):
        return self._is_admin() \
            or self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')

    def _ensure_hr(self):
        if not self._is_hr():
            raise AccessError(_("Only HR Manager / Admin can perform this action."))

    # ── Workflow actions ──────────────────────────────────────────────
    def action_open_for_previous_month(self):
        """Helper button: create / open the batch covering the previous calendar month."""
        self._ensure_hr()
        today = fields.Date.today()
        year = today.year
        month = today.month - 1
        if month == 0:
            month = 12
            year -= 1
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        existing = self.search([
            ('company_id', '=', self.env.company.id),
            ('period_start', '=', start),
            ('period_end', '=', end),
        ], limit=1)
        if existing:
            return existing._return_form_action()
        batch = self.create({
            'name': _('Bonus %s') % start.strftime('%Y-%m'),
            'period_start': start,
            'period_end': end,
        })
        return batch._return_form_action()

    def _return_form_action(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_lines(self):
        """Smart-button: open this batch's bonus lines (replaces the global menu)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bonus Lines'),
            'res_model': 'sl.bonus.batch.line',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def _add_employees_to_lines(self, employees):
        """Core helper — create draft lines for the given employees that are
        not yet in ``line_ids``. Returns the newly-created line records.

        Used by the legacy ``action_add_all_employees`` entry point AND by
        the two new wizards (``sl.bonus.add.employees.wizard`` and
        ``sl.bonus.add.from.appraisal.wizard``). Archived employees are
        accepted — an employee who departed after working the period keeps
        the bonus. Duplicates against existing ``line_ids`` are silently
        skipped (the per-line @api.constrains also guards against this).
        """
        self.ensure_one()
        if self.state not in ('draft', 'data_ready'):
            raise UserError(_(
                "Employees can only be added while the batch is in Draft "
                "or Data Ready."
            ))
        Line = self.env['sl.bonus.batch.line'].sudo()
        existing_ids = set(self.line_ids.mapped('employee_id.id'))
        new_employees = employees.sudo().filtered(
            lambda e: e.id not in existing_ids
        )
        if not new_employees:
            return Line.browse()
        return Line.create([{
            'batch_id': self.id,
            'employee_id': emp.id,
            'state': 'draft',
        } for emp in new_employees])

    def action_add_all_employees(self):
        """Legacy entry point — create a draft line for every active company
        employee not yet in ``line_ids``. The UI now routes this through the
        ``sl.bonus.add.employees.wizard``; this method is kept for
        programmatic callers (tests, scripts, server actions).
        """
        self._ensure_hr()
        for rec in self:
            employees = self.env['hr.employee'].sudo().search([
                ('company_id', 'in', [rec.company_id.id, False]),
                ('active', '=', True),
            ])
            rec._add_employees_to_lines(employees)
        return True

    def action_open_add_employees_wizard(self):
        """Open the Add Employees wizard (UI entry point — replaces the
        direct Add-All-Active-Employees button)."""
        self.ensure_one()
        self._ensure_hr()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Employees'),
            'res_model': 'sl.bonus.add.employees.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
            },
        }

    def action_open_add_from_appraisal_wizard(self):
        """Open the Add From Appraisal Batch wizard — adds every employee
        referenced by an appraisal in the selected appraisal batch."""
        self.ensure_one()
        self._ensure_hr()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add From Appraisal Batch'),
            'res_model': 'sl.bonus.add.from.appraisal.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id,
            },
        }

    def action_mark_data_ready(self):
        self._ensure_hr()
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only Draft batches can be moved to Data Ready."))
            rec.state = 'data_ready'
            rec.line_ids._sync_state_from_batch()

    def action_compute(self):
        self._ensure_hr()
        for rec in self:
            if rec.state not in ('data_ready', 'computed', 'hr_review'):
                raise UserError(_("Compute is allowed only in Data Ready / Computed / HR Review states."))
            rec._compute_lines()
            rec.write({
                'state': 'computed',
                'last_computed_on': fields.Datetime.now(),
                'last_computed_by': self.env.user.id,
            })
            rec.line_ids._sync_state_from_batch()
            rec.message_post(body=_("Bonuses recomputed by %s.") % self.env.user.name)

    def action_send_to_review(self):
        self._ensure_hr()
        for rec in self:
            if rec.state != 'computed':
                raise UserError(_("Only Computed batches can be sent to HR Review."))
            rec.state = 'hr_review'
            rec.line_ids._sync_state_from_batch()

    def action_approve(self):
        self._ensure_hr()
        for rec in self:
            # Phase-1 flow approves directly from 'computed'; 'hr_review' is still
            # accepted for backward compatibility with any existing records.
            if rec.state not in ('computed', 'hr_review'):
                raise UserError(_("Only Computed batches can be Approved."))
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'approved_on': fields.Datetime.now(),
            })
            rec.line_ids._sync_state_from_batch()
            rec.message_post(body=_("Batch approved."))

    def action_lock(self):
        if not self._is_admin():
            raise AccessError(_("Only Admin can lock an approved batch."))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_("Only Approved batches can be Locked."))
            rec.write({
                'state': 'locked',
                'locked_by': self.env.user.id,
                'locked_on': fields.Datetime.now(),
            })
            rec.line_ids._sync_state_from_batch()

    def action_reset_to_draft(self):
        """Move a batch backward to Draft.

        HR Manager / Admin may reset a batch (any state up to Approved). A
        LOCKED batch stays Admin-only — locking is the final administrative seal.
        """
        for rec in self:
            if rec.state == 'locked' and not rec._is_admin():
                raise AccessError(_("Only Admin can reset a LOCKED batch to draft."))
            if not rec._is_hr():
                raise AccessError(_("Only HR Manager / Admin can reset a batch to draft."))
            rec.write({
                'state': 'draft',
                'approved_by': False, 'approved_on': False,
                'locked_by': False, 'locked_on': False,
            })
            rec.line_ids._sync_state_from_batch()

    # ── Export ─────────────────────────────────────────────────────────
    def action_export_xlsx(self):
        """Export this batch's bonus lines to an .xlsx file (one-click download)."""
        self.ensure_one()
        self._ensure_hr()
        import io
        import base64
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' library is required to export to Excel."))
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet('Bonuses')
        bold = wb.add_format({'bold': True})
        money = wb.add_format({'num_format': '#,##0.00'})
        headers = [
            _('Employee'), _('Work Location'), _('Visa No'), _('Job'),
            _('Salary Payment Method'), _('Category'), _('Target'),
            _('Achieved (collected)'), _('Evaluation %'),
            _('Computed'), _('Bonus'), _('Excluded'), _('Reason'),
        ]
        for col, head in enumerate(headers):
            ws.write(0, col, head, bold)

        # Arabic value maps (independent of the export user's UI language).
        category_ar = {
            'service': 'خدمات',
            'sales': 'مبيعات',
            'stock': 'مشتريات المخزون',
            'installation': 'تركيبات',
            'branch_manager': 'مدير فرع / منطقة',
            'none': 'بدون مكافأة',
        }
        payment_ar = {
            'bank_transfer': 'تحويل بنكي',
            'cash': 'نقدي',
            'other': 'أخرى',
        }

        def _payment_method_label(contract):
            method = getattr(contract, 'salary_payment_method', False)
            if not method:
                return ''
            if method in payment_ar:
                return payment_ar[method]
            field = contract._fields.get('salary_payment_method')
            try:
                labels = dict(field.selection)
            except TypeError:  # callable selection
                labels = dict(field._description_selection(self.env))
            return labels.get(method, method)

        row = 1
        for line in self.line_ids.sorted(lambda l: (l.employee_id.name or '')):
            contract = line.employee_id.contract_id
            ws.write(row, 0, line.employee_id.name or '')
            ws.write(row, 1, line.work_location_id.name or '')
            ws.write(row, 2, getattr(line.employee_id, 'visa_no', '') or '')
            ws.write(row, 3, line.job_id.name or '')
            ws.write(row, 4, _payment_method_label(contract))
            ws.write(row, 5, category_ar.get(line.category, line.category or ''))
            # Target / Achieved are meaningful for sales lines only.
            if line.category == 'sales':
                ws.write_number(row, 6, line.target_amount or 0.0, money)
                ws.write_number(row, 7, line.achieved_amount or 0.0, money)
            else:
                ws.write(row, 6, '')
                ws.write(row, 7, '')
            ws.write_number(row, 8, line.evaluation_percent or 0.0)
            ws.write_number(row, 9, line.computed_amount or 0.0, money)
            ws.write_number(row, 10, line.bonus_amount or 0.0, money)
            ws.write(row, 11, _('Yes') if line.is_excluded else _('No'))
            # Reason column carries both the automatic exclusion reason and the
            # reason typed by HR/Admin when they manually adjusted the amount.
            reason_parts = []
            if line.exclusion_reason:
                reason_parts.append(line.exclusion_reason)
            if line.manual_override_reason and line.manual_override_reason.strip():
                reason_parts.append(
                    _("Manual adjustment: %s") % line.manual_override_reason.strip()
                )
            ws.write(row, 12, ' | '.join(reason_parts))
            row += 1
        # Total row (non-excluded bonus).
        ws.write(row + 1, 9, _('Total'), bold)
        ws.write_number(row + 1, 10, self.total_amount or 0.0, money)
        for col, width in enumerate((28, 22, 14, 16, 20, 16, 14, 16, 13, 14, 14, 10, 40)):
            ws.set_column(col, col, width)
        wb.close()
        fname = 'bonus_%s.xlsx' % (self.period_label or self.id)
        attachment = self.env['ir.attachment'].create({
            'name': fname,
            'type': 'binary',
            'datas': base64.b64encode(buf.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    # ── Compute engine ────────────────────────────────────────────────
    def _compute_lines(self):
        """Refresh bonus lines from the set of employees in ``line_ids``.

        Employee selection model (single source of truth):
          - If ``line_ids`` already contains lines, recompute exactly those
            employees. Manually-added employees and manual overrides are
            preserved across recomputes.
          - If ``line_ids`` is empty AND the legacy ``employee_ids`` M2M is
            set, seed lines from it (back-compat for existing draft batches
            created before 18.0.2.0.0).
          - If both are empty, fall back to all active company employees
            (preserves the prior "leave empty to mean everyone" semantics).

        Lines whose employee was archived since the last run are removed.
        Sudo is used for internal writes so HR users don't hit access errors
        on bookkeeping — outer permission gating already ran in action_compute.
        """
        self.ensure_one()
        Calc = self.env['sl.bonus.calculator'].sudo()
        Line = self.env['sl.bonus.batch.line'].sudo()
        Component = self.env['sl.bonus.batch.line.component'].sudo()

        # 1) Determine the employee set for this run. Lines/selections are
        #    kept as-is — archived (departed) employees still compute, since
        #    they keep the bonus for the period they worked.
        if self.line_ids:
            employees = self.line_ids.sudo().mapped('employee_id')
        elif self.employee_ids:
            employees = self.employee_ids.sudo()
            # Materialize legacy M2M selection into draft lines so subsequent
            # compute runs use line_ids exclusively.
            Line.create([{
                'batch_id': self.id, 'employee_id': emp.id, 'state': 'draft',
            } for emp in employees])
        else:
            employees = self.env['hr.employee'].sudo().search([
                ('company_id', 'in', [self.company_id.id, False]),
                ('active', '=', True),
            ])
            Line.create([{
                'batch_id': self.id, 'employee_id': emp.id, 'state': 'draft',
            } for emp in employees])

        if not employees:
            raise UserError(_(
                "No employees to compute. Add employees to the batch, or — if you "
                "left the selection empty — ensure active employees exist for '%s'."
            ) % self.company_id.name)

        # 2) Compute / refresh per-employee, preserving manual overrides.
        #    The appraisal batch reference (if any) is passed down so the
        #    calculator constrains evaluation lookups to that batch only.
        appraisal_batch = self.appraisal_batch_id or False
        existing_lines = {l.employee_id.id: l for l in self.sudo().line_ids}
        seen_emp_ids = set()
        for emp in employees:
            seen_emp_ids.add(emp.id)
            result = Calc.calculate_for_employee(
                emp, self.period_start, self.period_end,
                appraisal_batch=appraisal_batch,
            )
            line_vals = result['line_vals']
            line_vals['batch_id'] = self.id
            line_vals['employee_id'] = emp.id
            if emp.id in existing_lines:
                line = existing_lines[emp.id].sudo()
                has_override = bool(line.manual_override_reason) and line.manual_override_amount is not False
                if has_override:
                    overridden_amount = line.manual_override_amount
                    line.write({**line_vals, 'bonus_amount': overridden_amount})
                else:
                    line.write(line_vals)
                if line.component_ids:
                    line.component_ids.sudo().unlink()
            else:
                line = Line.create(line_vals)
            if result.get('components'):
                Component.create([
                    dict(c, line_id=line.id) for c in result['components']
                ])
        # 3) Remove stale lines for employees that were not part of this run
        #    (only possible via the legacy employee_ids / whole-company paths).
        to_remove = self.sudo().line_ids.filtered(lambda l: l.employee_id.id not in seen_emp_ids)
        if to_remove:
            to_remove.sudo().unlink()

    def unlink(self):
        """Deletion policy:
          - draft / data_ready : HR Manager or Admin may delete.
          - computed / hr_review: only Admin may delete (preserves audit-able runs).
          - approved / locked  : nobody may delete via standard unlink.
        Lines and components cascade via Odoo's ondelete='cascade'.
        """
        is_admin = self._is_admin()
        is_hr = self._is_hr()
        for rec in self:
            if rec.state in ('approved', 'locked'):
                raise UserError(_(
                    "Batch '%(name)s' is %(state)s and cannot be deleted. "
                    "Reset it to draft first (Admin only)."
                ) % {'name': rec.name, 'state': rec.state})
            if rec.state in ('computed', 'hr_review') and not is_admin:
                raise UserError(_(
                    "Batch '%(name)s' is in '%(state)s' state. Only an Admin can delete it; "
                    "otherwise reset it to draft first."
                ) % {'name': rec.name, 'state': rec.state})
            if not (is_hr or is_admin):
                raise AccessError(_(
                    "You don't have permission to delete bonus batches. Contact HR / Admin."
                ))
        return super().unlink()
