{
    'name': 'Samalink HR',
    'version': '1.1.0',
    'summary': 'HR Module for Samalink',
    'description': 'Custom HR functionalities for Samalink. '
                   'Includes flexible rest day logic, absence entry filtering, '
                   'work entry adjustments, and payroll integration.',
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': [
        'base', 'hr', 'hr_contract', 'hr_payroll_community',
        'resource', 'hr_work_entry', 'hr_holidays', 'hr_skills',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/absent_entry_server_actions.xml',
        'data/hr_employee_server_actions.xml',
        # Wizard action must load before views that reference %(action_generate_entries_wizard)d
        'wizard/generate_entries_wizard_views.xml',
        'views/hr_employee.xml',
        'views/hr_contract.xml',
        'views/hr_attendance.xml',
        'views/hr_work_entry.xml',
        'views/hr_work_entry_samalink.xml',
        'views/hr_absent_entry.xml',
        'views/hr_job.xml',
        'views/resource_calendar_views.xml',
        'views/res_config_settings_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_run_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}