{
    'name': 'User Menu Items',
    'version': '1.0.0',
    'summary': 'Custom user menu items for the application',
    'description': 'Adds custom items to the user menu.',
    'author': 'Your Name or Company',
    'website': 'https://yourwebsite.com',
    'category': 'Tools',
    'depends': ['base', 'web'],
    'assets': {
        'web.assets_backend': [
            'user_menu_items/static/src/webclient/user_menu/user_menu_items.js',
        ],
    },
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}