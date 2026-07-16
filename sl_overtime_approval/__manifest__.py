{
    'name': "Samalink Overtime Approval Reason",
    'summary': "Require a reason when approving overtime, with a configurable exception list",
    'description': """
Samalink Overtime Approval Reason
=================================

When a user approves overtime (Attendances > Management), a wizard opens with a
mandatory "Reason for Overtime" field. The reason is stored on the attendance
record (tracked in the chatter) and the overtime is approved on confirm. One
reason can be applied to several selected records at once.

Employees on the "Overtime Approval Exceptions" list (Attendances >
Configuration > Overtime Approval Exceptions) are approved directly with the
old one-click behaviour - no wizard, no reason required.
""",
    'version': '18.0.1.0.0',
    'author': 'Samalink',
    'website': 'https://edara.digital',
    'license': 'LGPL-3',
    'category': 'Human Resources/Attendances',
    'depends': ['hr_attendance', 'samalink_security_groups'],
    'data': [
        'security/ir.model.access.csv',
        'views/overtime_exception_views.xml',
        'views/hr_attendance_views.xml',
        'wizard/overtime_reason_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
