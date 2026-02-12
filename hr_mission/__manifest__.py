{
    'name': 'HR Mission',
    'version': '1.0.1',
    'summary': 'Manage employee missions',
    'description': """
        This module allows HR to manage and track employee missions.
    """,
    'author': '46-d-006',
    'website': 'https://yourcompany.com',
    'category': 'Human Resources/Missions',
    'depends': ['hr'],
    'data': [
        'views/hr_mission.xml',
        'security/ir_groups.xml',
        'security/ir_rule.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'icon': '/hr_mission/static/description/icon.png',
}