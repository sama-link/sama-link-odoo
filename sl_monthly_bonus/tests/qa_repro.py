"""Post-fix QA reproduction — exercises the previously-broken paths as the HR
officer user (login='sama', uid=2). Creates a transient batch, runs all the
operations that used to crash, rolls back at the end.
"""
import sys
import traceback
from datetime import date
import odoo
from odoo.api import Environment


def _connect(db='sama'):
    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo',
    ])
    return odoo.modules.registry.Registry(db)


def repro(label, fn):
    print("\n========", label, "========")
    try:
        fn()
        print("OK — no exception")
    except Exception as exc:
        print("EXCEPTION:", type(exc).__name__, str(exc)[:400])
        traceback.print_exc(limit=6)


def main(db='sama'):
    registry = _connect(db)
    HR_UID = 2  # 'sama' user — has samalink_hr_officer (which implies bonus_hr_manager)

    # 1+2. Recompute / unlink as HR user.
    with registry.cursor() as cr:
        env = Environment(cr, HR_UID, {})
        Batch = env['sl.bonus.batch']
        batch = Batch.create({
            'name': 'QA Repro 2026-01',
            'period_start': date(2026, 1, 1),
            'period_end': date(2026, 1, 31),
        })
        print("created batch", batch.id, "state", batch.state)
        repro("mark data ready", batch.action_mark_data_ready)
        repro("compute (1st)", batch.action_compute)
        repro("compute (2nd)", batch.action_compute)
        repro("compute (3rd)", batch.action_compute)
        line = batch.line_ids[:1]
        if line:
            print("first line id:", line.id, "components:", len(line.component_ids))
        repro("send to review", batch.action_send_to_review)
        repro("recompute from hr_review", batch.action_compute)
        # Reset back to draft so we can also test draft unlink (admin gating).
        env.cr.execute("UPDATE sl_bonus_batch SET state='draft' WHERE id=%s", (batch.id,))
        batch.invalidate_recordset()
        repro("unlink batch (draft) by HR", batch.unlink)
        cr.rollback()

    # 3. open_for_previous_month idempotent
    with registry.cursor() as cr:
        env = Environment(cr, HR_UID, {})
        Batch = env['sl.bonus.batch']
        # Pre-create previous-month batch
        from datetime import date as _d
        from calendar import monthrange
        today = _d.today()
        py, pm = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        end_day = monthrange(py, pm)[1]
        Batch.search([('period_start', '=', _d(py, pm, 1))]).unlink()
        pre = Batch.create({
            'name': 'pre-existing previous',
            'period_start': _d(py, pm, 1),
            'period_end': _d(py, pm, end_day),
        })
        def _open():
            act = Batch.action_open_for_previous_month()
            assert act.get('res_id') == pre.id, act
        repro("open_for_previous_month returns existing", _open)
        cr.rollback()


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'sama')
