"""Operational one-shot: delete QA-labeled test batches 30 and 31.

Verifies first that each row matches the expected test signature, then commits.
Run as superuser. Do NOT use against production data without re-checking signatures.
"""
import odoo
from odoo.api import Environment


def main(db='sama'):
    odoo.tools.config.parse_config([
        '-c', '/etc/odoo/odoo.conf',
        '--db_host=db', '--db_port=5432',
        '--db_user=odoo', '--db_password=odoo',
    ])
    registry = odoo.modules.registry.Registry(db)
    with registry.cursor() as cr:
        env = Environment(cr, odoo.SUPERUSER_ID, {})
        Batch = env['sl.bonus.batch']
        wanted = [
            (30, 'Bonus 2026-04', 'draft'),
            (31, 'Bonus 2026-03 TEST', 'computed'),
        ]
        for bid, expected_name, expected_state in wanted:
            b = Batch.browse(bid)
            if not b.exists():
                print(f"batch {bid}: already gone, skipping")
                continue
            if b.name != expected_name:
                print(f"batch {bid}: name mismatch (DB={b.name!r}, expected={expected_name!r}) — skipping for safety")
                continue
            if b.state != expected_state:
                print(f"batch {bid}: state mismatch (DB={b.state!r}, expected={expected_state!r}) — skipping for safety")
                continue
            n_lines = len(b.line_ids)
            b.unlink()
            print(f"batch {bid}: deleted (had {n_lines} lines)")
        cr.commit()
        print("done")


if __name__ == '__main__':
    main()
