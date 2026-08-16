import base64
import csv
import io
from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError


class SlBonusEdaraImportWizard(models.TransientModel):
    """Manually import Edara staging data from a CSV upload (mock / local use).

    Expected CSV columns:
      role,edara_external_id,date,amount,is_collected,note
    or for stock:
      role=stock_purchasing → uses stock_sales_value instead of amount
    or for installation:
      role=installation → uses 'completed'
    """
    _name = 'sl.bonus.edara.import.wizard'
    _description = 'Import Edara Staging Data (CSV)'

    file_data = fields.Binary(string='CSV File', required=True)
    file_name = fields.Char(string='File Name')
    target_model = fields.Selection(
        selection='_selection_target_model', string='Target', required=True,
        default='sl.bonus.edara.staging.sales')
    create_sync_run = fields.Boolean(
        string='Create Sync Log', default=True,
        help='Also create a sl.bonus.edara.sync record summarizing this import.',
    )

    @api.model
    def _selection_target_model(self):
        """Offer the other staging models to HR upwards only.

        The import writes through sudo(), so this selection is what stops a
        sales-only role from loading stock or installation data. Bonus / HR
        Manager implies the Sales Manager group, so testing for HR covers HR
        and Admin while excluding a plain Sales Manager.
        """
        options = [('sl.bonus.edara.staging.sales', 'Sales')]
        if self.env.user.has_group('sl_monthly_bonus.group_bonus_hr_manager'):
            options += [
                ('sl.bonus.edara.staging.stock', 'Stock Purchases'),
                ('sl.bonus.edara.staging.installation', 'Installations'),
            ]
        return options

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please attach a CSV file."))
        # Enforced here too: the selection shapes the dropdown, this stops a
        # crafted RPC that sets target_model directly.
        if (self.target_model != 'sl.bonus.edara.staging.sales'
                and not self.env.user.has_group(
                    'sl_monthly_bonus.group_bonus_hr_manager')):
            raise AccessError(
                _("You may only import Sales staging data."))
        Sync = self.env['sl.bonus.edara.sync'].sudo()
        Mapping = self.env['sl.bonus.edara.mapping'].sudo()
        Model = self.env[self.target_model].sudo()
        try:
            raw = base64.b64decode(self.file_data).decode('utf-8-sig')
        except Exception as exc:
            raise UserError(_("Could not decode the file: %s") % exc)
        reader = csv.DictReader(io.StringIO(raw))
        sync_run = False
        if self.create_sync_run:
            sync_run = Sync.create({
                'triggered_by': 'manual',
                'state': 'running',
            })
        count = 0
        try:
            for row in reader:
                vals = self._row_to_vals(row, sync_run)
                if not vals:
                    continue
                if not vals.get('employee_id') and vals.get('edara_external_id'):
                    role_map = {
                        'sl.bonus.edara.staging.sales': 'sales',
                        'sl.bonus.edara.staging.stock': 'stock_purchasing',
                        'sl.bonus.edara.staging.installation': 'installation',
                    }
                    emp = Mapping.resolve_employee(
                        vals['edara_external_id'], role_map[self.target_model],
                    )
                    if emp:
                        vals['employee_id'] = emp.id
                Model.create(vals)
                count += 1
        except Exception as exc:
            if sync_run:
                sync_run._finish('failure', str(exc))
            raise UserError(_("Import failed: %s") % exc)
        if sync_run:
            counts_field = {
                'sl.bonus.edara.staging.sales': 'sales_records',
                'sl.bonus.edara.staging.stock': 'stock_records',
                'sl.bonus.edara.staging.installation': 'installation_records',
            }[self.target_model]
            sync_run._finish('success', _("Imported %s rows.") % count, counts={counts_field: count})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Complete'),
                'message': _('Imported %s rows into %s.') % (count, self.target_model),
                'type': 'success', 'sticky': False,
            },
        }

    def _row_to_vals(self, row, sync_run):
        if not row:
            return False
        vals = {'sync_id': sync_run.id if sync_run else False}
        vals['edara_external_id'] = (row.get('edara_external_id') or '').strip() or False
        vals['date'] = row.get('date') or False
        vals['note'] = row.get('note') or False
        if self.target_model == 'sl.bonus.edara.staging.sales':
            vals['amount'] = float(row.get('amount') or 0.0)
            collected_raw = (row.get('is_collected') or '1').strip().lower()
            vals['is_collected'] = collected_raw in ('1', 'true', 'yes', 't', 'y')
        elif self.target_model == 'sl.bonus.edara.staging.stock':
            vals['stock_sales_value'] = float(row.get('stock_sales_value') or row.get('amount') or 0.0)
            vals['classification'] = (row.get('classification') or 'po_level').strip() or 'po_level'
        elif self.target_model == 'sl.bonus.edara.staging.installation':
            completed_raw = (row.get('completed') or '1').strip().lower()
            vals['completed'] = completed_raw in ('1', 'true', 'yes', 't', 'y')
        if not vals.get('date'):
            return False
        return vals
