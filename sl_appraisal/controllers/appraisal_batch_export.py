from io import BytesIO

import xlsxwriter
from werkzeug.exceptions import NotFound

from odoo import fields, http
from odoo.http import request
from odoo.tools import content_disposition


class AppraisalBatchExportController(http.Controller):
    @http.route('/sl_appraisal/batch/export/xlsx', type='http', auth='user')
    def export_batch_xlsx(self, ids=None, **kwargs):
        try:
            batch_ids = [int(batch_id) for batch_id in (ids or '').split(',') if batch_id]
        except ValueError as exc:
            raise NotFound() from exc
        if not batch_ids:
            raise NotFound()

        batches = request.env['hr.appraisal.batch'].browse(batch_ids).exists()
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

        state_labels = dict(request.env['hr.appraisal']._fields['state'].selection)

        for batch in batches:
            sheet = workbook.add_worksheet((batch.name or 'Batch')[:31])
            sheet.set_column(0, 0, 28)
            sheet.set_column(1, 4, 22)
            sheet.set_column(5, 6, 30)
            sheet.set_column(7, 9, 15)
            sheet.set_column(10, 10, 18)

            sheet.merge_range(0, 0, 0, 10, batch.name or 'Appraisal Batch', title_format)
            sheet.write(1, 0, 'Period', label_format)
            sheet.write(1, 1, f'{batch.date_from or ""} -> {batch.date_to or ""}', text_format)
            sheet.write(2, 0, 'Deadline', label_format)
            sheet.write(2, 1, str(batch.date_deadline or ''), text_format)
            sheet.write(3, 0, 'Created By', label_format)
            sheet.write(3, 1, batch.creator_id.name or '', text_format)
            sheet.write(4, 0, 'Generated On', label_format)
            sheet.write(4, 1, str(fields.Datetime.now()), text_format)

            headers = [
                'Employee',
                'Job Position',
                'Work Location',
                'General Manager',
                'Coach Manager',
                'Selected Managers',
                'Selected Employees',
                'Skills Average (%)',
                'Manual Score (%)',
                'Total Score (%)',
                'State',
            ]
            row = 6
            for col, header in enumerate(headers):
                sheet.write(row, col, header, header_format)

            for appraisal in batch.appraisal_ids.sorted(lambda app: app.employee_id.name or ''):
                row += 1
                sheet.write(row, 0, appraisal.employee_id.name or '', text_format)
                sheet.write(row, 1, appraisal.job_id.name or '', text_format)
                sheet.write(row, 2, appraisal.work_location_id.name or '', text_format)
                sheet.write(row, 3, appraisal.general_manager_id.name or '', text_format)
                sheet.write(row, 4, appraisal.coach_manager_id.name or '', text_format)
                sheet.write(row, 5, ', '.join(appraisal.hr_manager_ids.mapped('name')), text_format)
                sheet.write(row, 6, ', '.join(appraisal.hr_employee_ids.mapped('name')), text_format)
                sheet.write_number(row, 7, appraisal.skill_average_score or 0.0, percent_format)
                sheet.write_number(row, 8, appraisal.manual_score or 0.0, percent_format)
                sheet.write_number(row, 9, appraisal.total_score or 0.0, percent_format)
                sheet.write(row, 10, state_labels.get(appraisal.state, appraisal.state), text_format)

            sheet.freeze_panes(7, 0)
            if row >= 6:
                sheet.autofilter(6, 0, row, 10)

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
