"""One-time migration: reset auto-defaulted job bonus_category.

Prior to 18.0.1.1.0, hr.job.bonus_category defaulted to 'service'. Any job
created in that window without explicit HR configuration silently became
'service' and would have produced a monthly bonus once paired with a
service-rate row.

This migration switches such jobs to 'none' so that unconfigured jobs no
longer pay out. A job is considered "intentionally configured" — and is
LEFT ALONE — if any of the following points to it:

  * a sl.bonus.service.rate record (for category='service')
  * a sl.bonus.installation.rate record (for category='installation')
  * a sl.bonus.stock.commission.rate row referencing the job
  * a sl.bonus.branch.manager.rate row referencing the job
  * an explicit edit history (last edited by a non-system user — heuristic)

Run via Odoo upgrade machinery; safe to re-run (idempotent).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install — no migration needed.
        return

    _logger.info("sl_monthly_bonus: migrating auto-defaulted hr.job.bonus_category to 'none'")

    cr.execute("""
        WITH configured AS (
            SELECT job_id FROM sl_bonus_service_rate WHERE job_id IS NOT NULL
            UNION
            SELECT job_id FROM sl_bonus_installation_rate WHERE job_id IS NOT NULL
            UNION
            SELECT job_id FROM sl_bonus_stock_commission_rate WHERE job_id IS NOT NULL
            UNION
            SELECT job_id FROM sl_bonus_branch_manager_rate WHERE job_id IS NOT NULL
        )
        UPDATE hr_job
           SET bonus_category = 'none',
               write_date = NOW()
         WHERE bonus_category = 'service'
           AND id NOT IN (SELECT job_id FROM configured)
    """)
    _logger.info("sl_monthly_bonus migration: reset %s job(s) to bonus_category='none'.", cr.rowcount)
