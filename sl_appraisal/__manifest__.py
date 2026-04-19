{
    'name': 'Samalink Appraisals v1.0.0',
    'version': '18.0.1.0.0',
    'summary': 'Customized HR Appraisals with Skills Integration & 3-Stage Workflow',
    'description': """
        Extends Open HRMS Appraisals for Samalink:
        - 3-stage workflow: Draft → Published → HR Finalization
        - Skills evaluation and role-based feedback
        - Auto-update employee skills on HR approval
        - Employee self-service "My Appraisals" portal
    """,
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': [
        'oh_appraisal',
        'hr_skills',
        'samalink_security_groups',
    ],
    'data': [
        'security/sl_appraisal_groups.xml',
        'security/ir.model.access.csv',
        'security/sl_appraisal_security.xml',
        'data/stages.xml',
        'data/ir_cron_data.xml',
        'wizard/hr_appraisal_batch_employees_views.xml',
        'views/manager_feedback_views.xml',
        'views/hr_appraisal_views.xml',
        'views/hr_appraisal_batch_views.xml',
        'views/hr_employee_views.xml',
        'views/my_appraisals_views.xml',
        'reports/appraisal_batch_report.xml',
        'reports/appraisal_batch_report_template.xml',
        'views/menuitems.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
