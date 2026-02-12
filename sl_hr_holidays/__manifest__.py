{
    'name': 'Samalink Time Off',
    'version': '1.0.0',
    'summary': 'Manage HR holidays and leaves',
    'description': 'Module for managing employee holidays and leave requests.',
    'author': 'Your Company',
    'website': 'https://yourcompany.com',
    'category': 'Human Resources',
    'depends': ['base', 'hr_holidays', 'samalink_hr'],
    'data': [
        'views/hr_leave_type.xml',
        'views/hr_leave.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sl_hr_holidays/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}