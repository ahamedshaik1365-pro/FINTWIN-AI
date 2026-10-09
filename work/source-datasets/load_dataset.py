#!/usr/bin/env python3
"""
Load the FinTwin synthetic dataset into the project's SQLite database
(tables: user_profile, subscriptions, debts, as defined in backend/database.py).

Examples:
    python load_dataset.py --db backend/fintwin.db --reset --limit 50
    python load_dataset.py --db backend/fintwin.db --reset --user-ids 1 2 3
    python load_dataset.py --db backend/fintwin.db            # append, keeps existing rows

NOTE: backend/seed.py only seeds when user_profile is empty, so loading real
data with --reset means the demo user is replaced by dataset users.
The first loaded user gets id 1 (sequences are reset with --reset).
"""
import argparse
import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, career_stage TEXT NOT NULL,
    salary REAL NOT NULL, monthly_expenses REAL NOT NULL, emi_obligations REAL NOT NULL, savings REAL NOT NULL);
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
    amount REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, duplicate_key TEXT, last_used_days INTEGER,
    FOREIGN KEY(user_id) REFERENCES user_profile(id));
CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, balance REAL NOT NULL,
    interest_rate REAL NOT NULL, minimum_payment REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES user_profile(id));
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="folder containing the CSV files")
    ap.add_argument("--db", default="backend/fintwin.db")
    ap.add_argument("--limit", type=int, default=25, help="max users to load (ignored with --user-ids)")
    ap.add_argument("--user-ids", type=int, nargs="*", help="load only these dataset user_ids")
    ap.add_argument("--reset", action="store_true", help="delete existing rows first")
    a = ap.parse_args()

    data = Path(a.data)
    users = pd.read_csv(data / "users.csv")
    debts = pd.read_csv(data / "debts.csv")
    subs = pd.read_csv(data / "subscriptions.csv")
    users = users[users.user_id.isin(a.user_ids)] if a.user_ids else users.head(a.limit)

    Path(a.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(a.db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    if a.reset:
        conn.executescript("DELETE FROM subscriptions; DELETE FROM debts; DELETE FROM user_profile; "
                           "DELETE FROM sqlite_sequence WHERE name IN ('subscriptions','debts','user_profile');")
    cur = conn.cursor()
    n_d = n_s = 0
    for u in users.itertuples():
        cur.execute("INSERT INTO user_profile (name, career_stage, salary, monthly_expenses, emi_obligations, savings) "
                    "VALUES (?,?,?,?,?,?)",
                    (u.name, u.career_stage, u.salary, u.monthly_expenses, u.emi_obligations, u.savings))
        new_id = cur.lastrowid
        for d in debts[debts.user_id == u.user_id].itertuples():
            cur.execute("INSERT INTO debts (user_id, name, balance, interest_rate, minimum_payment) VALUES (?,?,?,?,?)",
                        (new_id, d.name, d.balance, d.interest_rate, d.minimum_payment))
            n_d += 1
        for s in subs[subs.user_id == u.user_id].itertuples():
            cur.execute("INSERT INTO subscriptions (user_id, name, category, amount, active, duplicate_key, last_used_days) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (new_id, s.name, s.category, s.amount, s.active, s.duplicate_key, s.last_used_days))
            n_s += 1
    conn.commit()
    conn.close()
    print(f"Loaded {len(users)} users, {n_d} debts, {n_s} subscriptions into {a.db}")


if __name__ == "__main__":
    main()
