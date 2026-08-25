{
    'name': 'Samalink Quarterly Project Bonus',
    'version': '18.0.1.0.0',
    'summary': 'Points-based quarterly project bonus: projects earn points, '
               'a quarterly pool sets the EGP per point, owners share it with the team',
    'description': """
        Quarterly Project Bonus for Samalink.

        - Projects with an owner, time frame, KPI, points and tasks.
        - Three roles: Project Employee (read), Project Owner (create/write own
          projects and tasks, distribute points), Project Admin (approves points
          and KPI, receives finished projects, sets the quarterly pool, closes
          the quarter, dashboard).
        - Points earned = approved points × KPI achieved % − late penalty.
        - Quarter close: EGP per point = pool ÷ points of all projects received
          in the quarter; every employee's bonus = their points × rate.
        - Comparison against the monthly method
          (baseline % × basic salary × project months) with ▲ / ▼ per row.
        - Employees on the quarterly track are flagged on the employee card
          (bonus_quarterly_exclusion) and skipped by the monthly bonus.
    """,
    'author': 'Samalink',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'license': 'LGPL-3',
    'depends': [
        'hr',
        'hr_contract',
        'mail',
        'sl_monthly_bonus',
    ],
    'data': [
        'security/sl_qbonus_groups.xml',
        'security/ir.model.access.csv',
        'security/sl_qbonus_security.xml',
        'data/ir_sequence_data.xml',
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'views/sl_qbonus_project_views.xml',
        'views/sl_qbonus_task_views.xml',
        'views/sl_qbonus_quarter_views.xml',
        'views/sl_qbonus_line_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/sl_qbonus_menus.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
}
