"""Bonus Payout XLSX export — accounting-ready spreadsheet for a single bonus batch.

Streams a workbook via xlsxwriter (bundled with Odoo). Restricted to HR/Admin
groups; raises AccessError otherwise.
"""
import io
import xlsxwriter
from odoo import http, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class SlBonusPayoutXlsx(http.Controller):

    @http.route('/sl_monthly_bonus/batch/<int:batch_id>/payout.xlsx', type='http', auth='user')
    def payout_xlsx(self, batch_id, **kw):
        env = request.env
        if not (env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager')
                or env.user.has_group('sl_monthly_bonus.group_bonus_admin')
                or env.user.has_group('base.group_system')):
            raise AccessError(_("Only HR Manager / Admin can export the payout sheet."))
        batch = env['sl.bonus.batch'].browse(batch_id)
        if not batch.exists():
            raise UserError(_("Batch not found."))
        if batch.state not in ('hr_review', 'approved', 'locked'):
            raise UserError(_(
                "Payout sheet is only available for HR Review / Approved / Locked batches "
                "(current: %s)."
            ) % batch.state)

        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True})
        ws = wb.add_worksheet(_('Payout'))
        ws.right_to_left()

        title_fmt = wb.add_format({'bold': True, 'font_size': 14, 'align': 'right'})
        header_fmt = wb.add_format({
            'bold': True, 'bg_color': '#10566A', 'font_color': 'white',
            'border': 1, 'align': 'center',
        })
        cell_fmt = wb.add_format({'border': 1, 'align': 'right'})
        money_fmt = wb.add_format({'border': 1, 'num_format': '#,##0.00', 'align': 'right'})
        pct_fmt = wb.add_format({'border': 1, 'num_format': '0.00"%"', 'align': 'right'})
        total_fmt = wb.add_format({
            'bold': True, 'bg_color': '#FFEEAA', 'border': 1, 'num_format': '#,##0.00',
            'align': 'right',
        })
        warning_fmt = wb.add_format({'bold': True, 'font_color': '#B00020', 'align': 'right'})

        ws.merge_range(0, 0, 0, 7, _('Monthly Bonus Payout Sheet — %s') % batch.name, title_fmt)
        ws.write(1, 0, _('Period'), header_fmt)
        ws.write(1, 1, batch.period_start.strftime('%Y-%m') if batch.period_start else '', cell_fmt)
        ws.write(1, 2, _('State'), header_fmt)
        ws.write(1, 3, batch.state, cell_fmt)
        ws.write(1, 4, _('Eligible'), header_fmt)
        ws.write(1, 5, batch.paid_count, cell_fmt)
        ws.write(1, 6, _('Excluded'), header_fmt)
        ws.write(1, 7, batch.excluded_count, cell_fmt)

        if batch.treat_missing_eval_as_full:
            ws.merge_range(2, 0, 2, 7,
                _('Treat Missing Evaluation as 100%% is ON for this batch.'),
                warning_fmt,
            )
            data_start_row = 4
        else:
            data_start_row = 3

        headers = [
            _('#'), _('Employee'), _('Department'), _('Job'), _('Category'),
            _('Evaluation %'), _('Computed'), _('Bonus'),
        ]
        for col, h in enumerate(headers):
            ws.write(data_start_row, col, h, header_fmt)
            ws.set_column(col, col, 18)

        row = data_start_row + 1
        total = 0.0
        eligible = batch.line_ids.filtered(lambda l: not l.is_excluded)
        for i, line in enumerate(eligible.sorted(lambda l: l.employee_id.name or ''), start=1):
            ws.write(row, 0, i, cell_fmt)
            ws.write(row, 1, line.employee_id.name or '', cell_fmt)
            ws.write(row, 2, line.department_id.name or '', cell_fmt)
            ws.write(row, 3, line.job_id.name or '', cell_fmt)
            ws.write(row, 4, dict(line._fields['category'].selection).get(line.category, ''), cell_fmt)
            ws.write(row, 5, line.evaluation_percent or 0.0, pct_fmt)
            ws.write(row, 6, line.computed_amount or 0.0, money_fmt)
            ws.write(row, 7, line.bonus_amount or 0.0, money_fmt)
            total += line.bonus_amount or 0.0
            row += 1

        ws.merge_range(row, 0, row, 6, _('Total'), header_fmt)
        ws.write(row, 7, total, total_fmt)
        row += 2

        excluded = batch.line_ids.filtered(lambda l: l.is_excluded)
        if excluded:
            ws.write(row, 0, _('Excluded Employees'), title_fmt)
            row += 1
            for h_i, h in enumerate([_('Employee'), _('Category'), _('Reason')]):
                ws.write(row, h_i, h, header_fmt)
            row += 1
            for line in excluded.sorted(lambda l: l.employee_id.name or ''):
                ws.write(row, 0, line.employee_id.name or '', cell_fmt)
                ws.write(row, 1, dict(line._fields['category'].selection).get(line.category, ''), cell_fmt)
                ws.write(row, 2, line.exclusion_reason or '', cell_fmt)
                row += 1

        wb.close()
        data = buf.getvalue()
        buf.close()
        filename = f"bonus_payout_{batch.period_start and batch.period_start.strftime('%Y_%m') or batch.id}.xlsx"
        return request.make_response(
            data,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ],
        )
