from io import BytesIO

import xlsxwriter
from werkzeug.exceptions import NotFound

from odoo import _, fields, http
from odoo.http import content_disposition, request


class AppraisalBatchExportController(http.Controller):
    @http.route('/sl_appraisal/batch/export/xlsx', type='http', auth='user')
    def export_batch_xlsx(self, ids=None, cids=None, **kwargs):
        try:
            batch_ids = [int(batch_id) for batch_id in (ids or '').split(',') if batch_id]
        except ValueError as exc:
            raise NotFound() from exc
        if not batch_ids:
            raise NotFound()

        # Scope the export to the companies selected in the web client (passed
        # as ``cids``) intersected with the companies the user may access. This
        # is a full-page navigation, so the request carries no company context
        # and ``allowed_company_ids`` would otherwise default to every company
        # the user belongs to, leaking cross-company appraisals into the file.
        user_company_ids = request.env.user.company_ids.ids
        requested_cids = [
            int(cid) for cid in (cids or '').split(',') if cid.strip().isdigit()
        ]
        allowed_company_ids = [
            cid for cid in requested_cids if cid in user_company_ids
        ] or [request.env.company.id]

        env = request.env(context=dict(
            request.env.context, allowed_company_ids=allowed_company_ids,
        ))

        batches = env['hr.appraisal.batch'].browse(batch_ids).exists()
        if not batches:
            raise NotFound()

        batches.check_access('read')

        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        title_format = workbook.add_format({'bold': True, 'font_size': 14})
        label_format = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1,
            'align': 'center',
        })
        text_format = workbook.add_format({'border': 1, 'valign': 'top'})
        percent_format = workbook.add_format({'border': 1, 'num_format': '0.00'})

        # Selection labels and related names are read through ``env`` (the
        # user's language), so the file follows the language the user picked in
        # Odoo. For RTL languages (Arabic) the sheets are laid out right-to-left.
        state_labels = dict(env['hr.appraisal'].fields_get(['state'])['state']['selection'])
        lang = env['res.lang']._lang_get(env.context.get('lang') or env.user.lang)
        is_rtl = lang.direction == 'rtl'

        last_col = 12
        for batch in batches:
            sheet = workbook.add_worksheet((batch.name or _('Batch'))[:31])
            if is_rtl:
                sheet.right_to_left()
            sheet.set_column(0, 0, 28)
            sheet.set_column(1, 4, 22)
            sheet.set_column(5, 6, 30)
            sheet.set_column(7, 11, 15)
            sheet.set_column(12, 12, 18)

            sheet.merge_range(0, 0, 0, last_col, batch.name or _('Appraisal Batch'), title_format)
            sheet.write(1, 0, _('Period'), label_format)
            sheet.write(1, 1, f'{batch.date_from or ""} -> {batch.date_to or ""}', text_format)
            sheet.write(2, 0, _('Deadline'), label_format)
            sheet.write(2, 1, str(batch.date_deadline or ''), text_format)
            sheet.write(3, 0, _('Created By'), label_format)
            sheet.write(3, 1, batch.creator_id.name or '', text_format)
            sheet.write(4, 0, _('Generated On'), label_format)
            sheet.write(4, 1, str(fields.Datetime.now()), text_format)

            headers = [
                _('Employee'),
                _('Job Position'),
                _('Work Location'),
                _('General Manager'),
                _('Coach Manager'),
                _('Selected Managers'),
                _('Selected Employees'),
                _('Skills Average (%)'),
                _('Administration Score (%)'),
                _('Manual Score (%)'),
                _('Total Score (%)'),
                _('Last Month Total (%)'),
                _('State'),
            ]
            row = 6
            for col, header in enumerate(headers):
                sheet.write(row, col, header, header_format)

            scoped_appraisals = batch.appraisal_ids.filtered(
                lambda app: not app.company_id or app.company_id.id in allowed_company_ids
            )
            previous_totals = self._previous_batch_totals(env, batch, scoped_appraisals)
            for appraisal in scoped_appraisals.sorted(lambda app: app.employee_id.name or ''):
                row += 1
                sheet.write(row, 0, appraisal.employee_id.name or '', text_format)
                sheet.write(row, 1, appraisal.job_id.name or '', text_format)
                sheet.write(row, 2, appraisal.work_location_id.name or '', text_format)
                sheet.write(row, 3, appraisal.general_manager_id.name or '', text_format)
                sheet.write(row, 4, appraisal.coach_manager_id.name or '', text_format)
                sheet.write(row, 5, ', '.join(appraisal.hr_manager_ids.mapped('name')), text_format)
                sheet.write(row, 6, ', '.join(appraisal.hr_employee_ids.mapped('name')), text_format)
                sheet.write_number(row, 7, appraisal.skill_average_score or 0.0, percent_format)
                sheet.write_number(row, 8, appraisal.admin_score or 0.0, percent_format)
                sheet.write_number(row, 9, appraisal.manual_score or 0.0, percent_format)
                sheet.write_number(row, 10, appraisal.total_score or 0.0, percent_format)
                previous_total = previous_totals.get(appraisal.employee_id.id)
                if previous_total is None:
                    sheet.write(row, 11, '', text_format)
                else:
                    sheet.write_number(row, 11, previous_total, percent_format)
                sheet.write(row, 12, state_labels.get(appraisal.state, appraisal.state), text_format)

            sheet.freeze_panes(7, 0)
            if row >= 6:
                sheet.autofilter(6, 0, row, last_col)

        workbook.close()
        output.seek(0)

        filename = 'appraisal_batches.xlsx' if len(batches) > 1 else f'{batches[0].name or "appraisal_batch"}.xlsx'
        return request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', content_disposition(filename)),
            ],
        )

    def _previous_batch_totals(self, env, batch, scoped_appraisals):
        """Map each employee to their Total Score (%) from the most recent
        EARLIER batch (by period end date). Used for the 'Last Month Total'
        column. The search runs through ``env`` so the multi-company scope and
        record rules already applied to the export are honoured here too."""
        employee_ids = scoped_appraisals.employee_id.ids
        if not batch.date_to or not employee_ids:
            return {}
        candidates = env['hr.appraisal'].search([
            ('employee_id', 'in', employee_ids),
            ('appraisal_batch_id', '!=', False),
            ('appraisal_batch_id.date_to', '<', batch.date_to),
        ])
        latest = {}
        for candidate in candidates:
            employee_id = candidate.employee_id.id
            candidate_date = candidate.appraisal_batch_id.date_to
            current = latest.get(employee_id)
            if current is None or candidate_date > current[0]:
                latest[employee_id] = (candidate_date, candidate.total_score or 0.0)
        return {employee_id: data[1] for employee_id, data in latest.items()}
