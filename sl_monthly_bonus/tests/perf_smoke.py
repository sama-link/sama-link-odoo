"""Performance smoke: run a full batch compute over the live 155 employees and
report elapsed time. Rolls back at the end.
"""
import time
from datetime import date
import odoo
from odoo.api import Environment


def run(db='sama'):
    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo',
    ])
    registry = odoo.modules.registry.Registry(db)
    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        active_emps = env['hr.employee'].search_count([('active', '=', True)])
        print(f"Active employees: {active_emps}")
        batch = env['sl.bonus.batch'].create({
            'name': 'PERF Smoke',
            'period_start': date(2026, 3, 1),
            'period_end': date(2026, 3, 31),
        })
        batch.action_mark_data_ready()
        t0 = time.time()
        batch.action_compute()
        elapsed = time.time() - t0
        print(f"Computed {len(batch.line_ids)} lines in {elapsed:.2f}s")
        excluded = sum(1 for l in batch.line_ids if l.is_excluded)
        total_amount = sum(l.bonus_amount for l in batch.line_ids if not l.is_excluded)
        print(f"  Excluded: {excluded}, Total bonus (excl. excluded): {total_amount:,.2f}")
        cr.rollback()


if __name__ == '__main__':
    run()
