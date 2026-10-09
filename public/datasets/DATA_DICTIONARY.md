# FinTwin AI – Synthetic Dataset

Fictional Indian software employees with **0–5 years** of experience. **All data is synthetic**: no real people, accounts or employers. It is *plausible*, not calibrated to a survey, so use it for demos, testing and prototyping, not for conclusions about real people.

Regenerate or scale it: `python generate_dataset.py --users 2000 --seed 7 --out data`

## Files

| File | Rows | Grain | Purpose |
|---|---|---|---|
| `users.csv` | 500 | one per user | Profile snapshot + derived labels for every module |
| `debts.csv` | 703 | one per loan/card | Input for Debt Detox + EMI Stress |
| `subscriptions.csv` | 1,536 | one per subscription | Input for Subscription Optimizer (with answer labels) |
| `monthly_history.csv` | 6,000 | user × month (12 each) | Ground truth to validate the Digital Twin |
| `subscription_catalog.csv` | 25 | one per service | Lookup used to generate subscriptions |

Keys: `users.user_id` ← `debts.user_id`, `subscriptions.user_id`, `monthly_history.user_id`.
Snapshot date is **2025-09-30**; history covers **2025-10 → 2026-09**. All money is INR per month unless stated.

## users.csv

| Column | Meaning |
|---|---|
| user_id, name, age | Identity (names are random combinations) |
| city, city_tier | 10 cities; tier 1 = metros, 2 = smaller tech hubs |
| company_type | IT Services / Product / Startup / GCC |
| role, career_stage | Job role; always `0-5 years` (matches `user_profile.career_stage`) |
| experience_years | 0.0–5.0 |
| housing_type, supports_family | Family home / Shared rental / Solo rental; 1 = sends money home |
| lifestyle_type | Frugal / Balanced / Spender (drives discretionary share) |
| monthly_gross | Gross monthly pay |
| **salary** | **In-hand (take-home) monthly pay**, used as the app's `salary` |
| essentials | Rent + family support + food + utilities + transport + health |
| discretionary_expenses | Wants: dining, shopping, travel, entertainment |
| **monthly_expenses** | essentials + discretionary, **excluding EMIs** |
| emi_obligations | Sum of `minimum_payment` in `debts.csv` for the user |
| savings | Total liquid savings/investments at snapshot (**includes** `current_fund`) |
| current_fund | Dedicated emergency fund (0 for ~21% of users) |
| previous_salary, previous_discretionary | Values 12 months earlier (blank if experience < 1 yr) |

**Derived labels (use as expected outputs for the endpoints)**

| Column | Rule |
|---|---|
| emi_ratio, emi_status | `emi / salary`; Healthy < 30%, Warning 30–40%, Critical > 40% |
| emi_stress_score | `min(100, emi_ratio / 0.5 × 100)` (dataset-defined) |
| wants_cap, overspend | 30% of salary; `max(0, discretionary − wants_cap)` |
| fund_target_low / high | 6× / 12× `monthly_expenses` |
| fund_progress_pct, fund_months_covered | `current_fund / target_low × 100`; `current_fund / monthly_expenses` |
| monthly_surplus | `salary − monthly_expenses − emi_obligations` (can be negative) |
| subs_monthly_total, subs_potential_savings | Sum of all subs; sum of those marked Cancel |
| lifestyle_inflation_flag | 1 if discretionary grew > 2 points faster than salary vs 12 months ago |
| had_layoff_in_year, min_savings_12m, savings_12m_actual | Outcomes taken from `monthly_history.csv` |
| risk_flag_12m | High: savings dipped below 0; Medium: ended < 3× (expenses + EMI); else Low |

## debts.csv
`debt_id, user_id, name, debt_type, original_principal, balance, interest_rate, annual_rate_nominal_pct, tenure_months, months_elapsed, minimum_payment, is_revolving`

- **`interest_rate` is a MONTHLY percentage** (3.5 = 3.5% per month); `annual_rate_nominal_pct` = ×12. Matches the units in the project's seed data.
- Types: `credit_card` (revolving, 2.9–3.9%/mo, minimum = 5% of balance, floor ₹200), `gadget_emi` (0% for ~55%), `personal_loan`, `education_loan`, `vehicle_loan`, `home_loan` (rare).
- Instalment loans use the standard reducing-balance EMI formula; `balance` is the remaining principal after `months_elapsed` payments. Tenure/elapsed are blank for revolving debt.

## subscriptions.csv
`sub_id, user_id, name, category, amount, active, duplicate_key, last_used_days, recommended_action, reason`

Label rules: within one `duplicate_key`, keep the most-recently-used (tie → cheaper) and mark the rest **Cancel** ("Duplicate of …"); otherwise `last_used_days` > 60 → **Cancel**, 31–60 → **Review**, ≤ 30 → **Keep**. Catalog prices are approximate list prices for illustration; verify before showing as fact.

## monthly_history.csv
`user_id, month_index, month, income, bonus, essential_expenses, discretionary_expenses, emi_paid, net_cashflow, savings_end, event`

- `savings_end(t) = savings_end(t−1) + income + bonus − essentials − discretionary − emi`; month 0 = `users.savings`. Can go **negative** (modelled as a shortfall).
- `event` (pipe-separated): `appraisal`, `variable_pay`, `festival_bonus`, `layoff` (income 0 + severance), `job_search`, `rejoined`.
- Includes 4–6% yearly expense inflation, festive-season spending peaks (Oct–Dec), a 60% spending cut during job search, and partial lifestyle creep after a raise.
- EMIs stay constant (no extra repayments), and debt balances in `debts.csv` are not updated over the year.

## Summary of the generated data

| Check | Result |
|---|---|
| Median in-hand salary | ₹70,800 (fresher ≈ ₹42.6k → 4–5 yrs ≈ ₹140k) |
| EMI status | 444 Healthy, 24 Warning, 32 Critical |
| 12-month risk | 390 Low, 79 Medium, 31 High |
| Lifestyle inflation flag | 123 flagged, 264 not, 113 n/a (< 1 yr experience) |
| Negative monthly surplus | 13.8% of users |
| Users with ≥ 1 debt | 381 of 500 |
| Users with a duplicate subscription | 31% |
| Layoffs in the year | 23 users |
| Integrity | No duplicate IDs; all foreign keys valid; `emi_obligations` = sum of debt minimums; history month 12 = `savings_12m_actual` |

## Using it with the project

```python
import pandas as pd
u = pd.read_csv("users.csv"); d = pd.read_csv("debts.csv")

# POST /api/emi        -> compare with emi_ratio / emi_status
# POST /api/fund       -> compare with fund_target_low/high, fund_progress_pct
# POST /api/subs       -> compare with recommended_action, subs_potential_savings
# POST /api/twin       -> feed salary, monthly_expenses, emi_obligations, savings;
#                         compare with savings_12m_actual / risk_flag_12m
```

Load users into the app's database: `python load_dataset.py --db backend/fintwin.db --reset --limit 25`

## Limitations
- Distributions are hand-designed, not fitted to real data; tax is an approximation (new-regime slabs, no marginal relief, no HRA/80C).
- No gender, caste, religion or other sensitive attributes are included. Any model trained on this reflects only these assumptions.
- Not financial advice.
