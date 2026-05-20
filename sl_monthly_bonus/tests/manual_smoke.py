"""Manual end-to-end smoke against the real 'sama' DB.

Creates an isolated test job + employee + contract + appraisal, runs the
calculator for each category, then rolls back. Verifies all 5 Appendix A
examples produce expected values without persisting anything.
"""
from datetime import date, timedelta
import odoo
from odoo.api import Environment
from odoo import fields as f


def _finalize(env, emp, period_start, period_end, score):
    a = env['hr.appraisal'].sudo().create({
        'employee_id': emp.id,
        'date_from': period_start, 'date_to': period_end,
        'appraisal_deadline': f.Date.today() + timedelta(days=30),
    })
    env.cr.execute("UPDATE hr_appraisal SET state='submitted' WHERE id=%s", (a.id,))
    a.invalidate_recordset()
    a.sudo().write({'total_score': score})
    env.cr.execute("UPDATE hr_appraisal SET state='hr_finalization' WHERE id=%s", (a.id,))
    a.invalidate_recordset()
    return a


def _make_emp(env, name, job, wage):
    emp = env['hr.employee'].create({'name': name, 'job_id': job.id})
    env['hr.contract'].create({
        'name': f'C-{name}', 'employee_id': emp.id, 'wage': wage,
        'state': 'open', 'date_start': date(2025, 1, 1),
    })
    return emp


def run(db='sama'):
    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo',
    ])
    registry = odoo.modules.registry.Registry(db)
    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        Calc = env['sl.bonus.calculator']
        ps, pe = date(2026, 4, 1), date(2026, 4, 30)

        # Service: 10,000 x 20% x 85% = 1,700
        j_serv = env['hr.job'].create({'name': 'SMK Service', 'bonus_category': 'service'})
        env['sl.bonus.service.rate'].create({
            'job_id': j_serv.id, 'percentage': 20.0, 'date_from': date(2025, 1, 1),
        })
        e_serv = _make_emp(env, 'SMK Service Emp', j_serv, 10000.0)
        _finalize(env, e_serv, ps, pe, 85.0)
        r = Calc.calculate_for_employee(e_serv, ps, pe)
        print(f"Service: expected 1700, got {r['line_vals']['computed_amount']}")

        # Sales: tier 4,000 at 110% achievement, eval 80% → 3,600
        j_sales = env['hr.job'].create({'name': 'SMK Sales', 'bonus_category': 'sales'})
        e_sales = _make_emp(env, 'SMK Sales Emp', j_sales, 5000.0)
        env['sl.bonus.target'].create({
            'employee_id': e_sales.id, 'period_start': ps, 'target_amount': 100000.0,
            'tier_ids': [
                (0, 0, {'name': 'T1', 'achievement_min': 80.0, 'commission_amount': 2000.0}),
                (0, 0, {'name': 'T2', 'achievement_min': 100.0, 'commission_amount': 3000.0}),
                (0, 0, {'name': 'T3', 'achievement_min': 110.0, 'commission_amount': 4000.0}),
            ],
        })
        env['sl.bonus.edara.staging.sales'].create({
            'employee_id': e_sales.id, 'date': date(2026, 4, 15),
            'amount': 110000.0, 'is_collected': True,
        })
        _finalize(env, e_sales, ps, pe, 80.0)
        r = Calc.calculate_for_employee(e_sales, ps, pe)
        print(f"Sales:   expected 3600, got {r['line_vals']['computed_amount']}")

        # Stock: 200,000 x 1.5% x 90% = 2,700
        j_stock = env['hr.job'].create({'name': 'SMK Stock', 'bonus_category': 'stock'})
        env['sl.bonus.stock.commission.rate'].create({
            'percentage': 1.5, 'date_from': date(2025, 1, 1),
        })
        e_stock = _make_emp(env, 'SMK Stock Emp', j_stock, 6000.0)
        env['sl.bonus.edara.staging.stock'].create({
            'employee_id': e_stock.id, 'date': date(2026, 4, 10),
            'stock_sales_value': 200000.0,
        })
        _finalize(env, e_stock, ps, pe, 90.0)
        r = Calc.calculate_for_employee(e_stock, ps, pe)
        print(f"Stock:   expected 2700, got {r['line_vals']['computed_amount']}")

        # Installation: 1,500 x 95% = 1,425
        j_inst = env['hr.job'].create({'name': 'SMK Inst', 'bonus_category': 'installation'})
        env['sl.bonus.installation.rate'].create({
            'job_id': j_inst.id, 'fixed_amount': 1500.0, 'date_from': date(2025, 1, 1),
        })
        e_inst = _make_emp(env, 'SMK Inst Emp', j_inst, 4000.0)
        _finalize(env, e_inst, ps, pe, 95.0)
        r = Calc.calculate_for_employee(e_inst, ps, pe)
        print(f"Install: expected 1425, got {r['line_vals']['computed_amount']}")

        # Branch manager: 12,000 x 25% x 90% = 2,700 (factor 1.2 → base)
        j_bm = env['hr.job'].create({'name': 'SMK BM', 'bonus_category': 'branch_manager'})
        addr = env['res.partner'].create({'name': 'SMK Branch Addr'})
        loc = env['hr.work.location'].create({'name': 'SMK Branch', 'address_id': addr.id})
        bp = env['sl.bonus.branch.profit'].create({
            'work_location_id': loc.id, 'period_start': ps, 'factor': 1.2,
        })
        bp.action_approve()
        env['sl.bonus.branch.manager.rate'].create({
            'job_id': j_bm.id, 'pct_low': 15.0, 'pct_base': 25.0, 'pct_high': 35.0,
            'date_from': date(2025, 1, 1),
        })
        e_bm = _make_emp(env, 'SMK BM Emp', j_bm, 12000.0)
        e_bm.work_location_id = loc.id
        _finalize(env, e_bm, ps, pe, 90.0)
        r = Calc.calculate_for_employee(e_bm, ps, pe)
        print(f"BranchM: expected 2700, got {r['line_vals']['computed_amount']}")

        # Roll back — leave the live DB untouched.
        cr.rollback()


if __name__ == '__main__':
    run()
