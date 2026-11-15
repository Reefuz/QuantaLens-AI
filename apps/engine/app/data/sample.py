"""Synthetic, deliberately messy banking transactions.

All data is randomly generated (fixed seed). No real customers. `generate_sample` returns the CSV text plus a
manifest of the mess it injected, so tests can check the profiler against ground truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import re

import numpy as np
import pandas as pd

SAMPLE_NAME = "Synthetic banking transactions (demo)"
SAMPLE_FILENAME = "synthetic_banking_transactions.csv"
SAMPLE_QUESTIONS = [
    "What is the total transaction volume?",
    "Which customer segment contributes the highest transaction value?",
    "Analyse monthly transaction trends.",
    "Identify unusual transaction patterns.",
    "Compare successful and failed transactions.",
    "Identify potential data quality issues.",
    "What are the top three business insights?",
]

SEGMENTS = {  # name: (share, median amount, age range, income median)
    "Retail": (0.60, 85.0, (22, 80), 2600),
    "Student": (0.20, 25.0, (18, 25), 900),
    "Business": (0.15, 900.0, (28, 65), 5200),
    "Private Banking": (0.05, 2500.0, (35, 80), 14000),
}
BRANCHES = ["London", "Manchester", "Birmingham", "Leeds", "Edinburgh", "Glasgow", "Bristol", "Cardiff"]
START, END = pd.Timestamp("2024-01-01"), pd.Timestamp("2025-06-30")


@dataclass
class SampleResult:
    csv_text: str
    manifest: dict = field(default_factory=dict)


def _pick(rng: np.random.Generator, n: int, share: float) -> np.ndarray:
    return rng.choice(n, size=int(round(n * share)), replace=False)


def generate_sample(n_unique: int = 12000, seed: int = 42) -> SampleResult:
    rng = np.random.default_rng(seed)
    manifest: dict = {}

    # ── customers ─────────────────────────────────────────────────────────
    n_customers = 1500
    seg_names = list(SEGMENTS)
    seg_probs = np.array([SEGMENTS[s][0] for s in seg_names])
    cust_seg = rng.choice(seg_names, size=n_customers, p=seg_probs)
    cust_age = np.array([rng.integers(*SEGMENTS[s][2]) for s in cust_seg])
    cust_income = np.array([SEGMENTS[s][3] * rng.lognormal(0, 0.35) for s in cust_seg]).round(0).astype(int)
    cust_branch = rng.choice(BRANCHES, size=n_customers)
    weights = rng.gamma(2.0, 1.0, n_customers)
    weights[rng.choice(n_customers, 10, replace=False)] *= 12  # a few unusually active customers
    weights /= weights.sum()
    cust_idx = rng.choice(n_customers, size=n_unique, p=weights)

    # ── dates: gentle growth, December lift ───────────────────────────────
    days = (END - START).days + 1
    day_axis = np.arange(days)
    month_of = (START + pd.to_timedelta(day_axis, unit="D"))
    w = 1.0 + 0.9 * day_axis / days
    w = w * np.where(month_of.month == 12, 1.35, 1.0)
    w /= w.sum()
    day_idx = np.sort(rng.choice(days, size=n_unique, p=w))
    dates = START + pd.to_timedelta(day_idx, unit="D")

    seg = cust_seg[cust_idx]
    # Business grows, Student declines over time: gives the agent real trends to find.
    progress = day_idx / days
    keep = np.where(seg == "Student", rng.random(n_unique) > 0.5 * progress, True)
    keep &= np.where(seg == "Business", rng.random(n_unique) < (0.65 + 0.35 * progress), True)
    cust_idx, dates, seg, day_idx = cust_idx[keep], dates[keep], seg[keep], day_idx[keep]
    n = len(cust_idx)

    ttype = rng.choice(["Deposit", "Withdrawal", "Transfer", "Payment"], size=n, p=[0.25, 0.25, 0.20, 0.30])
    median = np.array([SEGMENTS[s][1] for s in seg]) * np.where(ttype == "Transfer", 2.2, 1.0)
    amount = (median * rng.lognormal(0, 0.9, n)).round(2)
    status = rng.choice(["Completed", "Failed", "Pending"], size=n, p=[0.90, 0.06, 0.04])
    method = rng.choice(["Card", "Mobile App", "Bank Transfer", "Cash"], size=n, p=[0.45, 0.25, 0.20, 0.10])
    acct = np.where(
        seg == "Business", "Business", rng.choice(["Current", "Savings", "Credit"], size=n, p=[0.65, 0.27, 0.08])
    )

    df = pd.DataFrame(
        {
            "transaction_id": [f"TXN-{i:06d}" for i in range(1, n + 1)],
            "customer_id": [f"CUST-{c + 1:05d}" for c in cust_idx],
            "customer_segment": seg,
            "transaction_date": dates,
            "transaction_type": ttype,
            "transaction_amount": amount,
            "transaction_status": status,
            "payment_method": method,
            "branch": cust_branch[cust_idx],
            "account_type": acct,
            "customer_age": cust_age[cust_idx].astype(object),
            "monthly_income": cust_income[cust_idx].astype(object),
        }
    )
    clean_truth = {
        "rows_before_mess": n,
        "total_amount_all_rows_numeric": float(amount.sum()),
    }

    # ── dates in mixed formats ────────────────────────────────────────────
    fmt = rng.choice(["iso", "dmy_slash", "dd_mon_yyyy", "mon_d_yyyy"], size=n, p=[0.65, 0.20, 0.09, 0.06])
    d = df["transaction_date"]
    date_str = np.where(
        fmt == "iso", d.dt.strftime("%Y-%m-%d"),
        np.where(fmt == "dmy_slash", d.dt.strftime("%d/%m/%Y"),
        np.where(fmt == "dd_mon_yyyy", d.dt.strftime("%d-%b-%Y"), d.dt.strftime("%b ") + d.dt.day.astype(str) + d.dt.strftime(", %Y"))),
    ).astype(object)
    miss_date = _pick(rng, n, 0.005)
    date_str[miss_date] = None
    df["transaction_date"] = date_str
    manifest["date_format_counts"] = {k: int((fmt[np.setdiff1d(np.arange(n), miss_date)] == k).sum()) for k in ["iso", "dmy_slash", "dd_mon_yyyy", "mon_d_yyyy"]}
    manifest["missing_dates"] = int(len(miss_date))

    # ── amounts: currency formatting, invalid text, missing, outliers ─────
    amt = df["transaction_amount"].astype(object)
    out_idx = rng.choice(n, 40, replace=False)
    amt.iloc[out_idx] = (amount[out_idx] * rng.uniform(150, 400, 40)).round(2)  # injected outliers
    manifest["injected_amount_outliers"] = 40
    rest = np.setdiff1d(np.arange(n), out_idx)
    fmt_idx = rng.choice(rest, int(n * 0.05), replace=False)
    kinds = rng.choice(["gbp_symbol", "gbp_code", "thousands"], size=len(fmt_idx), p=[0.6, 0.2, 0.2])
    for i, k in zip(fmt_idx, kinds):
        v = float(amt.iloc[i])
        amt.iloc[i] = f"£{v:,.2f}" if k == "gbp_symbol" else (f"GBP {v:.2f}" if k == "gbp_code" else f"{v:,.2f}")
    # "thousands" values under 1,000 have no comma, so they are plain numbers. Count only detectable formatting.
    manifest["formatted_amounts"] = int(sum(1 for i in fmt_idx if re.search(r"[£,]|GBP", str(amt.iloc[i]))))
    rest2 = np.setdiff1d(rest, fmt_idx)
    bad_idx = rng.choice(rest2, 25, replace=False)
    amt.iloc[bad_idx] = rng.choice(["TBC", "pending", "see notes"], 25)
    manifest["invalid_amounts"] = 25
    miss_amt = rng.choice(np.setdiff1d(rest2, bad_idx), int(n * 0.006), replace=False)
    amt.iloc[miss_amt] = None
    manifest["missing_amounts"] = int(len(miss_amt))
    df["transaction_amount"] = amt

    # ── customer ids ──────────────────────────────────────────────────────
    miss_cust = _pick(rng, n, 0.01)
    df.loc[df.index[miss_cust], "customer_id"] = None
    manifest["missing_customer_ids"] = int(len(miss_cust))

    # ── inconsistent categories and whitespace ────────────────────────────
    def vary(col: str, share: float) -> int:
        idx = _pick(rng, n, share)
        for i in idx:
            v = str(df.iloc[i, df.columns.get_loc(col)])
            choice = rng.integers(0, 3)
            df.iloc[i, df.columns.get_loc(col)] = v.lower() if choice == 0 else (v.upper() if choice == 1 else v + " ")
        return len(idx)

    manifest["segment_variants"] = vary("customer_segment", 0.08)
    manifest["status_variants"] = vary("transaction_status", 0.05)
    pm_idx = _pick(rng, n, 0.06)
    for i in pm_idx:
        j = df.columns.get_loc("payment_method")
        v = str(df.iloc[i, j])
        df.iloc[i, j] = v.lower().replace(" ", "-") if v == "Bank Transfer" else v.lower()
    manifest["payment_method_variants"] = int(len(pm_idx))
    ws_idx = _pick(rng, n, 0.02)
    for i in ws_idx:
        j = df.columns.get_loc("branch")
        df.iloc[i, j] = " " + str(df.iloc[i, j])
    manifest["branch_whitespace_rows"] = int(len(ws_idx))

    # ── age and income ────────────────────────────────────────────────────
    age = df["customer_age"].astype(object)
    miss_age = _pick(rng, n, 0.03)
    age.iloc[miss_age] = None
    unk_age = rng.choice(np.setdiff1d(np.arange(n), miss_age), int(n * 0.01), replace=False)
    age.iloc[unk_age] = "unknown"
    bad_age = rng.choice(np.setdiff1d(np.arange(n), np.concatenate([miss_age, unk_age])), 6, replace=False)
    age.iloc[bad_age] = rng.choice(["230", "-5", "999"], 6)
    df["customer_age"] = age
    manifest["missing_ages"] = int(len(miss_age))
    manifest["unknown_age_tokens"] = int(len(unk_age))
    manifest["invalid_ages"] = 6

    inc = df["monthly_income"].astype(object)
    miss_inc = _pick(rng, n, 0.08)
    inc.iloc[miss_inc] = None
    na_inc = rng.choice(np.setdiff1d(np.arange(n), miss_inc), int(n * 0.02), replace=False)
    inc.iloc[na_inc] = "N/A"
    fmt_inc = rng.choice(np.setdiff1d(np.arange(n), np.concatenate([miss_inc, na_inc])), int(n * 0.05), replace=False)
    for i in fmt_inc:
        inc.iloc[i] = f"£{float(inc.iloc[i]):,.0f}"
    df["monthly_income"] = inc
    manifest["missing_incomes"] = int(len(miss_inc))
    manifest["na_income_tokens"] = int(len(na_inc))
    manifest["formatted_incomes"] = int(len(fmt_inc))

    # ── unnecessary columns ───────────────────────────────────────────────
    df["internal_notes"] = None
    df["batch_source"] = "CORE-BANKING-EXPORT"

    # ── duplicates: exact copies and reused ids ───────────────────────────
    base_ids = df["transaction_id"].to_numpy(copy=True)
    touched: set[int] = set()
    reused: list[int] = []
    for i in rng.permutation(n):
        if len(reused) == 15:
            break
        src = i - 7 if i >= 7 else i + 7
        if i in touched or src in touched:
            continue  # independent pairs, so each reused id duplicates exactly one other row
        base_ids[i] = base_ids[src]
        touched.update((int(i), int(src)))
        reused.append(int(i))
    df["transaction_id"] = base_ids
    dup_src = rng.choice(len(df), int(len(df) * 0.015), replace=False)
    dups = df.iloc[dup_src]
    pos = np.sort(rng.choice(len(df), len(dups), replace=False))
    parts, last = [], 0
    for p, (_, row) in zip(pos, dups.iterrows()):
        parts.append(df.iloc[last : p + 1])
        parts.append(row.to_frame().T)
        last = p + 1
    parts.append(df.iloc[last:])
    out = pd.concat(parts, ignore_index=True)
    manifest["exact_duplicate_rows_injected"] = int(len(dups))
    manifest["reused_transaction_ids_injected"] = 15
    manifest["total_rows"] = int(len(out))
    manifest["columns"] = list(out.columns)
    manifest["clean_truth"] = clean_truth

    return SampleResult(csv_text=out.to_csv(index=False), manifest=manifest)
