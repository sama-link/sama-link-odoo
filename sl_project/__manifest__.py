{
    'name': 'SamaLink Project',
    'version': '18.0.1.3.1',
    'summary': 'Project management module for Samalink',
    'description': 'A module to manage projects within the Samalink system.',
    'author': 'Your Company Name',
    'website': 'https://yourcompanywebsite.com',
    'category': 'Project',
    'depends': ['base', 'project', 'hr', 'project_todo'],
    'data': [
        'security/ir_rule.xml',
        'views/project_project.xml',
        'views/project_task.xml',
        'views/project_task_calendar.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'sl_project/static/src/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}