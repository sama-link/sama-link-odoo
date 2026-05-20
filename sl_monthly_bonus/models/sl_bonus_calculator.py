import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SlBonusCalculator(models.AbstractModel):
    """Deterministic bonus calculation engine.

    Public entry point: ``calculate_for_employee(employee, period_start, period_end)``.
    Returns a dict with ``line_vals`` for sl.bonus.batch.line and ``components``
    list (label/value/sequence) for sl.bonus.batch.line.component.

    The engine never writes to other modules. Evaluation % is read read-only.
    """
    _name = 'sl.bonus.calculator'
    _description = 'Monthly Bonus Calculation Engine'

    # ── Public API ────────────────────────────────────────────────────
    @api.model
    def calculate_for_employee(self, employee, period_start, period_end):
        result = self._init_result(employee, period_start, period_end)
        excluded, reason = self._compute_exclusion(employee, period_end)
        if excluded:
            result['line_vals'].update({
                'category': employee.job_id.bonus_category or 'none',
                'is_excluded': True,
                'exclusion_reason': reason,
                'computed_amount': 0.0,
                'bonus_amount': 0.0,
            })
            result['components'].append({
                'sequence': 10, 'label': _('Excluded'),
                'value': reason or _('Excluded'),
            })
            return result

        category = self._resolve_category(employee)
        result['line_vals']['category'] = category
        evaluation_pct, eval_source = self._get_evaluation_percent(employee, period_start, period_end)
        result['line_vals']['evaluation_percent'] = evaluation_pct
        result['line_vals']['evaluation_source'] = eval_source
        # Audit flag: was the 100% fallback used for this employee?
        result['line_vals']['eval_treated_as_full'] = bool(
            evaluation_pct == 100.0
            and self.env.context.get('sl_bonus_treat_missing_eval_as_full')
            and 'treated as 100%' in (eval_source or '')
        )
        # Surface the most common operational issue (no finalized appraisal yet) as a
        # readable, HR-friendly hint on the line. This is set BEFORE the category formula
        # runs so the formula may override with a more specific config issue.
        if evaluation_pct == 0 and category != 'none':
            result['line_vals']['exclusion_reason'] = _(
                "No finalized monthly evaluation (state = 'HR Finalization') was found for this "
                "employee covering %s. Bonus = 0 until the evaluation is approved."
            ) % period_start.strftime('%Y-%m')

        # Dispatch
        method = getattr(self, f'_calc_{category}', None)
        if not method:
            result['line_vals'].update({
                'is_excluded': True,
                'exclusion_reason': _("No formula configured for category %s.") % category,
                'computed_amount': 0.0, 'bonus_amount': 0.0,
            })
            return result
        method(employee, period_start, period_end, evaluation_pct, result)
        # Final value
        computed = round(result['line_vals'].get('computed_amount', 0.0), 2)
        result['line_vals']['computed_amount'] = computed
        result['line_vals']['bonus_amount'] = computed
        return result

    # ── Init / helpers ────────────────────────────────────────────────
    def _init_result(self, employee, period_start, period_end):
        contract = employee._bonus_get_active_contract(on_date=period_end)
        basic = contract.wage if contract else 0.0
        return {
            'line_vals': {
                'employee_id': employee.id,
                'basic_salary': basic,
                'category': 'none',
                'is_excluded': False,
                'evaluation_percent': 0.0,
                'evaluation_source': '',
                'computed_amount': 0.0,
                'bonus_amount': 0.0,
            },
            'components': [],
        }

    def _resolve_category(self, employee):
        return (employee.job_id and employee.job_id.bonus_category) or 'none'

    def _compute_exclusion(self, employee, period_end):
        if employee.bonus_quarterly_exclusion:
            return True, _("Quarterly bonus track (excluded from monthly).")
        if employee._bonus_is_in_probation(period_end):
            return True, _("Employee in probation period.")
        return False, ''

    def _get_evaluation_percent(self, employee, period_start, period_end):
        """Adapter to existing evaluation module — read-only.

        Strategy:
        1. Look for an hr.appraisal record overlapping the period with state
           'hr_finalization' (final). If found, use its total_score.
        2. Else, look for the latest hr_finalization appraisal up to period_end.
        3. Else, return 0% and an explanatory source.

        Honors the per-batch ``treat_missing_eval_as_full`` setting via context:
        if no finalized appraisal exists, the calculator returns 100% with an
        audit-visible source string. The line breakdown will mark this clearly.
        """
        Appraisal = self.env['hr.appraisal'].sudo()
        domain = [
            ('employee_id', '=', employee.id),
            ('state', '=', 'hr_finalization'),
        ]
        # 1. overlap with period
        overlap = Appraisal.search(domain + [
            ('date_from', '<=', period_end),
            ('date_to', '>=', period_start),
        ], order='date_to desc', limit=1)
        if overlap:
            return float(overlap.total_score or 0.0), f"hr.appraisal#{overlap.id}"
        # 2. latest up to period_end
        latest = Appraisal.search(domain + [('date_to', '<=', period_end)],
                                  order='date_to desc', limit=1)
        if latest:
            return float(latest.total_score or 0.0), f"hr.appraisal#{latest.id} (latest before period)"
        # 3. fallback — optionally treat as 100%
        if self.env.context.get('sl_bonus_treat_missing_eval_as_full'):
            return 100.0, _("No finalized appraisal — treated as 100% per batch setting")
        return 0.0, _("No finalized appraisal found")

    def _get_period_staging(self, model_name, employee, period_start, period_end):
        return self.env[model_name].sudo().search([
            ('employee_id', '=', employee.id),
            ('date', '>=', period_start),
            ('date', '<=', period_end),
        ])

    # ── Category formulas ─────────────────────────────────────────────
    def _calc_service(self, employee, period_start, period_end, evaluation_pct, result):
        Rate = self.env['sl.bonus.service.rate'].sudo()
        pct = Rate.get_rate_for(employee.job_id.id, period_end) if employee.job_id else 0.0
        basic = result['line_vals'].get('basic_salary') or 0.0
        amount = basic * (pct / 100.0) * (evaluation_pct / 100.0)
        result['line_vals']['service_pct'] = pct
        result['line_vals']['computed_amount'] = amount
        if pct == 0:
            result['line_vals']['exclusion_reason'] = _(
                "No service-rate configured for job '%s'. Add one under "
                "Bonus → Configuration → Service Rates."
            ) % (employee.job_id.name or '?')
        result['components'].extend([
            {'sequence': 10, 'label': _('Formula'), 'value': _('basic × service% × evaluation%')},
            {'sequence': 20, 'label': _('Basic Salary'), 'value': f"{basic:,.2f}"},
            {'sequence': 30, 'label': _('Service %'), 'value': f"{pct:,.2f}%"},
            {'sequence': 40, 'label': _('Evaluation %'), 'value': f"{evaluation_pct:,.2f}%"},
            {'sequence': 50, 'label': _('Result'), 'value': f"{amount:,.2f}"},
        ])
        if pct == 0:
            result['components'].append({
                'sequence': 5, 'label': _('Warning'),
                'value': _('No service-rate configured — bonus will be 0.'),
            })

    def _calc_sales(self, employee, period_start, period_end, evaluation_pct, result):
        Target = self.env['sl.bonus.target'].sudo()
        target = Target.find_for(employee.id, period_start)
        sales = sum(self._get_period_staging(
            'sl.bonus.edara.staging.sales', employee, period_start, period_end
        ).filtered('is_collected').mapped('amount'))
        target_amount = target.target_amount if target else 0.0
        achievement_pct = (sales / target_amount * 100.0) if target_amount else 0.0
        tier = target.get_tier_for_achievement(achievement_pct) if target else False
        tier_commission = tier.commission_amount if tier else 0.0
        if not target:
            result['line_vals']['exclusion_reason'] = _(
                "No monthly sales target configured for this employee for %s. "
                "Add one under Bonus → Configuration → Sales Targets."
            ) % period_start.strftime('%Y-%m')
        # Threshold: full commission at the highest tier reached.
        # 50% of commission paid fully + 50% scaled by evaluation%
        fixed_half = tier_commission * 0.5
        eval_half = tier_commission * 0.5 * (evaluation_pct / 100.0)
        amount = fixed_half + eval_half
        result['line_vals'].update({
            'target_amount': target_amount,
            'achieved_amount': sales,
            'achievement_percent': achievement_pct,
            'tier_name': tier.name if tier else (_('No tier reached') if target else _('No target configured')),
            'tier_commission': tier_commission,
            'computed_amount': amount,
        })
        result['components'].extend([
            {'sequence': 10, 'label': _('Formula'),
             'value': _('(tier × 50%) + (tier × 50% × evaluation%)')},
            {'sequence': 20, 'label': _('Target'), 'value': f"{target_amount:,.2f}"},
            {'sequence': 30, 'label': _('Achieved (collected)'), 'value': f"{sales:,.2f}"},
            {'sequence': 40, 'label': _('Achievement %'), 'value': f"{achievement_pct:,.2f}%"},
            {'sequence': 50, 'label': _('Tier'),
             'value': tier.name if tier else (_('No tier reached') if target else _('No target configured'))},
            {'sequence': 60, 'label': _('Tier Commission'), 'value': f"{tier_commission:,.2f}"},
            {'sequence': 70, 'label': _('Fixed half (50%)'), 'value': f"{fixed_half:,.2f}"},
            {'sequence': 80, 'label': _('Eval-scaled half (50% × eval%)'), 'value': f"{eval_half:,.2f}"},
            {'sequence': 90, 'label': _('Evaluation %'), 'value': f"{evaluation_pct:,.2f}%"},
            {'sequence': 100, 'label': _('Result'), 'value': f"{amount:,.2f}"},
        ])

    def _calc_stock(self, employee, period_start, period_end, evaluation_pct, result):
        Rate = self.env['sl.bonus.stock.commission.rate'].sudo()
        rate_pct = Rate.get_rate_for(employee.job_id.id if employee.job_id else False, period_end)
        stock_value = sum(self._get_period_staging(
            'sl.bonus.edara.staging.stock', employee, period_start, period_end
        ).mapped('stock_sales_value'))
        amount = stock_value * (rate_pct / 100.0) * (evaluation_pct / 100.0)
        result['line_vals'].update({
            'stock_sales_value': stock_value,
            'stock_commission_pct': rate_pct,
            'computed_amount': amount,
        })
        if rate_pct == 0:
            result['line_vals']['exclusion_reason'] = _(
                "No stock commission rate configured. "
                "Add one under Bonus → Configuration → Stock Commission."
            )
        result['components'].extend([
            {'sequence': 10, 'label': _('Formula'),
             'value': _('stock_sales × commission% × evaluation%')},
            {'sequence': 20, 'label': _('Stock Sales Value'), 'value': f"{stock_value:,.2f}"},
            {'sequence': 30, 'label': _('Commission %'), 'value': f"{rate_pct:,.4f}%"},
            {'sequence': 40, 'label': _('Evaluation %'), 'value': f"{evaluation_pct:,.2f}%"},
            {'sequence': 50, 'label': _('Result'), 'value': f"{amount:,.2f}"},
        ])

    def _calc_installation(self, employee, period_start, period_end, evaluation_pct, result):
        Rate = self.env['sl.bonus.installation.rate'].sudo()
        fixed = Rate.get_amount_for(employee.job_id.id, period_end) if employee.job_id else 0.0
        amount = fixed * (evaluation_pct / 100.0)
        result['line_vals'].update({
            'installation_fixed_amount': fixed,
            'computed_amount': amount,
        })
        if fixed == 0:
            result['line_vals']['exclusion_reason'] = _(
                "No installation fixed amount configured for job '%s'. "
                "Add one under Bonus → Configuration → Installation Fixed Bonus."
            ) % (employee.job_id.name or '?')
        result['components'].extend([
            {'sequence': 10, 'label': _('Formula'), 'value': _('fixed × evaluation%')},
            {'sequence': 20, 'label': _('Fixed Amount'), 'value': f"{fixed:,.2f}"},
            {'sequence': 30, 'label': _('Evaluation %'), 'value': f"{evaluation_pct:,.2f}%"},
            {'sequence': 40, 'label': _('Result'), 'value': f"{amount:,.2f}"},
        ])

    def _calc_branch_manager(self, employee, period_start, period_end, evaluation_pct, result):
        BranchProfit = self.env['sl.bonus.branch.profit'].sudo()
        ManagerRate = self.env['sl.bonus.branch.manager.rate'].sudo()
        branch_profit = BranchProfit.find_approved(
            employee.work_location_id.id if employee.work_location_id else False, period_start,
        )
        if not branch_profit:
            branch_label = employee.work_location_id.name or _('this branch')
            result['line_vals'].update({
                'is_excluded': True,
                'exclusion_reason': _(
                    "Approved branch profitability factor missing for %(branch)s in %(period)s. "
                    "Finance must enter and approve the factor under "
                    "Bonus → Branch Profitability before this manager bonus can be paid."
                ) % {'branch': branch_label, 'period': period_start.strftime('%Y-%m')},
                'computed_amount': 0.0,
            })
            result['components'].append({
                'sequence': 10, 'label': _('Excluded'),
                'value': result['line_vals']['exclusion_reason'],
            })
            return
        factor = branch_profit.factor
        pct = ManagerRate.get_percentage_for(
            employee.job_id.id if employee.job_id else False, factor, period_end,
        )
        basic = result['line_vals'].get('basic_salary') or 0.0
        amount = basic * (pct / 100.0) * (evaluation_pct / 100.0)
        if pct == 0:
            result['line_vals']['exclusion_reason'] = _(
                "No branch manager rate configured for job '%(job)s'. "
                "Add one under Bonus → Configuration → Branch Manager Rates."
            ) % {'job': employee.job_id.name or '?'}
        result['line_vals'].update({
            'branch_profit_factor': factor,
            'branch_manager_pct': pct,
            'computed_amount': amount,
        })
        result['components'].extend([
            {'sequence': 10, 'label': _('Formula'),
             'value': _('basic × branch_tier_% × evaluation%')},
            {'sequence': 20, 'label': _('Basic Salary'), 'value': f"{basic:,.2f}"},
            {'sequence': 30, 'label': _('Branch Profit Factor'), 'value': f"{factor:,.3f}"},
            {'sequence': 40, 'label': _('Tier %'), 'value': f"{pct:,.2f}%"},
            {'sequence': 50, 'label': _('Evaluation %'), 'value': f"{evaluation_pct:,.2f}%"},
            {'sequence': 60, 'label': _('Result'), 'value': f"{amount:,.2f}"},
        ])

    def _calc_none(self, employee, period_start, period_end, evaluation_pct, result):
        result['line_vals'].update({
            'is_excluded': True,
            'exclusion_reason': _('Job position has no monthly bonus category assigned.'),
            'computed_amount': 0.0,
        })
        result['components'].append({
            'sequence': 10, 'label': _('No bonus'),
            'value': _('Job position has no monthly bonus category.'),
        })
