"""Seed the employee-card bonus eligibility fields from the legacy
Evaluation Exceptions list.

``bonus_eligible`` / ``bonus_evaluation_mode`` were added to hr.employee in
18.0.2.19.0; column creation filled every existing employee with the
defaults (eligible / "Depends on appraisal"). Employees on the legacy
``sl.bonus.evaluation.exception`` list must show "Fixed" instead so their
bonus keeps skipping the appraisal %.

Raw SQL on purpose: the list model was removed in 18.0.2.21.0, so a DB
jumping straight from <2.19.0 to >=2.21.0 replays this script at a point
where the ORM model no longer exists — only the legacy table (if any) does.
"""


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'sl_bonus_evaluation_exception'")
    if not cr.fetchone():
        return
    cr.execute(
        """
        UPDATE hr_employee e
        SET bonus_eligible = TRUE,
            bonus_evaluation_mode = 'fixed'
        FROM sl_bonus_evaluation_exception x
        WHERE x.employee_id = e.id
        """
    )
