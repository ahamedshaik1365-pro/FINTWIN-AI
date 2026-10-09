#!/usr/bin/env python3
"""
FinTwin AI - synthetic dataset generator.

Creates 5 linked CSV files describing fictional Indian software employees with
0-5 years of experience: profiles, debts, subscriptions, a subscription catalog
and 12 months of cash-flow history.

ALL DATA IS SYNTHETIC. No real people, accounts or institutions are represented.

Usage:
    python generate_dataset.py                 # 500 users, seed 42, ./data
    python generate_dataset.py --users 2000 --seed 7 --out ./data
"""
import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

SNAPSHOT_DATE = "2025-09-30"          # profile snapshot; history covers the next 12 months
HISTORY_MONTHS = pd.period_range("2025-10", "2026-09", freq="M")

# city: (tier, solo 1BHK rent base INR/month, sampling weight)
CITIES = {
    "Bengaluru": (1, 18000, 0.24), "Hyderabad": (1, 15000, 0.16), "Pune": (1, 13000, 0.14),
    "Chennai": (1, 13000, 0.12), "Gurugram": (1, 20000, 0.07), "Noida": (1, 12000, 0.07),
    "Mumbai": (1, 25000, 0.07), "Kochi": (2, 10000, 0.04), "Coimbatore": (2, 8000, 0.04),
    "Indore": (2, 8000, 0.05),
}
# company type: (fresher gross INR/month, yearly growth, weight, layoff probability in the year)
COMPANIES = {
    "IT Services": (28000, 0.22, 0.38, 0.04),
    "Product": (70000, 0.28, 0.20, 0.05),
    "Startup": (45000, 0.30, 0.17, 0.09),
    "GCC": (55000, 0.27, 0.25, 0.03),
}
ROLES = ["Software Engineer", "Backend Developer", "Frontend Developer", "QA / Test Engineer",
         "Data Analyst", "Data Engineer", "DevOps Engineer", "ML Engineer", "Associate Engineer"]
ROLE_W = [0.24, 0.14, 0.10, 0.10, 0.08, 0.08, 0.07, 0.05, 0.14]

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karthik", "Siddharth", "Rahul", "Nikhil", "Varun",
         "Harsh", "Manish", "Pranav", "Kunal", "Ishaan", "Abhishek", "Suresh", "Vignesh", "Aravind", "Naveen",
         "Ananya", "Diya", "Priya", "Sneha", "Kavya", "Meera", "Neha", "Pooja", "Riya", "Shruti",
         "Divya", "Aishwarya", "Lakshmi", "Swati", "Isha", "Nandini", "Tanvi", "Deepika", "Sowmya", "Harini"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Mehta", "Gupta", "Singh", "Kumar",
        "Menon", "Pillai", "Rao", "Joshi", "Desai", "Kulkarni", "Bhat", "Shetty", "Chopra", "Malhotra",
        "Naidu", "Das", "Banerjee", "Mukherjee", "Agarwal", "Jain", "Kapoor", "Srinivasan", "Krishnan", "Ramesh"]

# Subscription catalog: name, category, duplicate_key, price_min, price_max, popularity, stale_probability
# Prices are APPROXIMATE typical monthly list prices in INR (2025-26), for illustration only.
CATALOG = [
    ("Spotify Premium", "Entertainment", "music", 119, 139, 0.55, 0.12),
    ("YouTube Premium", "Entertainment", "music", 149, 189, 0.35, 0.12),
    ("Apple Music", "Entertainment", "music", 99, 119, 0.12, 0.15),
    ("JioSaavn Pro", "Entertainment", "music", 99, 99, 0.10, 0.20),
    ("Netflix", "Entertainment", "video", 149, 649, 0.50, 0.30),
    ("Prime Video", "Entertainment", "video", 125, 299, 0.55, 0.30),
    ("JioHotstar", "Entertainment", "video", 149, 299, 0.45, 0.35),
    ("SonyLIV", "Entertainment", "video", 99, 399, 0.12, 0.45),
    ("Zee5", "Entertainment", "video", 99, 149, 0.08, 0.50),
    ("Swiggy One", "Food", "food_membership", 149, 199, 0.30, 0.15),
    ("Zomato Gold", "Food", "food_membership", 149, 199, 0.28, 0.15),
    ("Gym Membership", "Health", "fitness", 1000, 2500, 0.30, 0.45),
    ("Fitness App", "Health", "fitness", 300, 1000, 0.15, 0.50),
    ("Google One Storage", "Productivity", "storage", 130, 210, 0.35, 0.35),
    ("iCloud+ Storage", "Productivity", "storage", 75, 219, 0.20, 0.35),
    ("AI Assistant Pro", "Productivity", "ai_tools", 1700, 2000, 0.20, 0.20),
    ("AI Code Assistant", "Productivity", "ai_tools", 800, 1000, 0.15, 0.20),
    ("Online Course Platform", "Learning", "learning", 400, 1200, 0.20, 0.50),
    ("Learning App", "Learning", "learning", 200, 600, 0.10, 0.50),
    ("Professional Network Premium", "Professional", "professional", 1500, 2400, 0.08, 0.50),
    ("News / Magazine App", "Reading", "reading", 99, 250, 0.12, 0.40),
    ("Ebook / Audiobook App", "Reading", "reading", 149, 199, 0.10, 0.40),
    ("Game Subscription", "Gaming", "gaming", 349, 549, 0.10, 0.40),
    ("VPN Service", "Security", "security", 150, 300, 0.10, 0.45),
    ("Domain / Hosting", "Dev Tools", "dev_tools", 200, 500, 0.06, 0.25),
]


# --------------------------------------------------------------------------- helpers
def round_to(x, base):
    return int(round(x / base) * base)


def monthly_in_hand(gross_m):
    """Approx. take-home: employee PF (6% of gross), professional tax, income tax
    under the new regime slabs (FY2025-26, std. deduction 75k, rebate to 12L, 4% cess).
    Marginal relief is ignored; treat as an approximation."""
    annual = gross_m * 12
    taxable = max(0.0, annual - 75000)
    slabs = [(400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15),
             (2000000, 0.20), (2400000, 0.25), (math.inf, 0.30)]
    tax, lower = 0.0, 0.0
    for upper, rate in slabs:
        if taxable > lower:
            tax += (min(taxable, upper) - lower) * rate
        lower = upper
    if taxable <= 1200000:
        tax = 0.0
    tax *= 1.04
    return gross_m - 0.06 * gross_m - tax / 12 - 200


def amortize(principal, monthly_rate_pct, tenure, elapsed):
    """Return (emi, remaining_balance) for a standard reducing-balance loan."""
    r = monthly_rate_pct / 100
    if r == 0:
        emi = principal / tenure
        return emi, principal - emi * elapsed
    emi = principal * r / (1 - (1 + r) ** -tenure)
    bal = principal * (1 + r) ** elapsed - emi * ((1 + r) ** elapsed - 1) / r
    return emi, max(bal, 0.0)


# --------------------------------------------------------------------------- debts
def make_debts(rng, uid, exp, in_hand, next_id):
    rows = []

    def add(name, dtype, principal, rate, tenure, elapsed, revolving=False, balance=None, minimum=None):
        nonlocal next_id
        if revolving:
            bal, mn = balance, minimum
        else:
            emi, bal = amortize(principal, rate, tenure, elapsed)
            mn = emi
        rows.append({
            "debt_id": next_id, "user_id": uid, "name": name, "debt_type": dtype,
            "original_principal": int(principal) if principal else int(bal),
            "balance": round_to(bal, 100), "interest_rate": round(rate, 2),
            "annual_rate_nominal_pct": round(rate * 12, 1),
            "tenure_months": "" if revolving else tenure,
            "months_elapsed": "" if revolving else elapsed,
            "minimum_payment": round_to(mn, 10), "is_revolving": int(revolving),
        })
        next_id += 1

    # credit cards (revolving, ~2.9-3.9 % per month)
    if rng.random() < min(0.55, 0.15 + 0.10 * exp):
        n_cards = rng.choice([1, 2, 3], p=[0.70, 0.25, 0.05])
        for i in range(n_cards):
            bal = round_to(in_hand * rng.uniform(0.1, 1.3), 500)
            if bal < 2000:
                continue
            add(f"Credit Card {chr(65 + i)}", "credit_card", None, rng.uniform(2.9, 3.9), 0, 0,
                revolving=True, balance=bal, minimum=max(200, 0.05 * bal))
    # gadget / no-cost EMI
    if rng.random() < 0.30:
        for _ in range(rng.choice([1, 2], p=[0.8, 0.2])):
            n = int(rng.choice([6, 9, 12, 18, 24]))
            rate = 0.0 if rng.random() < 0.55 else rng.uniform(0.6, 1.1)
            nm = rng.choice(["Laptop EMI", "Phone EMI", "Appliance EMI"], p=[0.35, 0.50, 0.15])
            add(str(nm), "gadget_emi", round_to(rng.uniform(20000, 160000), 1000), rate, n,
                int(rng.integers(0, n - 1)))
    # personal loan
    if rng.random() < 0.06 + 0.04 * exp:
        n = int(rng.integers(12, 49))
        add("Personal Loan", "personal_loan", round_to(rng.lognormal(math.log(150000), 0.6), 5000),
            rng.uniform(0.95, 1.6), n, int(rng.integers(0, n - 2)))
    # education loan
    if rng.random() < 0.26:
        n = int(rng.choice([84, 96, 120]))
        k = int(max(0, exp * 12 - rng.uniform(3, 12)))
        add("Education Loan", "education_loan", round_to(rng.lognormal(math.log(500000), 0.45), 10000),
            rng.uniform(0.70, 0.95), n, min(k, n - 12))
    # vehicle loan
    if exp >= 1.5 and rng.random() < 0.05 + 0.05 * exp:
        if in_hand >= 70000 and rng.random() < 0.4:
            add("Car Loan", "vehicle_loan", round_to(rng.uniform(400000, 900000), 10000),
                rng.uniform(0.75, 1.05), int(rng.choice([48, 60, 72, 84])), int(rng.integers(0, 24)))
        else:
            n = int(rng.choice([24, 30, 36]))
            add("Two-Wheeler Loan", "vehicle_loan", round_to(rng.uniform(70000, 130000), 1000),
                rng.uniform(0.80, 1.10), n, int(rng.integers(0, n - 4)))
    # home loan (rare)
    if exp >= 3 and in_hand >= 120000 and rng.random() < 0.15:
        add("Home Loan", "home_loan", round_to(rng.uniform(2500000, 6000000), 100000),
            rng.uniform(0.68, 0.76), 240, int(rng.integers(0, max(2, int(exp * 12 - 10)))))

    # keep the EMI burden humanly possible (<= 65 % of in-hand pay)
    while rows and sum(r["minimum_payment"] for r in rows) > 0.65 * in_hand:
        rows.pop(int(np.argmin([r["minimum_payment"] for r in rows])))
    return rows, next_id


# --------------------------------------------------------------------------- subscriptions
def make_subs(rng, uid, in_hand, next_id):
    n = int(np.clip(rng.poisson(2.2 + in_hand / 90000), 1, 9))
    pop = np.array([c[5] for c in CATALOG])
    idx = rng.choice(len(CATALOG), size=n, replace=False, p=pop / pop.sum())
    rows = []
    for i in idx:
        name, cat, key, lo, hi, _, stale_p = CATALOG[i]
        amount = lo if lo == hi else round_to(rng.uniform(lo, hi), 10 if hi > 400 else 1)
        if rng.random() < stale_p:
            used = int(rng.integers(31, 151))
        else:
            used = int(rng.integers(0, 26))
        rows.append({"sub_id": next_id, "user_id": uid, "name": name, "category": cat,
                     "amount": amount, "active": 1, "duplicate_key": key, "last_used_days": used})
        next_id += 1
    # recommendation rules (documented in DATA_DICTIONARY.md)
    df = pd.DataFrame(rows)
    acts, why = {}, {}
    for key, g in df.groupby("duplicate_key"):
        keeper = g.sort_values(["last_used_days", "amount"]).iloc[0]
        for _, r in g.iterrows():
            sid = r["sub_id"]
            if len(g) > 1 and sid != keeper["sub_id"]:
                acts[sid], why[sid] = "Cancel", f"Duplicate of {keeper['name']} ({key})"
            elif r["last_used_days"] > 60:
                acts[sid], why[sid] = "Cancel", f"Unused for {r['last_used_days']} days"
            elif r["last_used_days"] > 30:
                acts[sid], why[sid] = "Review", f"Low usage: {r['last_used_days']} days since last use"
            else:
                acts[sid], why[sid] = "Keep", "Actively used"
    df["recommended_action"] = df["sub_id"].map(acts)
    df["reason"] = df["sub_id"].map(why)
    return df.to_dict("records"), next_id


# --------------------------------------------------------------------------- history
def make_history(rng, uid, u, company):
    base_ess, base_disc = u["essentials"], u["discretionary_expenses"]
    salary, emi = u["salary"], u["emi_obligations"]
    infl_m = rng.uniform(0.04, 0.07) / 12
    layoff = rng.random() < COMPANIES[company][3]
    l_start = int(rng.integers(2, 10)) if layoff else None
    l_len = int(rng.integers(2, 7)) if layoff else 0
    appraisal = rng.random() < 0.70 and u["experience_years"] >= 0.5
    hike = rng.uniform(0.05, 0.25) if appraisal else 0.0
    disc_mult = 1.0
    bal = u["savings"]
    rows, min_bal = [], bal
    for t, per in enumerate(HISTORY_MONTHS, start=1):
        events, bonus = [], 0.0
        label, mon = str(per), per.month
        income = salary
        if appraisal and label >= "2026-04":
            income = salary * (1 + hike)
            if label == "2026-04":
                events.append("appraisal")
                disc_mult = 1 + 0.6 * hike            # partial lifestyle creep after a hike
                if rng.random() < (0.7 if company == "Product" else 0.45):
                    bonus += income * rng.uniform(0.3, 1.0)
                    events.append("variable_pay")
        if label == "2025-10" and rng.random() < 0.25:
            bonus += salary * rng.uniform(0.2, 0.5)
            events.append("festival_bonus")
        job_search = False
        if layoff:
            if t == l_start:
                events.append("layoff")
                bonus += salary * rng.uniform(1.0, 3.0)   # severance
            if l_start <= t < l_start + l_len:
                income, job_search = 0.0, True
                events.append("job_search")
            elif t == l_start + l_len:
                salary = salary * rng.uniform(0.9, 1.15)
                income = salary
                events.append("rejoined")
            elif t > l_start + l_len:
                income = salary
        seasonal = {10: 1.25, 11: 1.15, 12: 1.30, 1: 0.95}.get(mon, 1.0)
        infl = (1 + infl_m) ** t
        ess = base_ess * infl * rng.normal(1, 0.03)
        disc = base_disc * disc_mult * infl * seasonal * rng.normal(1, 0.12) * (0.6 if job_search else 1.0)
        ess, disc = max(ess, 0), max(disc, 0)
        net = income + bonus - ess - disc - emi
        bal += net
        min_bal = min(min_bal, bal)
        rows.append({
            "user_id": uid, "month_index": t, "month": label, "income": int(round(income)),
            "bonus": int(round(bonus)), "essential_expenses": int(round(ess)),
            "discretionary_expenses": int(round(disc)), "emi_paid": int(emi),
            "net_cashflow": int(round(net)), "savings_end": int(round(bal)),
            "event": "|".join(events),
        })
    return rows, int(round(bal)), int(round(min_bal)), layoff


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    city_names = list(CITIES)
    city_w = np.array([CITIES[c][2] for c in city_names])
    comp_names = list(COMPANIES)
    comp_w = np.array([COMPANIES[c][2] for c in comp_names])

    users, debts, subs, hist = [], [], [], []
    debt_id = sub_id = 1
    used_names = set()

    for uid in range(1, args.users + 1):
        # --- identity
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names or len(used_names) > 1000:
                used_names.add(name)
                break
        yrs = int(rng.choice(6, p=[0.22, 0.20, 0.18, 0.16, 0.13, 0.11]))
        exp = round(min(5.0, yrs + rng.uniform(0, 0.92)), 1)
        city = str(rng.choice(city_names, p=city_w / city_w.sum()))
        tier, rent_base, _ = CITIES[city]
        company = str(rng.choice(comp_names, p=comp_w / comp_w.sum()))
        fresher, growth, _, _ = COMPANIES[company]
        role = str(rng.choice(ROLES, p=ROLE_W))
        age = int(np.clip(round(21.5 + exp + rng.uniform(0, 3)), 21, 31))

        # --- income
        gross = int(np.clip(round_to(fresher * (1 + growth) ** exp * rng.lognormal(0, 0.16), 500), 22000, 600000))
        in_hand = round_to(monthly_in_hand(gross), 100)

        # --- housing & essentials
        p_family = 0.30 if tier == 2 else 0.18
        housing = str(rng.choice(["Family home", "Shared rental", "Solo rental"],
                                 p=[p_family, 0.42, 0.58 - p_family]))
        factor = float(np.clip(0.8 + 0.5 * in_hand / 150000, 0.8, 1.5)) * rng.lognormal(0, 0.10)
        rent = {"Family home": 0, "Shared rental": rent_base * 0.55 * factor, "Solo rental": rent_base * factor}[housing]
        rent = round_to(min(rent, 0.40 * in_hand), 500)
        supports = bool(rng.random() < 0.40)
        family = round_to(in_hand * rng.uniform(0.05, 0.15), 500) if supports else 0
        food = 5000 + 0.05 * in_hand * rng.uniform(0.8, 1.2)
        util = 2200 + 300 * rng.random()
        transport = 1500 + 0.025 * in_hand
        health = 800 + 0.01 * in_hand
        essentials = round_to(rent + family + food + util + transport + health, 100)

        # --- lifestyle
        lifestyle = str(rng.choice(["Frugal", "Balanced", "Spender"], p=[0.30, 0.50, 0.20]))
        lo, hi = {"Frugal": (0.10, 0.18), "Balanced": (0.18, 0.28), "Spender": (0.28, 0.45)}[lifestyle]
        disc = round_to(in_hand * rng.uniform(lo, hi), 500)

        # --- debts
        d_rows, debt_id = make_debts(rng, uid, exp, in_hand, debt_id)
        emi = int(sum(r["minimum_payment"] for r in d_rows))
        if essentials + disc + emi > 1.00 * in_hand:           # keep most people roughly solvent
            disc = max(round_to(0.05 * in_hand, 500), round_to(1.00 * in_hand - essentials - emi, 500))
        debts += d_rows
        expenses = essentials + disc

        # --- savings & emergency fund
        months_saved = (0.6 + 0.9 * exp) * rng.lognormal(0, 0.6)
        savings = round_to(in_hand * min(months_saved, 18) * (1 - min(0.6, emi / in_hand)), 1000)
        fund = 0 if rng.random() < 0.20 else round_to(savings * rng.uniform(0.10, 0.90), 1000)

        # --- year-ago values (for lifestyle-inflation checks)
        if exp >= 1.0:
            hike = rng.uniform(0.04, 0.30)
            inflating = rng.random() < 0.30
            dgrow = hike * rng.uniform(1.1, 1.8) + 0.04 if inflating else hike * rng.uniform(0.2, 0.9)
            prev_salary, prev_disc = round_to(in_hand / (1 + hike), 100), round_to(disc / (1 + dgrow), 500)
        else:
            prev_salary = prev_disc = ""

        u = {"user_id": uid, "name": name, "age": age, "city": city, "city_tier": tier,
             "company_type": company, "role": role, "career_stage": "0-5 years",
             "experience_years": exp, "housing_type": housing, "supports_family": int(supports),
             "lifestyle_type": lifestyle, "monthly_gross": gross, "salary": in_hand,
             "essentials": essentials, "discretionary_expenses": disc, "monthly_expenses": expenses,
             "emi_obligations": emi, "savings": savings, "current_fund": fund,
             "previous_salary": prev_salary, "previous_discretionary": prev_disc}

        # --- history (also yields the 12-month outcome labels)
        h_rows, end_sav, min_sav, laid_off = make_history(rng, uid, u, company)
        hist += h_rows

        # --- subscriptions
        s_rows, sub_id = make_subs(rng, uid, in_hand, sub_id)
        subs += s_rows
        s_df = pd.DataFrame(s_rows)

        # --- derived labels (mirror the project's module logic)
        ratio = emi / in_hand
        u.update({
            "emi_ratio": round(ratio, 4),
            "emi_status": "Healthy" if ratio < 0.30 else ("Warning" if ratio <= 0.40 else "Critical"),
            "emi_stress_score": int(round(min(100, ratio / 0.5 * 100))),
            "wants_cap": round(0.30 * in_hand), "overspend": max(0, disc - round(0.30 * in_hand)),
            "fund_target_low": 6 * expenses, "fund_target_high": 12 * expenses,
            "fund_progress_pct": round(fund / (6 * expenses) * 100, 1),
            "fund_months_covered": round(fund / expenses, 2),
            "monthly_surplus": in_hand - expenses - emi,
            "subs_monthly_total": int(s_df["amount"].sum()),
            "subs_potential_savings": int(s_df.loc[s_df["recommended_action"] == "Cancel", "amount"].sum()),
        })
        if exp >= 1.0:
            sg, dg = in_hand / prev_salary - 1, disc / prev_disc - 1
            u["lifestyle_inflation_flag"] = int(dg - sg > 0.02)
        else:
            u["lifestyle_inflation_flag"] = ""
        u.update({"had_layoff_in_year": int(laid_off), "min_savings_12m": min_sav,
                  "savings_12m_actual": end_sav,
                  "risk_flag_12m": "High" if min_sav < 0 else ("Medium" if end_sav < 3 * (expenses + emi) else "Low")})
        users.append(u)

    pd.DataFrame(users).to_csv(out / "users.csv", index=False)
    pd.DataFrame(debts).to_csv(out / "debts.csv", index=False)
    pd.DataFrame(subs).to_csv(out / "subscriptions.csv", index=False)
    pd.DataFrame(hist).to_csv(out / "monthly_history.csv", index=False)
    pd.DataFrame(CATALOG, columns=["name", "category", "duplicate_key", "price_min_inr", "price_max_inr",
                                   "popularity_weight", "stale_probability"]
                 ).to_csv(out / "subscription_catalog.csv", index=False)
    print(f"Wrote {len(users)} users, {len(debts)} debts, {len(subs)} subscriptions, "
          f"{len(hist)} history rows to {out.resolve()}")


if __name__ == "__main__":
    main()
