from odoo import fields, models


class OvertimeApprovalException(models.Model):
    _name = 'sl.overtime.approval.exception'
    _description = 'Overtime Approval Exception'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='employee_id.company_id', string='Company', store=True)
    note = fields.Char(string='Note')

    _sql_constraints = [
        ('employee_unique', 'unique(employee_id)',
         'This employee is already in the overtime approval exception list.'),
    ]
