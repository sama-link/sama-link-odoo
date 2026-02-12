Problem:
    Worked days doesn't use correct code for compute salary
Inspection:
    hr_payslip.py > HrPayslip > get_worked_day_lines:
        it use leave(resource.calendar.leaves).holiday_id as source of code
        but usually it's false so by default it set as GLOBAL
Solution:
    add work_entry_type(hr.work.entry.type) to avoid using the default GLOBAL