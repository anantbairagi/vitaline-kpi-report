"""Clinical KPI Stakeholder Report — Streamlit App

Narrative walkthrough of Vitaline program clinical outcomes.
Run:  streamlit run scripts/kpi_stakeholder_app.py
"""

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "deid_clinical.db"
EXCEL_PATH = ROOT / "reports" / "clinical_kpi_report_2026_01.xlsx"

st.set_page_config(page_title="Clinical KPI Report - Jan 2026", page_icon=":hospital:",
                   layout="wide", initial_sidebar_state="collapsed")


@st.cache_data(ttl=300)
def load_excel():
    sheets = {}
    for name, key in [("Summary", "summary"), ("1_Eligible_Patients", "eligible"),
                      ("2_Long_Stay", "longstay"), ("3_KPI1_Falls_MajorInjury", "kpi1"),
                      ("4_KPI2_Prevalence_Falls", "kpi2"), ("5_KPI3_PrePost_Falls", "kpi3"),
                      ("6_KPI4_PrePost_Hosp", "kpi4")]:
        sheets[key] = pd.read_excel(EXCEL_PATH, sheet_name=name)
    return sheets


@st.cache_data(ttl=300)
def load_context():
    conn = sqlite3.connect(DB_PATH)
    activity = pd.read_sql(
        """SELECT participation, COUNT(*) as visits,
                  COUNT(DISTINCT surrogate_patient_id) as patients
           FROM vitaline WHERE clinic_date >= '2026-01-01' AND clinic_date <= '2026-01-31'
           GROUP BY participation ORDER BY visits DESC""", conn)
    n_fac = pd.read_sql(
        """SELECT COUNT(DISTINCT surrogate_facility_id) as n FROM vitaline
           WHERE clinic_date >= '2026-01-01' AND clinic_date <= '2026-01-31'
             AND participation = 'Received'""", conn).iloc[0]["n"]
    conn.close()
    return activity, int(n_fac)


if not EXCEL_PATH.exists():
    st.error(f"Report not found. Run `python scripts/generate_kpi_report.py` first.")
    st.stop()

data = load_excel()
activity, n_facilities = load_context()
overall = data["summary"][data["summary"]["Facility"] == "OVERALL"].iloc[0]
total_visits = int(activity["visits"].sum())
received = activity[activity["participation"] == "Received"]
received_visits = int(received["visits"].sum()) if len(received) else 0
n_eligible = int(overall["Eligible Patients"])
n_longstay = int(overall["Long-Stay Patients"])


def pct(n, d):
    return f"{n / d:.1%}" if d > 0 else "N/A"


def card(label, value, description):
    st.markdown(
f"""<div style="background:#f8f9fa;border-radius:10px;padding:18px 14px;text-align:center;border:1px solid #dee2e6;">
<p style="color:#6c757d;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px 0;">{label}</p>
<p style="font-size:2.1rem;font-weight:700;color:#212529;margin:0 0 8px 0;">{value}</p>
<p style="color:#555;font-size:0.82rem;margin:0;line-height:1.45;">{description}</p>
</div>""", unsafe_allow_html=True)


def change_card(label, value, description, is_good):
    color = "#198754" if is_good else "#dc3545"
    st.markdown(
f"""<div style="background:#f8f9fa;border-radius:10px;padding:18px 14px;text-align:center;border:1px solid #dee2e6;">
<p style="color:#6c757d;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px 0;">{label}</p>
<p style="font-size:2.1rem;font-weight:700;color:{color};margin:0 0 8px 0;">{value}</p>
<p style="color:#555;font-size:0.82rem;margin:0;line-height:1.45;">{description}</p>
</div>""", unsafe_allow_html=True)


def dist_chart(fac_df, col, title, color="#0d6efd"):
    plot = fac_df.dropna(subset=[col]).copy()
    if plot.empty:
        st.caption("No facility-level data for this metric.")
        return
    plot = plot.sort_values(col, ascending=True)
    labels = plot["Facility"] + " - " + plot["Company"].fillna("")
    fig = go.Figure(go.Bar(x=plot[col], y=labels, orientation="h", marker_color=color,
                           text=plot[col].apply(lambda v: f"{v:.1%}"), textposition="outside"))
    fig.update_layout(title=title, xaxis_tickformat=".0%",
                      height=max(300, len(plot) * 28 + 80),
                      margin=dict(l=10, r=30, t=40, b=30))
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    "<h1 style='text-align:center;margin-bottom:0;'>Clinical KPI Report</h1>"
    "<p style='text-align:center;color:#6c757d;font-size:1.2rem;margin-top:4px;'>"
    "Vitaline IV Therapy Program &mdash; January 2026</p>",
    unsafe_allow_html=True)
st.markdown("---")

# ── DEFINITIONS ──────────────────────────────────────────────────────────────

with st.expander("Key Definitions Used in This Report"):
    st.markdown(
        "- **Eligible Patient**: A Vitaline patient who received an infusion in the report "
        "month and has 3 or more contiguous months of treatment (1-month gap allowed).\n"
        "- **Long-Stay Resident**: A patient whose cumulative days in facility (CDIF) is "
        "101 days or more, per CMS definition.\n"
        "- **Episode**: A period of continuous care at a facility. Starts with an admission. "
        "If a patient is discharged and returns within 30 days, it's a reentry in the same "
        "episode. Otherwise, it's a new episode.\n"
        "- **Target Assessment**: The patient's most recent qualifying MDS assessment, "
        "no more than 120 days before the end of their current episode.\n"
        "- **Target Date**: For entry records = entry date. For discharges = discharge date. "
        "For all other assessments = Assessment Reference Date (ARD).\n"
        "- **Qualifying Assessment**: An MDS assessment with a Reason for Assessment (RFA) of: "
        "OBRA (A0310A = 01-06), PPS (A0310B = 01-06), or discharge (A0310F = 10, 11).\n"
        "- **Look-back Scan**: Starting from the target assessment, scan all qualifying "
        "assessments going back up to 275 days within the same episode. This covers "
        "approximately 1 year of clinical history.\n\n"
        "*Source: CMS MDS 3.0 Quality Measures User's Manual V17 (January 2025)*"
    )

# ── SECTION 1 ────────────────────────────────────────────────────────────────

st.header("1. Vitaline Activity in January 2026")
st.markdown(f"In **January 2026**, Vitaline conducted clinics across **{n_facilities} facilities**. "
            f"A total of **{total_visits} patient visits** were recorded, of which "
            f"**{received_visits}** were infusions actually received.")

c1, c2, c3 = st.columns(3)
with c1:
    card("Total Patient Visits", f"{total_visits:,}",
         "All visits in January 2026 including received infusions and did-not-participate records.")
with c2:
    card("Infusions Received", f"{received_visits:,}",
         "Patients who actually received a Vitaline infusion. This is the starting population.")
with c3:
    card("Facilities Served", str(n_facilities),
         "Skilled nursing facilities across Accolade, Empire, Caliber, and Paradigm.")

with st.expander("View breakdown by participation type"):
    st.dataframe(activity.rename(columns={"participation": "Participation",
                 "visits": "Visits", "patients": "Unique Patients"}),
                 use_container_width=True, hide_index=True)
st.markdown("---")

# ── SECTION 2 ────────────────────────────────────────────────────────────────

st.header("2. Identifying Eligible Patients")
st.markdown("Not every patient qualifies. We require a **meaningful treatment history**:")
st.info("**Eligibility Criteria**\n\n"
        "1. **Active in January 2026** — received at least one infusion.\n"
        "2. **3+ contiguous months** — counting backwards from January, the patient must have "
        "received infusions in at least 3 distinct months, with at most a 1-month gap between "
        "any two consecutive months.")

c1, c2, c3 = st.columns(3)
with c1:
    card("Active Patients", str(received_visits),
         "Patients who received a Vitaline infusion in January 2026.")
with c2:
    card("Eligible Patients", str(n_eligible),
         f"{pct(n_eligible, received_visits)} of active patients met the 3+ contiguous month "
         f"criteria — they have a sustained treatment history.")
with c3:
    card("Not Eligible", str(received_visits - n_eligible),
         "Had fewer than 3 contiguous months of treatment.")

with st.expander(f"View all {received_visits} patients with eligibility details"):
    st.dataframe(data["eligible"].rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "all_visit_months": "All Visit Months", "contiguous_chain": "Contiguous Chain",
        "chain_length": "Chain Length", "eligible": "Eligible", "company": "Company"}),
        use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 3 ────────────────────────────────────────────────────────────────

st.header("3. Long-Stay Residents")
st.markdown("CMS quality measures for falls apply only to **long-stay** residents:")
st.info("**Long-Stay Definition** (CMS V17)\n\n"
        "A resident is long-stay if their **Cumulative Days in Facility (CDIF) is 101+ days**.\n\n"
        "- Each patient's stay history is reconstructed from MDS entry/discharge records.\n"
        "- Admission vs reentry is determined by **A1700** on the entry record.\n"
        "- CDIF counts only in-facility days. Hospital days do not count.\n\n"
        "*Source: CMS QM User's Manual V17, Chapter 1 Section 1, Chapter 4*")

ls_df = data["longstay"]
median_cdif = int(ls_df[ls_df["is_long_stay"] == True]["cdif"].median()) if n_longstay else 0

c1, c2, c3 = st.columns(3)
with c1:
    card("Eligible Patients", str(n_eligible), "From Step 2 — patients with 3+ months of treatment.")
with c2:
    card("Long-Stay (101+ Days)", str(n_longstay),
         f"{pct(n_longstay, n_eligible)} of eligible patients have 101+ cumulative days "
         f"at their facility, qualifying as long-stay per CMS.")
with c3:
    card("Median CDIF", f"{median_cdif} days",
         "Half of long-stay patients have been at their facility longer than this.")

with st.expander(f"View long-stay classification for all {n_eligible} eligible patients"):
    st.dataframe(ls_df.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "episode_start": "Episode Start", "episode_end": "Episode End",
        "num_stays": "Stays", "stay_details": "Stay Details",
        "cdif": "CDIF (days)", "is_long_stay": "Long-Stay"}),
        use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 4: KPI 1 ────────────────────────────────────────────────────────

st.header("4. KPI 1 — Falls with Major Injury")
st.markdown("CMS measure **N013.02**: *Percent of Residents Experiencing One or More Falls "
            "with Major Injury (Long Stay)*. Among our long-stay Vitaline patients, **what "
            "percentage experienced a fall with major injury?**")
st.info("**How it's calculated** (CMS V17 exact methodology)\n\n"
        "1. **Find the target assessment**: the patient's most recent qualifying MDS assessment "
        "within their current episode, no more than 120 days before the episode end.\n"
        "2. **Look-back scan**: from the target assessment, scan all qualifying assessments "
        "going back up to 275 days within the same episode — covering roughly 1 year of "
        "clinical history.\n"
        "3. **Qualifying assessments**: OBRA (A0310A = 01-06), PPS (A0310B = 01-06), or "
        "discharge (A0310F = 10, 11).\n"
        "4. **Denominator**: long-stay patients with at least one scan assessment where "
        "falls with major injury (J1900C) was coded by the assessor.\n"
        "5. **Numerator**: patients where J1900C = 1 or 2 (one or more major-injury falls) "
        "on any assessment in the scan.\n\n"
        "*Source: CMS QM User's Manual V17, Table 2-12, Chapter 1 Section 4*")

k1 = data["kpi1"]
k1_ls = k1[k1["is_long_stay"] == True]
k1_denom = int(((k1_ls["has_assessment"] == True) & (k1_ls["excluded"] == False)).sum())
k1_num = int((k1_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"{n_longstay} eligible patients with 101+ cumulative days at their facility.")
with c2:
    card("In Denominator", str(k1_denom),
         f"Of {n_longstay} long-stay patients, {k1_denom} had qualifying assessments "
         f"where falls with major injury (J1900C) was coded during the ~1 year look-back scan.")
with c3:
    card("Had Major-Injury Fall", str(k1_num),
         f"Of those {k1_denom} patients, {k1_num} had at least one assessment reporting "
         f"a fall with major injury (J1900C = 1 or 2) during the scan period.")
with c4:
    card("Rate", pct(k1_num, k1_denom),
         f"{pct(k1_num, k1_denom)} of assessed long-stay Vitaline patients experienced "
         f"a major-injury fall in the past year." if k1_denom > 0 else "N/A")

with st.expander("View KPI 1 patient-level detail"):
    d1 = k1_ls[k1_ls["has_assessment"] == True].copy()
    st.dataframe(d1.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "n_assessments": "Assessments Scanned", "item_values": "J1900C Values",
        "excluded": "Excluded", "in_numerator": "Had Fall", "scan_detail": "Scan Window"
    })[["Patient ID", "Facility", "Assessments Scanned", "J1900C Values",
        "Excluded", "Had Fall", "Scan Window"]],
       use_container_width=True, hide_index=True)
st.markdown("---")

# ── SECTION 5: KPI 2 ────────────────────────────────────────────────────────

st.header("5. KPI 2 — Prevalence of Falls")
st.markdown("CMS measure **N032.02**: *Prevalence of Falls (Long Stay)*. "
            "**What percentage of long-stay Vitaline patients had any fall at all?**")
st.info("**How it's calculated** (CMS V17 exact methodology)\n\n"
        "1. **Find the target assessment**: same as KPI 1 — the patient's most recent "
        "qualifying assessment, no more than 120 days before episode end.\n"
        "2. **Look-back scan**: scan all qualifying assessments going back up to 275 days "
        "within the same episode.\n"
        "3. **Qualifying assessments**: OBRA (A0310A = 01-06), PPS (A0310B = 01-06), or "
        "discharge (A0310F = 10, 11).\n"
        "4. **Denominator**: long-stay patients with at least one scan assessment where "
        "any fall (J1800) was coded.\n"
        "5. **Numerator**: patients where J1800 = 1 (yes, had a fall since prior assessment) "
        "on any assessment in the scan.\n\n"
        "*Source: CMS QM User's Manual V17, Table 2-32*")

k2 = data["kpi2"]
k2_ls = k2[k2["is_long_stay"] == True]
k2_denom = int(((k2_ls["has_assessment"] == True) & (k2_ls["excluded"] == False)).sum())
k2_num = int((k2_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"{n_longstay} eligible patients with 101+ cumulative days at their facility.")
with c2:
    card("In Denominator", str(k2_denom),
         f"Of {n_longstay} long-stay patients, {k2_denom} had qualifying assessments "
         f"where any fall (J1800) was coded during the ~1 year look-back scan.")
with c3:
    card("Had a Fall", str(k2_num),
         f"Of those {k2_denom} patients, {k2_num} had at least one assessment reporting "
         f"a fall (J1800 = 1) during the scan period.")
with c4:
    card("Rate", pct(k2_num, k2_denom),
         f"{pct(k2_num, k2_denom)} of assessed long-stay Vitaline patients had a fall "
         f"reported in the past year." if k2_denom > 0 else "N/A")

with st.expander("View KPI 2 patient-level detail"):
    d2 = k2_ls[k2_ls["has_assessment"] == True].copy()
    st.dataframe(d2.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "n_assessments": "Assessments Scanned", "item_values": "J1800 Values",
        "excluded": "Excluded", "in_numerator": "Had Fall", "scan_detail": "Scan Window"
    })[["Patient ID", "Facility", "Assessments Scanned", "J1800 Values",
        "Excluded", "Had Fall", "Scan Window"]],
       use_container_width=True, hide_index=True)
st.markdown("---")

# ── SECTION 6: KPI 3 ────────────────────────────────────────────────────────

st.header("6. KPI 3 — Falls: Non-Vitaline Period vs Vitaline Treatment Period")
st.markdown(f"This compares major-injury falls **before** a patient started Vitaline versus "
            f"**during** treatment. It applies to all **{n_eligible} eligible patients** "
            f"(not just long-stay).")
st.info("**How the comparison works**\n\n"
        "- **Non-Vitaline Period**: The most recent period (90 or 120 days) when the patient "
        "was **not receiving** Vitaline infusions. We scan gaps between consecutive visits. "
        "If no gap exists, we use the period before their first visit.\n"
        "- **Vitaline Treatment Period**: The most recent 90 or 120 days ending January 31, 2026 "
        "— a period when the patient was actively receiving Vitaline.\n\n"
        "For each period, we check MDS assessments for falls with major injury (J1900C).\n\n"
        "- **Part A**: patients with at least 1 major-injury fall (J1900C = 1 or 2)\n"
        "- **Part B**: patients with 2+ major-injury falls across separate assessments\n"
        "- **Part C**: patients with 2+ major-injury falls on a single assessment (J1900C = 2)")

k3 = data["kpi3"]

for wd in (90, 120):
    s = f"_{wd}d"
    st.subheader(f"{wd}-Day Window")

    pre_a = int(k3[f"pre_any_fall{s}"].sum())
    post_a = int(k3[f"post_any_fall{s}"].sum())
    pre_b = int(k3[f"pre_2plus_falls{s}"].sum())
    post_b = int(k3[f"post_2plus_falls{s}"].sum())
    pre_c = int(k3[f"pre_j1900c2{s}"].sum())
    post_c = int(k3[f"post_j1900c2{s}"].sum())

    pa_pct = pre_a / n_eligible if n_eligible else 0
    oa_pct = post_a / n_eligible if n_eligible else 0
    da = oa_pct - pa_pct

    st.markdown(f"**Part A — At least 1 major-injury fall** "
                f"({pre_a} non-Vitaline vs {post_a} Vitaline)")
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pa_pct:.1%}",
             f"**{pre_a}** of {n_eligible} patients had a major-injury fall "
             f"during the {wd} days before Vitaline treatment.")
    with c2:
        card("Vitaline Treatment Period", f"{oa_pct:.1%}",
             f"**{post_a}** of {n_eligible} patients had a major-injury fall "
             f"during the most recent {wd} days of treatment.")
    with c3:
        change_card("Change", f"{da:+.1%}",
                    "Fewer patients experienced major-injury falls during Vitaline treatment."
                    if da <= 0 else "More patients had falls during treatment.", da <= 0)

    pb_pct = pre_b / n_eligible if n_eligible else 0
    ob_pct = post_b / n_eligible if n_eligible else 0

    st.markdown(f"**Part B — 2+ falls across separate assessments** "
                f"({pre_b} vs {post_b}) &nbsp; | &nbsp; "
                f"**Part C — J1900C=2 on single assessment** ({pre_c} vs {post_c})",
                unsafe_allow_html=True)

st.markdown("")
with st.expander("View KPI 3 patient-level detail"):
    st.dataframe(k3, use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 7: KPI 4 ────────────────────────────────────────────────────────

st.header("7. KPI 4 — Hospitalizations: Non-Vitaline vs Vitaline Period")
st.markdown("Same comparison as KPI 3 but for **acute care hospitalizations** — "
            "when a patient is discharged from the nursing facility to a hospital.")
st.info("**How hospitalizations are counted**\n\n"
        "A hospitalization = discharge record (A0310F = 10 or 11) where the patient went to "
        "an **acute care hospital** (discharge_status = '04').\n\n"
        "- **Part A**: patients with at least 1 hospitalization\n"
        "- **Part B**: patients with 2 or more hospitalizations")

k4 = data["kpi4"]

for wd in (90, 120):
    s = f"_{wd}d"
    st.subheader(f"{wd}-Day Window")

    pre_a = int(k4[f"pre_1plus{s}"].sum())
    post_a = int(k4[f"post_1plus{s}"].sum())
    pre_b = int(k4[f"pre_2plus{s}"].sum())
    post_b = int(k4[f"post_2plus{s}"].sum())

    pa_pct = pre_a / n_eligible if n_eligible else 0
    oa_pct = post_a / n_eligible if n_eligible else 0
    da = oa_pct - pa_pct

    st.markdown(f"**Part A — At least 1 hospitalization** "
                f"({pre_a} non-Vitaline vs {post_a} Vitaline)")
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pa_pct:.1%}",
             f"**{pre_a}** of {n_eligible} patients were hospitalized at least once "
             f"during the {wd} days before Vitaline treatment.")
    with c2:
        card("Vitaline Treatment Period", f"{oa_pct:.1%}",
             f"**{post_a}** of {n_eligible} patients were hospitalized at least once "
             f"during the most recent {wd} days of treatment.")
    with c3:
        change_card("Change", f"{da:+.1%}",
                    "Fewer patients required hospitalization during Vitaline treatment."
                    if da <= 0 else "More hospitalizations during treatment.", da <= 0)

    pb_pct = pre_b / n_eligible if n_eligible else 0
    ob_pct = post_b / n_eligible if n_eligible else 0
    st.markdown(f"**Part B — 2+ hospitalizations** ({pre_b} non-Vitaline vs {post_b} Vitaline)")

st.markdown("")
with st.expander("View KPI 4 patient-level detail"):
    st.dataframe(k4, use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 8: FACILITY TABLE ────────────────────────────────────────────────

st.header("8. Results by Facility")
fac = data["summary"][data["summary"]["Facility"] != "OVERALL"].copy()
fac = fac[fac["Eligible Patients"] > 0]

display_cols = {
    "Facility": "Facility", "Company": "Company",
    "Eligible Patients": "Eligible", "Long-Stay Patients": "Long-Stay",
    "KPI1 Denom": "Falls Major Injury Assessed", "KPI1 Num": "Had Major-Injury Fall",
    "KPI1 Rate": "Major Injury Rate",
    "KPI2 Denom": "Any Fall Assessed", "KPI2 Num": "Had Fall",
    "KPI2 Rate": "Fall Prevalence Rate",
}
st.dataframe(fac[list(display_cols.keys())].rename(columns=display_cols).style.format(
    {"Major Injury Rate": "{:.1%}", "Fall Prevalence Rate": "{:.1%}"}, na_rep="--"),
    use_container_width=True, hide_index=True, height=500)
st.markdown("---")

# ── SECTION 9: DISTRIBUTIONS ────────────────────────────────────────────────

st.header("9. KPI Distribution Across Facilities")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Falls Major Injury (KPI 1)", "Fall Prevalence (KPI 2)",
    "Falls Pre vs Post (KPI 3)", "Hosp Pre vs Post (KPI 4)", "Patient Counts"])

with tab1:
    dist_chart(fac, "KPI1 Rate", "Falls with Major Injury Rate by Facility", "#dc3545")
with tab2:
    dist_chart(fac, "KPI2 Rate", "Fall Prevalence Rate by Facility", "#fd7e14")
with tab3:
    st.caption("90-day window: % of eligible patients with at least 1 major-injury fall")
    plot = fac[["Facility", "Company"]].copy()
    plot["pre"] = fac.get("KPI3 Pre >=1 fall 90d %")
    plot["post"] = fac.get("KPI3 Post >=1 fall 90d %")
    plot = plot.dropna(subset=["pre", "post"]).sort_values("pre", ascending=True)
    if not plot.empty:
        labels = plot["Facility"] + " - " + plot["Company"].fillna("")
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Non-Vitaline", y=labels, x=plot["pre"],
                             orientation="h", marker_color="#6c757d"))
        fig.add_trace(go.Bar(name="Vitaline", y=labels, x=plot["post"],
                             orientation="h", marker_color="#0d6efd"))
        fig.update_layout(barmode="group", xaxis_tickformat=".0%",
                          height=max(400, len(plot) * 32 + 80),
                          margin=dict(l=10, r=30, t=30, b=30),
                          legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5))
        st.plotly_chart(fig, use_container_width=True)
with tab4:
    st.caption("90-day window: % of eligible patients with at least 1 hospitalization")
    plot = fac[["Facility", "Company"]].copy()
    plot["pre"] = fac.get("KPI4 Pre >=1 hosp 90d %")
    plot["post"] = fac.get("KPI4 Post >=1 hosp 90d %")
    plot = plot.dropna(subset=["pre", "post"]).sort_values("pre", ascending=True)
    if not plot.empty:
        labels = plot["Facility"] + " - " + plot["Company"].fillna("")
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Non-Vitaline", y=labels, x=plot["pre"],
                             orientation="h", marker_color="#6c757d"))
        fig.add_trace(go.Bar(name="Vitaline", y=labels, x=plot["post"],
                             orientation="h", marker_color="#198754"))
        fig.update_layout(barmode="group", xaxis_tickformat=".0%",
                          height=max(400, len(plot) * 32 + 80),
                          margin=dict(l=10, r=30, t=30, b=30),
                          legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5))
        st.plotly_chart(fig, use_container_width=True)
with tab5:
    plot = fac[["Facility", "Company", "Eligible Patients", "Long-Stay Patients"]].copy()
    plot = plot.sort_values("Eligible Patients", ascending=True)
    labels = plot["Facility"] + " - " + plot["Company"].fillna("")
    fig = go.Figure()
    fig.add_trace(go.Bar(name="Eligible", y=labels, x=plot["Eligible Patients"],
                         orientation="h", marker_color="#0d6efd"))
    fig.add_trace(go.Bar(name="Long-Stay", y=labels, x=plot["Long-Stay Patients"],
                         orientation="h", marker_color="#6610f2"))
    fig.update_layout(barmode="group", height=max(400, len(plot) * 32 + 80),
                      margin=dict(l=10, r=30, t=30, b=30),
                      legend=dict(orientation="h", y=1.02, xanchor="center", x=0.5))
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown(
    "<p style='text-align:center;color:#868e96;padding:20px;font-size:0.85rem;'>"
    "<strong>Data</strong>: MDS 3.0 assessments (188,250 records) &bull; "
    "Vitaline booking log (30,550 records) &bull; 41 facilities<br>"
    "<strong>Methodology</strong>: CMS MDS 3.0 Quality Measures User's Manual V17 "
    "(January 2025)<br>"
    "<strong>Privacy</strong>: All data is de-identified. No PHI.</p>",
    unsafe_allow_html=True)
