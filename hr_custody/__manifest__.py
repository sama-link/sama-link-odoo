{
    'name': 'Employee Personal Assets (Custody) Management',
    'version': '18.0.1.0.0',
    'summary': 'Manage employee custody items and link with offboarding',
    'description': """
        This module allows you to manage personal assets assigned to employees.
        It links custody items to the employee profile and contract.
        It also enforces a rule that offboarding cannot be completed unless all custody items are cleared.
    """,
    'category': 'Human Resources',
    'author': 'Antigravity',
    'depends': ['hr', 'hr_contract', 'hr_resignation'],
    'data': [
        'security/ir.model.access.csv',
        'views/custody_view.xml',
        'views/employee_view.xml',
        'views/contract_view.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
