from odoo import models, api


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    # Arabic (ar_001) names per rule code, applied on module update. Kept in code so
    # they deploy to every database (MCP/RPC cannot carry Arabic reliably).
    _SAMALINK_AR_NAMES = {
        'ABSENT_PENALTY': 'جزاء الغياب بدون إذن',
        'ADMIN_PENALTY': 'الجزاءات الإدارية',
        'ADVANCE': 'السلف',
        'BASIC': 'الراتب الأساسي',
        'BASIC_SALARY': 'الراتب',
        'DA': 'بدل غلاء المعيشة',
        'GROSS': 'الإجمالي',
        'HOLIDAY_BONUS': 'بدل الاجازات الرسمية',
        'HOUR_WAGE': 'الأجر بالساعة',
        'HRA': 'بدل السكن',
        'INCENTIV': 'المكافآت',
        'LATE': 'تأخير إداري',
        'LATE_PENALTY': 'جزاء تأخير / انصراف مبكر',
        'Meal': 'بدل الوجبات',
        'Medical': 'بدل طبي',
        'NET': 'صافي الراتب',
        'NET_H': 'صافي الراتب بالساعة',
        'OTH': 'تسويات ادارية',
        'Other': 'بدلات أخرى',
        'OVERTIME_HOURS': 'الوقت الإضافي',
        'PAID_HOLIDAY_BONUS': 'بدل الاجازات المدفوعة',
        'PRESENT_DAYS': 'أيام الحضور',
        'REST_ALLOW': 'بدل ايام الراحة',
        'SALARY': 'الراتب الأساسي',
        'SICK_HOLIDAY_BONUS': 'بدل اجازة مرضية',
        'Travel': 'بدل الانتقال',
    }

    @api.model
    def _samalink_load_ar_names(self):
        """Set the Arabic (ar_001) translation of each salary rule name by code.
        Called from data on module install/update; idempotent. No-op if ar_001
        is not an installed language."""
        if not self.env['res.lang'].search_count([('code', '=', 'ar_001')]):
            return
        for code, ar_name in self._SAMALINK_AR_NAMES.items():
            for rule in self.with_context(active_test=False).search([('code', '=', code)]):
                rule.update_field_translations('name', {'ar_001': ar_name})
