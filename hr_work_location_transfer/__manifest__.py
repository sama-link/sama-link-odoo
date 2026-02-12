{
    'name': 'HR Work Location Transfer',
    'version': '1.0.0',
    'summary': 'Manage employee work location transfers',
    'description': """
        This module allows HR to manage and track employee work location transfers.
    """,
    'author': '46-d-006',
    'website': 'https://yourcompany.com',
    'category': 'Human Resources',
    'depends': ['hr'],
    'data': [
        'views/hr_transfer.xml',
        'security/ir_groups.xml',
        'security/ir_rule.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}