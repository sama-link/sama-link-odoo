{
    'name': 'Samalink Monthly Bonus',
    'version': '18.0.1.2.0',
    'summary': 'Monthly Bonus Calculation & Payment Module for Samalink',
    'description': """
        Monthly bonus calculation, review, approval and audit module for Samalink.

        Categories:
        - Service roles (basic_salary x rate x evaluation)
        - Sales (threshold-tier commission, 50% fixed + 50% x evaluation)
        - Stock purchasing (stock_value x commission x evaluation)
        - Installations (fixed amount x evaluation)
        - Branch / area managers (basic_salary x branch tier x evaluation)

        Includes Edara staging (local/mock only), self-service estimate, audit log,
        Arabic RTL UI, dashboard, QWeb + XLSX reports, smart-link with the
        existing appraisal module, per-employee compute wizard, and an
        Admin-only emergency state-change tool.
    """,
    'author': 'Samalink',
    'website': 'https://edara.digital',
    'category': 'Human Resources',
    'depends': [
        'base',
        'hr',
        'hr_contract',
        'hr_payroll_community',
        'samalink_hr',
        'samalink_security_groups',
        'sl_appraisal',
    ],
    'data': [
        'security/sl_bonus_groups.xml',
        'security/ir.model.access.csv',
        'security/sl_bonus_security.xml',
        'data/sl_bonus_data.xml',
        'data/ir_cron_data.xml',
        'views/sl_bonus_config_views.xml',
        'views/sl_bonus_target_views.xml',
        'views/sl_bonus_branch_profit_views.xml',
        'views/sl_bonus_edara_views.xml',
        'views/sl_bonus_batch_views.xml',
        'views/sl_bonus_self_service_views.xml',
        'views/sl_bonus_audit_views.xml',
        'views/sl_bonus_dashboard_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_job_bonus_views.xml',
        'views/hr_appraisal_batch_views.xml',
        'wizard/sl_bonus_manual_adjust_views.xml',
        'wizard/sl_bonus_edara_import_views.xml',
        'wizard/sl_bonus_compute_wizard_views.xml',
        'wizard/sl_bonus_state_change_wizard_views.xml',
        'reports/sl_bonus_reports.xml',
        'reports/report_bonus_receipt.xml',
        'reports/report_bonus_payout.xml',
        'reports/report_bonus_department.xml',
        'reports/report_bonus_yearly.xml',
        'views/sl_bonus_menus.xml',
        # Loaded LAST: needs both group_bonus_* records and menu xmlids to exist.
        'security/sl_bonus_samalink_bridge.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
