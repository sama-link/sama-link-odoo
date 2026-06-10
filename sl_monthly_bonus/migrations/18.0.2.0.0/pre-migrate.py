"""Schema migration for sl_monthly_bonus 18.0.2.0.0.

This release introduces *independent* bonus lines (lines that exist without a
parent batch, like an `hr.payslip` outside a `hr.payslip.run`). Two structural
changes are required on the `sl_bonus_batch_line` table:

1. Drop the NOT NULL constraint on `batch_id` so independent lines (where
   `batch_id IS NULL`) become storable.
2. Drop the legacy SQL UNIQUE constraint `(batch_id, employee_id)`. The new
   business rule — "one active bonus per (employee, year-month)" — depends on
   `period_start` rather than `batch_id` and is enforced in Python via
   `@api.constrains`, which is harder to express as a single SQL UNIQUE because
   `(year(period_start), month(period_start))` is a derived expression.

Both operations are idempotent: re-running the migration on an already-migrated
DB is a no-op (the system catalogue probes return False / "not exists" the
second time around).

Existing data (batch-owned lines and their components) is preserved as-is. Any
manual overrides on existing lines remain intact because no row data is
touched.
"""
import logging

_logger = logging.getLogger(__name__)


def _column_is_nullable(cr, table, column):
    cr.execute(
        """
        SELECT is_nullable = 'YES'
          FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    row = cr.fetchone()
    return bool(row and row[0])


def _constraint_exists(cr, table, constraint):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.table_constraints
         WHERE table_name = %s AND constraint_name = %s
        """,
        (table, constraint),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return  # Fresh install — nothing to migrate.

    # 1) Make `batch_id` nullable on `sl_bonus_batch_line`.
    if not _column_is_nullable(cr, 'sl_bonus_batch_line', 'batch_id'):
        cr.execute("ALTER TABLE sl_bonus_batch_line ALTER COLUMN batch_id DROP NOT NULL")
        _logger.info(
            "sl_monthly_bonus 18.0.2.0.0: dropped NOT NULL on sl_bonus_batch_line.batch_id"
        )

    # 2) Drop the legacy (batch_id, employee_id) SQL UNIQUE constraint. Odoo
    #    auto-recreates SQL constraints declared in `_sql_constraints`; since
    #    that declaration has been removed in this version, the constraint
    #    must be dropped explicitly so it doesn't linger from a prior install.
    if _constraint_exists(cr, 'sl_bonus_batch_line', 'sl_bonus_batch_line_uniq_batch_employee'):
        cr.execute(
            "ALTER TABLE sl_bonus_batch_line DROP CONSTRAINT sl_bonus_batch_line_uniq_batch_employee"
        )
        _logger.info(
            "sl_monthly_bonus 18.0.2.0.0: dropped legacy unique constraint uniq_batch_employee"
        )
