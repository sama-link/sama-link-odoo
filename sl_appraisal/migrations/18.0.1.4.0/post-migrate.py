"""Seed the employee-card appraisal eligibility fields from the legacy
Administrative Exclude list.

``appraisal_eligible`` / ``appraisal_admin_score_mode`` were added to
hr.employee in 18.0.1.4.0; column creation filled every existing employee
with the defaults (eligible / "Has administrative score"). Employees on the
legacy ``appraisal.admin.score.exclude`` list must show "No administrative
score" instead so they keep their 100% administration score.

Raw SQL on purpose: the list model was removed in 18.0.1.7.0, so a DB
jumping straight from <1.4.0 to >=1.7.0 replays this script at a point
where the ORM model no longer exists — only the legacy table (if any) does.
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'appraisal_admin_score_exclude'")
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE hr_employee e
        SET appraisal_eligible = TRUE,
            appraisal_admin_score_mode = 'exempt'
        FROM appraisal_admin_score_exclude x
        WHERE x.employee_id = e.id
        """
    )
