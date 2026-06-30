{
    'name': 'Samalink Freelancer Records v1.0.0',
    'version': '18.0.1.0.0',
    'summary': 'Track freelancer work records with selected attendance hours',
    'description': """
        Freelancer work records for Samalink:
        - Record per freelancer task: employee, description, selected attendance records
        - Auto total worked hours of the selected attendances
        - Smart button to view the linked attendance records
        - Role-based access: self-service users (own records) and administrators (all records)
        - Native graph + pivot analysis (total hours, average task hours, counts)
    """,
    'author': '46-d-006',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': [
        'hr',
        'hr_attendance',
    ],
    'data': [
        'security/sl_freelancer_groups.xml',
        'security/ir.model.access.csv',
        'security/sl_freelancer_security.xml',
        'views/sl_freelancer_task_views.xml',
        'views/sl_freelancer_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
