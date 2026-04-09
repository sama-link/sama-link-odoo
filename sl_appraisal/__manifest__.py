{
    'name': 'Samalink Appraisals v1.0.0',
    'version': '18.0.1.0.0',
    'summary': 'Customized HR Appraisals with Skills Integration & 3-Stage Workflow',
    'description': """
        Extends Open HRMS Appraisals for Samalink:
        - 3-stage workflow: Draft → Published → HR Finalization
        - Skills evaluation linked to survey questions
        - Auto-update employee skills on HR approval
        - Employee self-service "My Appraisals" portal
    """,
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': [
        'oh_appraisal',
        'hr_skills',
        'survey',
        'samalink_security_groups',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/sl_appraisal_security.xml',
        'data/stages.xml',
        'views/manager_feedback_views.xml',
        'views/hr_appraisal_views.xml',
        'views/hr_employee_views.xml',
        'views/my_appraisals_views.xml',
        'views/menuitems.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
