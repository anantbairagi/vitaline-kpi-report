"""Clinical KPI Monthly Report Generator

Generates an Excel report with 4 clinical KPIs for Vitaline patients,
with all intermediate columns visible for auditability.

KPI 1: Falls with Major Injury (LS) — mirrors CMS N013.01
KPI 2: Prevalence of Falls (LS) — mirrors CMS N032.01
KPI 3: Pre/Post 90-Day Falls Comparison
KPI 4: Pre/Post 90-Day Hospitalization Comparison

Source: CMS MDS 3.0 Quality Measures User's Manual (v12.1)
Usage:  python scripts/generate_kpi_report.py [--year 2026] [--month 1]
"""

import argparse
import calendar
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

# ── Configuration ────────────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "deid_clinical.db"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "reports"

OBRA_RFAS = ("01", "02", "03", "04", "05")
DISCHARGE_RFAS = ("10", "11")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _period_key(dt):
    """Convert a date/Timestamp to 'YYYY-MM' string."""
    return f"{dt.year}-{dt.month:02d}"


def _month_offset(ym_str, n):
    """Shift a 'YYYY-MM' string by n months."""
    y, m = int(ym_str[:4]), int(ym_str[5:])
    m += n
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return f"{y}-{m:02d}"


# ── Data Loading ─────────────────────────────────────────────────────────────

def load_data():
    conn = sqlite3.connect(DB_PATH)
    mds = pd.read_sql("SELECT * FROM mds_clinical", conn)
    vitaline = pd.read_sql("SELECT * FROM vitaline", conn)
    facilities = pd.read_sql("SELECT * FROM facility_lookup", conn)
    conn.close()

    for col in ("entry_date", "discharge_date", "admission_date", "assessment_reference_date"):
        mds[col] = pd.to_datetime(mds[col], errors="coerce")

    vitaline["clinic_date"] = pd.to_datetime(vitaline["clinic_date"], errors="coerce")
    return mds, vitaline, facilities


# ── Step 1: Eligible Patients ────────────────────────────────────────────────

def step1_eligible(vitaline, facilities, report_ym):
    """Identify Vitaline patients eligible for the report month.

    Criteria: participation='Received', visited in report month,
    3+ contiguous months of visits (1-month gap allowed).
    """
    v = vitaline[vitaline["participation"] == "Received"].copy()
    v["ym"] = v["clinic_date"].apply(_period_key)

    active = v[v["ym"] == report_ym]
    active_pids = active["surrogate_patient_id"].unique()

    pid_months = v.groupby("surrogate_patient_id")["ym"].apply(set).to_dict()
    pid_facility = (
        v.sort_values("clinic_date")
        .drop_duplicates("surrogate_patient_id", keep="last")[
            ["surrogate_patient_id", "surrogate_facility_id"]
        ]
        .set_index("surrogate_patient_id")["surrogate_facility_id"]
        .to_dict()
    )

    rows = []
    for pid in active_pids:
        months_set = pid_months.get(pid, set())
        chain = [report_ym]
        current = report_ym
        while True:
            m1 = _month_offset(current, -1)
            m2 = _month_offset(current, -2)
            if m1 in months_set:
                chain.append(m1)
                current = m1
            elif m2 in months_set:
                chain.append(m2)
                current = m2
            else:
                break

        chain_sorted = sorted(chain)
        rows.append({
            "surrogate_patient_id": pid,
            "surrogate_facility_id": pid_facility.get(pid, ""),
            "all_visit_months": ", ".join(sorted(months_set)),
            "contiguous_chain": ", ".join(chain_sorted),
            "chain_length": len(chain),
            "eligible": len(chain) >= 3,
        })

    df = pd.DataFrame(rows)
    df = df.merge(facilities, on="surrogate_facility_id", how="left")
    return df


# ── Step 2: Long-Stay (CDIF) ────────────────────────────────────────────────

def _build_stays_and_cdif(patient_mds, target_period_end):
    """Build stays/episodes and compute CDIF for one patient-facility pair.

    Implements CMS QM User's Manual v12.1, Chapter 1 Section 1 & Appendix C.
    Returns (episode_start, cdif, num_stays, detail_str).
    """
    events = []
    for _, row in patient_mds.iterrows():
        atype = row["entry_discharge_reporting"]
        if atype == "01" and pd.notna(row["entry_date"]):
            events.append(("E", row["entry_date"], atype))
        elif atype in ("10", "11", "12") and pd.notna(row["discharge_date"]):
            events.append(("D", row["discharge_date"], atype))

    if not events:
        adm = patient_mds["admission_date"].dropna().min()
        if pd.notna(adm):
            cdif = (target_period_end - adm).days + 1
            return adm, cdif, 1, f"Fallback: {adm.date()} → {target_period_end.date()} ({cdif}d)"
        return None, 0, 0, "No entry/admission records"

    events.sort(key=lambda e: (e[1], 0 if e[0] == "E" else 1))

    stays = []
    open_entry = None
    for ev in events:
        if ev[0] == "E":
            if open_entry is not None:
                imputed_end = ev[1] - timedelta(days=1)
                if imputed_end >= open_entry:
                    stays.append({"start": open_entry, "end": imputed_end, "dt": None})
            open_entry = ev[1]
        else:
            if open_entry is not None:
                stays.append({"start": open_entry, "end": ev[1], "dt": ev[2]})
                open_entry = None

    if open_entry is not None:
        stays.append({"start": open_entry, "end": target_period_end, "dt": None})

    if not stays:
        return None, 0, 0, "No valid stays"

    stays.sort(key=lambda s: s["start"])

    # Group into latest episode using 30-day reentry rule (CMS Appendix C §4.1)
    episode = [stays[-1]]
    for k in range(len(stays) - 2, -1, -1):
        prev = stays[k]
        first_in_ep = episode[0]
        if prev["dt"] == "11":
            gap = (first_in_ep["start"] - prev["end"]).days
            if gap <= 30:
                episode.insert(0, prev)
                continue
        break

    cdif = 0
    details = []
    for s in episode:
        ongoing = s["dt"] is None
        if ongoing:
            days = (s["end"] - s["start"]).days + 1
        else:
            days = max(1, (s["end"] - s["start"]).days)
        cdif += days
        tag = "→ongoing" if ongoing and s["end"] == target_period_end else ""
        details.append(f"{s['start'].date()}→{s['end'].date()} ({days}d{tag})")

    return episode[0]["start"], cdif, len(episode), "; ".join(details)


def step2_longstay(mds, eligible_df, target_period_end):
    """Compute CDIF and long-stay classification for eligible patients."""
    eligible = eligible_df[eligible_df["eligible"]]
    rows = []
    for _, pat in eligible.iterrows():
        pid = pat["surrogate_patient_id"]
        fid = pat["surrogate_facility_id"]
        pm = mds[(mds["surrogate_patient_id"] == pid) & (mds["surrogate_facility_id"] == fid)]

        ep_start, cdif, n_stays, detail = _build_stays_and_cdif(pm, target_period_end)
        rows.append({
            "surrogate_patient_id": pid,
            "surrogate_facility_id": fid,
            "episode_start": ep_start.date() if pd.notna(ep_start) else None,
            "num_stays": n_stays,
            "stay_details": detail,
            "cdif": cdif,
            "is_long_stay": cdif >= 101,
        })

    return pd.DataFrame(rows)


# ── Step 3–4: KPI 1 & KPI 2 ─────────────────────────────────────────────────

def _assess_quality_measure(patient_mds, window_start, window_end, item_col,
                            numerator_values, episode_start=None):
    """Evaluate a CMS-style quality measure for one patient in a window.

    Returns dict with assessment details and flags.
    """
    qualifying = patient_mds[
        (patient_mds["assessment_type_obra"].isin(OBRA_RFAS))
        | (patient_mds["entry_discharge_reporting"].isin(DISCHARGE_RFAS))
    ].copy()

    if episode_start is not None and pd.notna(episode_start):
        qualifying = qualifying[qualifying["assessment_reference_date"] >= episode_start]

    in_window = qualifying[
        (qualifying["assessment_reference_date"] >= window_start)
        & (qualifying["assessment_reference_date"] <= window_end)
    ]

    if in_window.empty:
        return {"has_assessment": False, "excluded": False, "in_numerator": False,
                "n_assessments": 0, "item_values": "", "reason": "No qualifying assessment"}

    values = in_window[item_col].tolist()
    coded = [v for v in values if pd.notna(v) and v not in ("-", "")]
    excluded = len(coded) == 0

    in_num = any(v in numerator_values for v in coded) if coded else False

    return {
        "has_assessment": True,
        "excluded": excluded,
        "in_numerator": in_num,
        "n_assessments": len(in_window),
        "item_values": ", ".join(str(v) for v in values),
        "reason": "",
    }


def step3_kpi1(mds, eligible_df, longstay_df, report_start, report_end, quarterly_start):
    """KPI 1: Falls with Major Injury — monthly and quarterly."""
    ls = longstay_df[longstay_df["is_long_stay"]]
    ls_pids = set(ls["surrogate_patient_id"])

    rows = []
    for _, pat in eligible_df[eligible_df["eligible"]].iterrows():
        pid = pat["surrogate_patient_id"]
        fid = pat["surrogate_facility_id"]
        is_ls = pid in ls_pids

        if not is_ls:
            rows.append({
                "surrogate_patient_id": pid, "surrogate_facility_id": fid,
                "is_long_stay": False,
                "monthly_has_assessment": None, "monthly_excluded": None,
                "monthly_in_numerator": None, "monthly_item_values": "",
                "quarterly_has_assessment": None, "quarterly_excluded": None,
                "quarterly_in_numerator": None, "quarterly_item_values": "",
            })
            continue

        ep_row = ls[ls["surrogate_patient_id"] == pid].iloc[0]
        ep_start = pd.Timestamp(ep_row["episode_start"]) if ep_row["episode_start"] else None
        pm = mds[(mds["surrogate_patient_id"] == pid) & (mds["surrogate_facility_id"] == fid)]

        m = _assess_quality_measure(pm, report_start, report_end,
                                    "j1900c_major_injury", ("1", "2"), ep_start)
        q = _assess_quality_measure(pm, quarterly_start, report_end,
                                    "j1900c_major_injury", ("1", "2"), ep_start)

        rows.append({
            "surrogate_patient_id": pid, "surrogate_facility_id": fid,
            "is_long_stay": True,
            "monthly_has_assessment": m["has_assessment"],
            "monthly_excluded": m["excluded"],
            "monthly_in_numerator": m["in_numerator"],
            "monthly_n_assessments": m["n_assessments"],
            "monthly_item_values": m["item_values"],
            "quarterly_has_assessment": q["has_assessment"],
            "quarterly_excluded": q["excluded"],
            "quarterly_in_numerator": q["in_numerator"],
            "quarterly_n_assessments": q["n_assessments"],
            "quarterly_item_values": q["item_values"],
        })

    return pd.DataFrame(rows)


def step4_kpi2(mds, eligible_df, longstay_df, report_start, report_end, quarterly_start):
    """KPI 2: Prevalence of Falls — monthly and quarterly."""
    ls = longstay_df[longstay_df["is_long_stay"]]
    ls_pids = set(ls["surrogate_patient_id"])

    rows = []
    for _, pat in eligible_df[eligible_df["eligible"]].iterrows():
        pid = pat["surrogate_patient_id"]
        fid = pat["surrogate_facility_id"]
        is_ls = pid in ls_pids

        if not is_ls:
            rows.append({
                "surrogate_patient_id": pid, "surrogate_facility_id": fid,
                "is_long_stay": False,
                "monthly_has_assessment": None, "monthly_excluded": None,
                "monthly_in_numerator": None, "monthly_item_values": "",
                "quarterly_has_assessment": None, "quarterly_excluded": None,
                "quarterly_in_numerator": None, "quarterly_item_values": "",
            })
            continue

        ep_row = ls[ls["surrogate_patient_id"] == pid].iloc[0]
        ep_start = pd.Timestamp(ep_row["episode_start"]) if ep_row["episode_start"] else None
        pm = mds[(mds["surrogate_patient_id"] == pid) & (mds["surrogate_facility_id"] == fid)]

        m = _assess_quality_measure(pm, report_start, report_end,
                                    "j1800_any_fall", ("1",), ep_start)
        q = _assess_quality_measure(pm, quarterly_start, report_end,
                                    "j1800_any_fall", ("1",), ep_start)

        rows.append({
            "surrogate_patient_id": pid, "surrogate_facility_id": fid,
            "is_long_stay": True,
            "monthly_has_assessment": m["has_assessment"],
            "monthly_excluded": m["excluded"],
            "monthly_in_numerator": m["in_numerator"],
            "monthly_n_assessments": m["n_assessments"],
            "monthly_item_values": m["item_values"],
            "quarterly_has_assessment": q["has_assessment"],
            "quarterly_excluded": q["excluded"],
            "quarterly_in_numerator": q["in_numerator"],
            "quarterly_n_assessments": q["n_assessments"],
            "quarterly_item_values": q["item_values"],
        })

    return pd.DataFrame(rows)


# ── Step 5: KPI 3 — Pre/Post Falls ──────────────────────────────────────────

def _find_pre_90_window(clinic_dates_sorted):
    """Find the most recent 90-day window without any Vitaline infusion.

    Scans gaps between consecutive visits (latest gap first).
    Falls back to 90 days before first visit if no inter-visit gap >= 90 days.
    """
    if not clinic_dates_sorted:
        return None, None

    for i in range(len(clinic_dates_sorted) - 1, 0, -1):
        gap = (clinic_dates_sorted[i] - clinic_dates_sorted[i - 1]).days
        if gap > 90:
            pre_end = clinic_dates_sorted[i] - timedelta(days=1)
            pre_start = clinic_dates_sorted[i] - timedelta(days=90)
            return pre_start, pre_end

    pre_end = clinic_dates_sorted[0] - timedelta(days=1)
    pre_start = clinic_dates_sorted[0] - timedelta(days=90)
    return pre_start, pre_end


def _count_falls_in_window(patient_mds, window_start, window_end):
    """Count J1900C values within an assessment window.

    Returns dict with counts and flags for KPI 3.
    """
    obra = patient_mds[
        patient_mds["assessment_type_obra"].isin(OBRA_RFAS)
        | patient_mds["entry_discharge_reporting"].isin(DISCHARGE_RFAS)
    ]
    in_window = obra[
        (obra["assessment_reference_date"] >= window_start)
        & (obra["assessment_reference_date"] <= window_end)
    ]

    n_assess = len(in_window)
    j1900c_vals = in_window["j1900c_major_injury"].dropna().tolist()
    coded = [v for v in j1900c_vals if v not in ("-", "")]

    count_1 = sum(1 for v in coded if v == "1")
    count_2 = sum(1 for v in coded if v == "2")
    has_any_fall = (count_1 + count_2) > 0
    has_j1900c_2 = count_2 > 0

    return {
        "n_assessments": n_assess,
        "j1900c_values": ", ".join(str(v) for v in j1900c_vals) if j1900c_vals else "",
        "j1900c_eq1_count": count_1,
        "j1900c_eq2_count": count_2,
        "has_any_fall": has_any_fall,
        "has_j1900c_2": has_j1900c_2,
    }


def step5_kpi3(mds, vitaline, eligible_df, post_start, post_end):
    """KPI 3: Pre/Post 90-day falls comparison for all eligible patients."""
    v_received = vitaline[vitaline["participation"] == "Received"]

    rows = []
    for _, pat in eligible_df[eligible_df["eligible"]].iterrows():
        pid = pat["surrogate_patient_id"]
        fid = pat["surrogate_facility_id"]

        clinic_dates = sorted(
            v_received[v_received["surrogate_patient_id"] == pid]["clinic_date"]
            .dropna().dt.date.tolist()
        )
        pre_start, pre_end = _find_pre_90_window(clinic_dates)

        pm = mds[(mds["surrogate_patient_id"] == pid) & (mds["surrogate_facility_id"] == fid)]

        pre = _count_falls_in_window(pm, pd.Timestamp(pre_start), pd.Timestamp(pre_end)) if pre_start else {
            "n_assessments": 0, "j1900c_values": "", "j1900c_eq1_count": 0,
            "j1900c_eq2_count": 0, "has_any_fall": False, "has_j1900c_2": False,
        }
        post = _count_falls_in_window(pm, post_start, post_end)

        gap_source = "pre-first-visit"
        if clinic_dates and len(clinic_dates) > 1:
            for i in range(len(clinic_dates) - 1, 0, -1):
                if (clinic_dates[i] - clinic_dates[i - 1]).days > 90:
                    gap_source = f"gap between {clinic_dates[i-1]} and {clinic_dates[i]}"
                    break

        rows.append({
            "surrogate_patient_id": pid,
            "surrogate_facility_id": fid,
            "first_vitaline_date": str(clinic_dates[0]) if clinic_dates else "",
            "pre_window_source": gap_source,
            "pre_window_start": str(pre_start) if pre_start else "",
            "pre_window_end": str(pre_end) if pre_end else "",
            "post_window_start": str(post_start.date()),
            "post_window_end": str(post_end.date()),
            "pre_n_assessments": pre["n_assessments"],
            "pre_j1900c_values": pre["j1900c_values"],
            "pre_j1900c_eq1": pre["j1900c_eq1_count"],
            "pre_j1900c_eq2": pre["j1900c_eq2_count"],
            "pre_any_fall": pre["has_any_fall"],
            "pre_has_j1900c_2": pre["has_j1900c_2"],
            "post_n_assessments": post["n_assessments"],
            "post_j1900c_values": post["j1900c_values"],
            "post_j1900c_eq1": post["j1900c_eq1_count"],
            "post_j1900c_eq2": post["j1900c_eq2_count"],
            "post_any_fall": post["has_any_fall"],
            "post_has_j1900c_2": post["has_j1900c_2"],
        })

    return pd.DataFrame(rows)


# ── Step 6: KPI 4 — Pre/Post Hospitalizations ───────────────────────────────

def _count_hosp_in_window(patient_mds, window_start, window_end):
    """Count hospitalization events (A0310F in 10,11 + discharge_status=04)."""
    discharges = patient_mds[
        patient_mds["entry_discharge_reporting"].isin(("10", "11"))
    ]
    in_window = discharges[
        (discharges["discharge_date"] >= window_start)
        & (discharges["discharge_date"] <= window_end)
    ]

    to_hospital = in_window[in_window["discharge_status"] == "04"]
    n_hosp = len(to_hospital)

    return {
        "n_discharges": len(in_window),
        "n_hospitalizations": n_hosp,
        "discharge_statuses": ", ".join(in_window["discharge_status"].dropna().tolist()),
        "has_1plus": n_hosp >= 1,
        "has_2plus": n_hosp >= 2,
    }


def step6_kpi4(mds, vitaline, eligible_df, post_start, post_end):
    """KPI 4: Pre/Post 90-day hospitalization comparison."""
    v_received = vitaline[vitaline["participation"] == "Received"]

    rows = []
    for _, pat in eligible_df[eligible_df["eligible"]].iterrows():
        pid = pat["surrogate_patient_id"]
        fid = pat["surrogate_facility_id"]

        clinic_dates = sorted(
            v_received[v_received["surrogate_patient_id"] == pid]["clinic_date"]
            .dropna().dt.date.tolist()
        )
        pre_start, pre_end = _find_pre_90_window(clinic_dates)

        pm = mds[(mds["surrogate_patient_id"] == pid) & (mds["surrogate_facility_id"] == fid)]

        pre = _count_hosp_in_window(pm, pd.Timestamp(pre_start), pd.Timestamp(pre_end)) if pre_start else {
            "n_discharges": 0, "n_hospitalizations": 0, "discharge_statuses": "",
            "has_1plus": False, "has_2plus": False,
        }
        post = _count_hosp_in_window(pm, post_start, post_end)

        gap_source = "pre-first-visit"
        if clinic_dates and len(clinic_dates) > 1:
            for i in range(len(clinic_dates) - 1, 0, -1):
                if (clinic_dates[i] - clinic_dates[i - 1]).days > 90:
                    gap_source = f"gap between {clinic_dates[i-1]} and {clinic_dates[i]}"
                    break

        rows.append({
            "surrogate_patient_id": pid,
            "surrogate_facility_id": fid,
            "pre_window_start": str(pre_start) if pre_start else "",
            "pre_window_end": str(pre_end) if pre_end else "",
            "post_window_start": str(post_start.date()),
            "post_window_end": str(post_end.date()),
            "pre_window_source": gap_source,
            "pre_n_discharges": pre["n_discharges"],
            "pre_n_hospitalizations": pre["n_hospitalizations"],
            "pre_discharge_statuses": pre["discharge_statuses"],
            "pre_has_1plus_hosp": pre["has_1plus"],
            "pre_has_2plus_hosp": pre["has_2plus"],
            "post_n_discharges": post["n_discharges"],
            "post_n_hospitalizations": post["n_hospitalizations"],
            "post_discharge_statuses": post["discharge_statuses"],
            "post_has_1plus_hosp": post["has_1plus"],
            "post_has_2plus_hosp": post["has_2plus"],
        })

    return pd.DataFrame(rows)


# ── Summary ──────────────────────────────────────────────────────────────────

def _rate(num, denom):
    return num / denom if denom > 0 else None


def compute_summary(eligible_df, longstay_df, kpi1_df, kpi2_df, kpi3_df, kpi4_df,
                    facilities, report_ym):
    """Build per-facility summary of all KPIs."""
    elig = eligible_df[eligible_df["eligible"]]
    facility_ids = sorted(elig["surrogate_facility_id"].unique())

    summary_rows = []
    for fid in [None] + list(facility_ids):
        if fid is None:
            label = "OVERALL"
            company = ""
            mask_e = elig.index
            mask_ls = longstay_df.index
            mask_k1 = kpi1_df.index
            mask_k2 = kpi2_df.index
            mask_k3 = kpi3_df.index
            mask_k4 = kpi4_df.index
        else:
            label = fid
            company = facilities.loc[
                facilities["surrogate_facility_id"] == fid, "company"
            ].values
            company = company[0] if len(company) else ""
            mask_e = elig["surrogate_facility_id"] == fid
            mask_ls = longstay_df["surrogate_facility_id"] == fid
            mask_k1 = kpi1_df["surrogate_facility_id"] == fid
            mask_k2 = kpi2_df["surrogate_facility_id"] == fid
            mask_k3 = kpi3_df["surrogate_facility_id"] == fid
            mask_k4 = kpi4_df["surrogate_facility_id"] == fid

        n_eligible = int(mask_e.sum()) if isinstance(mask_e, pd.Series) else len(elig)
        ls_sub = longstay_df[mask_ls] if isinstance(mask_ls, pd.Series) else longstay_df
        n_longstay = int(ls_sub["is_long_stay"].sum())

        # KPI 1
        k1 = kpi1_df[mask_k1] if isinstance(mask_k1, pd.Series) else kpi1_df
        k1_ls = k1[k1["is_long_stay"] == True]
        for prefix, label_p in [("monthly", "Monthly"), ("quarterly", "Quarterly")]:
            ha = k1_ls[f"{prefix}_has_assessment"]
            ex = k1_ls[f"{prefix}_excluded"]
            innum = k1_ls[f"{prefix}_in_numerator"]
            denom = int(((ha == True) & (ex == False)).sum())
            numer = int((innum == True).sum())
            summary_key = f"kpi1_{prefix}"
            # store for later

        # KPI 2
        k2 = kpi2_df[mask_k2] if isinstance(mask_k2, pd.Series) else kpi2_df
        k2_ls = k2[k2["is_long_stay"] == True]

        # KPI 3
        k3 = kpi3_df[mask_k3] if isinstance(mask_k3, pd.Series) else kpi3_df

        # KPI 4
        k4 = kpi4_df[mask_k4] if isinstance(mask_k4, pd.Series) else kpi4_df

        def _kpi12_stats(kdf, prefix):
            ha = kdf[f"{prefix}_has_assessment"]
            ex = kdf[f"{prefix}_excluded"]
            inn = kdf[f"{prefix}_in_numerator"]
            d = int(((ha == True) & (ex == False)).sum())
            n = int((inn == True).sum())
            return d, n, _rate(n, d)

        k1m_d, k1m_n, k1m_r = _kpi12_stats(k1_ls, "monthly")
        k1q_d, k1q_n, k1q_r = _kpi12_stats(k1_ls, "quarterly")
        k2m_d, k2m_n, k2m_r = _kpi12_stats(k2_ls, "monthly")
        k2q_d, k2q_n, k2q_r = _kpi12_stats(k2_ls, "quarterly")

        k3_total = len(k3)
        k3_pre_a = int(k3["pre_any_fall"].sum()) if len(k3) else 0
        k3_post_a = int(k3["post_any_fall"].sum()) if len(k3) else 0
        k3_pre_b = int(k3["pre_has_j1900c_2"].sum()) if len(k3) else 0
        k3_post_b = int(k3["post_has_j1900c_2"].sum()) if len(k3) else 0

        k4_total = len(k4)
        k4_pre_a = int(k4["pre_has_1plus_hosp"].sum()) if len(k4) else 0
        k4_post_a = int(k4["post_has_1plus_hosp"].sum()) if len(k4) else 0
        k4_pre_b = int(k4["pre_has_2plus_hosp"].sum()) if len(k4) else 0
        k4_post_b = int(k4["post_has_2plus_hosp"].sum()) if len(k4) else 0

        summary_rows.append({
            "Facility": label,
            "Company": company,
            "Eligible Patients": n_eligible,
            "Long-Stay Patients": n_longstay,
            # KPI 1
            "KPI1 Monthly Denom": k1m_d, "KPI1 Monthly Num": k1m_n,
            "KPI1 Monthly Rate": k1m_r,
            "KPI1 Quarterly Denom": k1q_d, "KPI1 Quarterly Num": k1q_n,
            "KPI1 Quarterly Rate": k1q_r,
            # KPI 2
            "KPI2 Monthly Denom": k2m_d, "KPI2 Monthly Num": k2m_n,
            "KPI2 Monthly Rate": k2m_r,
            "KPI2 Quarterly Denom": k2q_d, "KPI2 Quarterly Num": k2q_n,
            "KPI2 Quarterly Rate": k2q_r,
            # KPI 3
            "KPI3 Eligible": k3_total,
            "KPI3-A Pre (>=1 fall)": k3_pre_a,
            "KPI3-A Post (>=1 fall)": k3_post_a,
            "KPI3-A Pre %": _rate(k3_pre_a, k3_total),
            "KPI3-A Post %": _rate(k3_post_a, k3_total),
            "KPI3-B Pre (J1900C=2)": k3_pre_b,
            "KPI3-B Post (J1900C=2)": k3_post_b,
            "KPI3-B Pre %": _rate(k3_pre_b, k3_total),
            "KPI3-B Post %": _rate(k3_post_b, k3_total),
            # KPI 4
            "KPI4 Eligible": k4_total,
            "KPI4-A Pre (>=1 hosp)": k4_pre_a,
            "KPI4-A Post (>=1 hosp)": k4_post_a,
            "KPI4-A Pre %": _rate(k4_pre_a, k4_total),
            "KPI4-A Post %": _rate(k4_post_a, k4_total),
            "KPI4-B Pre (>=2 hosp)": k4_pre_b,
            "KPI4-B Post (>=2 hosp)": k4_post_b,
            "KPI4-B Pre %": _rate(k4_pre_b, k4_total),
            "KPI4-B Post %": _rate(k4_post_b, k4_total),
        })

    return pd.DataFrame(summary_rows)


# ── Excel Generation ─────────────────────────────────────────────────────────

def _definitions_rows():
    """Return rows for the Definitions sheet."""
    return [
        ("Sheet", "Column / Metric", "Definition"),
        ("", "", ""),
        ("General", "Report Month", "The calendar month for which KPIs are computed"),
        ("General", "Eligible Patient", "Vitaline patient with participation='Received', "
         "visited in the report month, with 3+ contiguous months of visits (1-month gap allowed)"),
        ("General", "Contiguous Chain", "Backward chain from report month; consecutive months "
         "with visits, allowing a single month gap between any two"),
        ("General", "Long-Stay (CMS)", "CDIF >= 101 days per CMS QM User's Manual v12.1. "
         "CDIF = cumulative days in facility within the latest episode, "
         "excluding days outside facility (hospitalizations). "
         "Include entry day, exclude discharge day."),
        ("General", "Episode", "One or more stays starting with an admission. "
         "Stays within 30 days of a return-anticipated discharge are reentries in the same episode."),
        ("", "", ""),
        ("KPI 1", "Falls with Major Injury (LS)", "CMS N013.01 — % of long-stay residents "
         "with J1900C = 1 or 2 on any qualifying OBRA assessment"),
        ("KPI 1", "Denominator", "Long-stay eligible patients with 1+ qualifying assessments "
         "where J1900C is coded (not NULL or dash)"),
        ("KPI 1", "Numerator", "Patients in denominator with J1900C in (1, 2) on any assessment"),
        ("KPI 1", "Monthly", "Assessments with ARD in report month only"),
        ("KPI 1", "Quarterly", "Assessments with ARD in report month + 2 prior months"),
        ("", "", ""),
        ("KPI 2", "Prevalence of Falls (LS)", "CMS N032.01 — % of long-stay residents "
         "with J1800 = 1 on any qualifying OBRA assessment"),
        ("KPI 2", "Denominator", "Long-stay eligible patients with 1+ qualifying assessments "
         "where J1800 is coded (not NULL or dash)"),
        ("KPI 2", "Numerator", "Patients in denominator with J1800 = 1 on any assessment"),
        ("", "", ""),
        ("KPI 3", "Pre/Post 90-Day Falls", "Compare major-injury falls before and after Vitaline"),
        ("KPI 3", "PRE Window", "Most recent 90-day period without Vitaline infusions. "
         "Found by scanning gaps between consecutive visits (latest gap first). "
         "Falls back to 90 days before first visit if no gap >= 90 days exists."),
        ("KPI 3", "POST Window", "90 days ending on last day of report month"),
        ("KPI 3", "Part A", "% of eligible patients with at least 1 assessment where "
         "J1900C in (1, 2) during each window"),
        ("KPI 3", "Part B", "% of eligible patients with at least 1 assessment where "
         "J1900C = 2 (two or more major-injury falls) during each window"),
        ("", "", ""),
        ("KPI 4", "Pre/Post 90-Day Hospitalizations", "Compare hospitalizations before and after Vitaline"),
        ("KPI 4", "Hospitalization", "Discharge record (A0310F in 10, 11) with "
         "discharge_status = 04 (acute care hospital)"),
        ("KPI 4", "Part A", "% of eligible patients with >= 1 hospitalization in each window"),
        ("KPI 4", "Part B", "% of eligible patients with >= 2 hospitalizations in each window"),
        ("", "", ""),
        ("Sources", "CMS QM Manual", "MDS 3.0 Quality Measures User's Manual v12.1 "
         "(RTI International, October 2019)"),
        ("Sources", "CDIF / Episode Logic", "CMS QM Manual Chapter 1, Sections 1-4; Appendix C"),
        ("Sources", "Falls Measures", "CMS QM Manual Table 2-9 (N013.01), Appendix E (N032.01)"),
    ]


def write_excel(summary_df, eligible_df, longstay_df, kpi1_df, kpi2_df,
                kpi3_df, kpi4_df, report_year, report_month):
    """Write all sheets to an Excel workbook with formatting."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    OUTPUT_DIR.mkdir(exist_ok=True)
    fname = OUTPUT_DIR / f"clinical_kpi_report_{report_year}_{report_month:02d}.xlsx"

    month_name = calendar.month_name[report_month]
    title = f"Clinical KPI Report — {month_name} {report_year}"

    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    def _write_sheet(writer, df, sheet_name):
        df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
        ws = writer.sheets[sheet_name]
        for col_idx in range(1, len(df.columns) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

        for col_idx in range(1, len(df.columns) + 1):
            max_len = max(
                len(str(df.columns[col_idx - 1])),
                df.iloc[:, col_idx - 1].astype(str).str.len().max() if len(df) else 0,
            )
            ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 3, 50)

        for row_idx in range(2, len(df) + 2):
            for col_idx in range(1, len(df.columns) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.border = thin_border
                val = cell.value
                if isinstance(val, float) and 0 <= val <= 1:
                    cell.number_format = "0.00%"

    with pd.ExcelWriter(fname, engine="openpyxl") as writer:
        _write_sheet(writer, summary_df, "Summary")
        _write_sheet(writer, eligible_df, "1_Eligible_Patients")
        _write_sheet(writer, longstay_df, "2_Long_Stay")
        _write_sheet(writer, kpi1_df, "3_KPI1_Falls_MajorInjury")
        _write_sheet(writer, kpi2_df, "4_KPI2_Prevalence_Falls")
        _write_sheet(writer, kpi3_df, "5_KPI3_PrePost_Falls")
        _write_sheet(writer, kpi4_df, "6_KPI4_PrePost_Hosp")

        defs = pd.DataFrame(_definitions_rows()[1:], columns=_definitions_rows()[0])
        _write_sheet(writer, defs, "7_Definitions")

    print(f"Report written to {fname}")
    return fname


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Clinical KPI Monthly Report")
    parser.add_argument("--year", type=int, default=2026, help="Report year")
    parser.add_argument("--month", type=int, default=1, help="Report month (1-12)")
    args = parser.parse_args()

    report_year = args.year
    report_month = args.month
    report_ym = f"{report_year}-{report_month:02d}"
    report_start = pd.Timestamp(date(report_year, report_month, 1))
    report_end = pd.Timestamp(date(
        report_year, report_month,
        calendar.monthrange(report_year, report_month)[1],
    ))

    quarterly_start = report_start - pd.DateOffset(months=2)
    quarterly_start = pd.Timestamp(date(quarterly_start.year, quarterly_start.month, 1))

    post_90_end = report_end
    post_90_start = post_90_end - timedelta(days=89)

    print(f"Generating Clinical KPI Report for {calendar.month_name[report_month]} {report_year}")
    print(f"  Report month:    {report_start.date()} to {report_end.date()}")
    print(f"  Quarterly window: {quarterly_start.date()} to {report_end.date()}")
    print(f"  POST 90-day:     {post_90_start.date()} to {post_90_end.date()}")
    print()

    print("Loading data...")
    mds, vitaline, facilities = load_data()
    print(f"  MDS records:     {len(mds):,}")
    print(f"  Vitaline records: {len(vitaline):,}")
    print(f"  Facilities:      {len(facilities)}")
    print()

    print("Step 1: Identifying eligible patients...")
    eligible_df = step1_eligible(vitaline, facilities, report_ym)
    n_active = len(eligible_df)
    n_eligible = int(eligible_df["eligible"].sum())
    print(f"  Active in {report_ym}: {n_active}")
    print(f"  Eligible (3+ months): {n_eligible}")
    print()

    target_period_end = report_end

    print("Step 2: Computing long-stay (CDIF)...")
    longstay_df = step2_longstay(mds, eligible_df, target_period_end)
    n_ls = int(longstay_df["is_long_stay"].sum())
    print(f"  Long-stay (CDIF >= 101): {n_ls} / {n_eligible}")
    print()

    print("Step 3: KPI 1 — Falls with Major Injury...")
    kpi1_df = step3_kpi1(mds, eligible_df, longstay_df,
                         report_start, report_end, quarterly_start)
    print("  Done.")

    print("Step 4: KPI 2 — Prevalence of Falls...")
    kpi2_df = step4_kpi2(mds, eligible_df, longstay_df,
                         report_start, report_end, quarterly_start)
    print("  Done.")

    print("Step 5: KPI 3 — Pre/Post 90-day Falls...")
    kpi3_df = step5_kpi3(mds, vitaline, eligible_df, post_90_start, post_90_end)
    print("  Done.")

    print("Step 6: KPI 4 — Pre/Post 90-day Hospitalizations...")
    kpi4_df = step6_kpi4(mds, vitaline, eligible_df, post_90_start, post_90_end)
    print("  Done.")
    print()

    print("Computing summary...")
    summary_df = compute_summary(eligible_df, longstay_df, kpi1_df, kpi2_df,
                                 kpi3_df, kpi4_df, facilities, report_ym)

    # Print headline numbers
    overall = summary_df[summary_df["Facility"] == "OVERALL"].iloc[0]
    print()
    print("=" * 60)
    print(f"  HEADLINE RESULTS — {calendar.month_name[report_month]} {report_year}")
    print("=" * 60)
    print(f"  Eligible Patients:  {int(overall['Eligible Patients'])}")
    print(f"  Long-Stay:          {int(overall['Long-Stay Patients'])}")
    print()
    for label, prefix in [("KPI 1 (Falls Major Injury)", "KPI1"),
                          ("KPI 2 (Prevalence of Falls)", "KPI2")]:
        mrate = overall[f"{prefix} Monthly Rate"]
        qrate = overall[f"{prefix} Quarterly Rate"]
        print(f"  {label}:")
        print(f"    Monthly:   {overall[f'{prefix} Monthly Num']}/{overall[f'{prefix} Monthly Denom']}"
              f" = {mrate:.1%}" if mrate is not None else f"    Monthly:   N/A")
        print(f"    Quarterly: {overall[f'{prefix} Quarterly Num']}/{overall[f'{prefix} Quarterly Denom']}"
              f" = {qrate:.1%}" if qrate is not None else f"    Quarterly: N/A")
    print()
    for label, prefix in [("KPI 3 (Pre/Post Falls)", "KPI3"), ("KPI 4 (Pre/Post Hosp)", "KPI4")]:
        suf_a = "A" if prefix == "KPI3" else "A"
        suf_b = "B" if prefix == "KPI3" else "B"
        pre_a = overall[f"{prefix}-A Pre %"]
        post_a = overall[f"{prefix}-A Post %"]
        pre_b = overall[f"{prefix}-B Pre %"]
        post_b = overall[f"{prefix}-B Post %"]
        desc_a = ">=1 fall" if prefix == "KPI3" else ">=1 hosp"
        desc_b = "J1900C=2" if prefix == "KPI3" else ">=2 hosp"
        print(f"  {label}:")
        if pre_a is not None and post_a is not None:
            print(f"    Part A ({desc_a}): Pre {pre_a:.1%} -> Post {post_a:.1%}")
        if pre_b is not None and post_b is not None:
            print(f"    Part B ({desc_b}): Pre {pre_b:.1%} -> Post {post_b:.1%}")
    print("=" * 60)
    print()

    print("Writing Excel...")
    outpath = write_excel(summary_df, eligible_df, longstay_df,
                          kpi1_df, kpi2_df, kpi3_df, kpi4_df,
                          report_year, report_month)
    print(f"\nDone! Report saved to: {outpath}")


if __name__ == "__main__":
    main()
