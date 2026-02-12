{
    'name': 'SamaLink Project',
    'version': '1.0.0',
    'summary': 'Project management module for Samalink',
    'description': 'A module to manage projects within the Samalink system.',
    'author': 'Your Company Name',
    'website': 'https://yourcompanywebsite.com',
    'category': 'Project',
    'depends': ['base', 'project'],
    'data': [
        'security/ir_rule.xml',
        'views/project_project.xml',
        'views/project_task.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}