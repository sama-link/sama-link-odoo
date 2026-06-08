"""Migration safety for the P1 Edara ``edara_row_uid`` unique constraints.

``edara_row_uid`` is a NEW column in 18.0.1.2.0, so on a normal upgrade the
column does not yet exist when this pre-migration runs and there is nothing to
clean (Odoo creates the column and applies the unique constraint afterwards;
PostgreSQL allows multiple NULLs under a UNIQUE constraint, so pre-existing
manual/CSV rows — which have NULL uid — never conflict).

This script is nonetheless defensive and idempotent: if the column already
exists (e.g. a re-run, or a partially-applied upgrade) it de-duplicates any
non-NULL ``edara_row_uid`` values — keeping the lowest id and NULL-ing the rest
— so the UNIQUE constraint can always be (re)applied without error.
"""
import logging

_logger = logging.getLogger(__name__)

_TABLES = (
    'sl_bonus_edara_staging_sales',
    'sl_bonus_edara_staging_stock',
    'sl_bonus_edara_staging_installation',
    'sl_bonus_edara_staging_target',
    'sl_bonus_edara_staging_branch_profit',
)


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return cr.fetchone()[0] is not None


def migrate(cr, version):
    if not version:
        # Fresh install — nothing to migrate.
        return
    for table in _TABLES:
        if not _table_exists(cr, table):
            continue
        if not _column_exists(cr, table, 'edara_row_uid'):
            # Normal path: column is created by the ORM after this script. No
            # existing data can violate the soon-to-be-added unique constraint.
            continue
        # Defensive de-dup of any non-NULL duplicates (idempotent).
        cr.execute("""
            UPDATE {tbl} t
               SET edara_row_uid = NULL
             WHERE edara_row_uid IS NOT NULL
               AND id NOT IN (
                   SELECT MIN(id) FROM {tbl}
                    WHERE edara_row_uid IS NOT NULL
                    GROUP BY edara_row_uid
               )
        """.format(tbl=table))
        if cr.rowcount:
            _logger.info(
                "sl_monthly_bonus 18.0.1.2.0: de-duplicated %s edara_row_uid value(s) in %s.",
                cr.rowcount, table,
            )
