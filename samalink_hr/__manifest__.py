{
    'name': 'Samalink HR v2.0.0',
    'version': '2.0',
    'summary': 'HR Module for Samalink',
    'description': 'Custom HR functionalities for Samalink. '
                   'Includes flexible rest day logic, absence entry filtering, '
                   'work entry adjustments, and payroll integration.',
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': ['base', 'hr', 'samalink_security_groups', 'hr_contract', 'resource', 'hr_work_entry', 'hr_holidays'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/hr_employee.xml',
        'views/hr_contract.xml',
        'views/hr_attendance.xml',
        'views/hr_work_entry.xml',
        'views/hr_absent_entry.xml',
        'views/hr_job.xml',
        'views/resource_calendar_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/generate_entries_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}