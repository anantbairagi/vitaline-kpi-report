"""Clinical KPI Stakeholder Report — Streamlit App

A narrative walkthrough of Vitaline program clinical outcomes.
Reads from the pre-generated Excel report and SQLite database.

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

st.set_page_config(
    page_title="Clinical KPI Report - Jan 2026",
    page_icon=":hospital:",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Data Loading ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_excel():
    sheets = {}
    for name, key in [
        ("Summary", "summary"), ("1_Eligible_Patients", "eligible"),
        ("2_Long_Stay", "longstay"), ("3_KPI1_Falls_MajorInjury", "kpi1"),
        ("4_KPI2_Prevalence_Falls", "kpi2"), ("5_KPI3_PrePost_Falls", "kpi3"),
        ("6_KPI4_PrePost_Hosp", "kpi4"),
    ]:
        sheets[key] = pd.read_excel(EXCEL_PATH, sheet_name=name)
    return sheets


@st.cache_data
def load_context():
    conn = sqlite3.connect(DB_PATH)
    activity = pd.read_sql(
        """SELECT participation, COUNT(*) as visits,
                  COUNT(DISTINCT surrogate_patient_id) as patients
           FROM vitaline
           WHERE clinic_date >= '2026-01-01' AND clinic_date <= '2026-01-31'
           GROUP BY participation ORDER BY visits DESC""", conn)
    n_fac = pd.read_sql(
        """SELECT COUNT(DISTINCT surrogate_facility_id) as n FROM vitaline
           WHERE clinic_date >= '2026-01-01' AND clinic_date <= '2026-01-31'
             AND participation = 'Received'""", conn).iloc[0]["n"]
    conn.close()
    return activity, int(n_fac)


if not EXCEL_PATH.exists():
    st.error(f"Report not found at `{EXCEL_PATH}`. "
             "Run `python scripts/generate_kpi_report.py` first.")
    st.stop()

data = load_excel()
activity, n_facilities = load_context()
overall = data["summary"][data["summary"]["Facility"] == "OVERALL"].iloc[0]

total_visits = int(activity["visits"].sum())
received = activity[activity["participation"] == "Received"]
received_visits = int(received["visits"].sum()) if len(received) else 0
n_eligible = int(overall["Eligible Patients"])
n_longstay = int(overall["Long-Stay Patients"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def pct(n, d):
    return f"{n / d:.1%}" if d > 0 else "N/A"


def card(label, value, description):
    """Render a metric card with label, big number, and descriptive context."""
    st.markdown(
f"""<div style="background:#f8f9fa;border-radius:10px;padding:18px 14px;text-align:center;border:1px solid #dee2e6;">
<p style="color:#6c757d;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px 0;">{label}</p>
<p style="font-size:2.1rem;font-weight:700;color:#212529;margin:0 0 8px 0;">{value}</p>
<p style="color:#555;font-size:0.82rem;margin:0;line-height:1.45;text-align:center;">{description}</p>
</div>""", unsafe_allow_html=True)


def change_card(label, value, description, is_good):
    """Metric card with colored value for improvement/worsening."""
    color = "#198754" if is_good else "#dc3545"
    st.markdown(
f"""<div style="background:#f8f9fa;border-radius:10px;padding:18px 14px;text-align:center;border:1px solid #dee2e6;">
<p style="color:#6c757d;font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px;margin:0 0 4px 0;">{label}</p>
<p style="font-size:2.1rem;font-weight:700;color:{color};margin:0 0 8px 0;">{value}</p>
<p style="color:#555;font-size:0.82rem;margin:0;line-height:1.45;text-align:center;">{description}</p>
</div>""", unsafe_allow_html=True)


def facility_distribution_chart(fac_df, value_col, title, color="#0d6efd",
                                fmt=".1%", suffix="%"):
    """Horizontal bar chart of a metric across facilities."""
    plot_df = fac_df.dropna(subset=[value_col]).copy()
    if plot_df.empty:
        st.caption("No facility-level data available for this metric.")
        return
    plot_df = plot_df.sort_values(value_col, ascending=True)
    labels = plot_df["Facility"] + " — " + plot_df["Company"].fillna("")

    fig = go.Figure(go.Bar(
        x=plot_df[value_col],
        y=labels,
        orientation="h",
        marker_color=color,
        text=plot_df[value_col].apply(lambda v: f"{v:{fmt}}" if pd.notna(v) else ""),
        textposition="outside",
    ))
    fig.update_layout(
        title=title, xaxis_tickformat=fmt, height=max(300, len(plot_df) * 28 + 80),
        margin=dict(l=10, r=30, t=40, b=30), xaxis_title="",
        yaxis=dict(tickfont=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════════════════════════

st.markdown(
    "<h1 style='text-align:center;margin-bottom:0;'>Clinical KPI Report</h1>"
    "<p style='text-align:center;color:#6c757d;font-size:1.2rem;margin-top:4px;'>"
    "Vitaline IV Therapy Program &mdash; January 2026</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# ── SECTION 1: VITALINE ACTIVITY ─────────────────────────────────────────────

st.header("1. Vitaline Activity in January 2026")

st.markdown(
    f"In **January 2026**, Vitaline conducted clinics across **{n_facilities} facilities**. "
    f"A total of **{total_visits} patient visits** were recorded, of which "
    f"**{received_visits}** were infusions actually received by patients."
)

c1, c2, c3 = st.columns(3)
with c1:
    card("Total Patient Visits", f"{total_visits:,}",
         "All visits recorded in January 2026, including received infusions, "
         "billable and non-billable did-not-participate (DNP) records.")
with c2:
    card("Infusions Received", f"{received_visits:,}",
         f"Patients who actually received a Vitaline infusion. "
         f"This is the starting population for our clinical analysis.")
with c3:
    card("Facilities Served", str(n_facilities),
         "Skilled nursing facilities across Accolade Healthcare, "
         "Empire Care Centers, Caliber Consulting Crest, and Paradigm Healthcare.")

with st.expander("View breakdown by participation type"):
    st.dataframe(activity.rename(columns={
        "participation": "Participation", "visits": "Visits",
        "patients": "Unique Patients"
    }), use_container_width=True, hide_index=True)

st.markdown("---")

# ── SECTION 2: ELIGIBLE PATIENTS ─────────────────────────────────────────────

st.header("2. Identifying Eligible Patients")

st.markdown(
    "Not every patient who received an infusion in January qualifies for our clinical "
    "analysis. We apply two criteria to ensure we're measuring patients with a "
    "**meaningful treatment history**:"
)

st.info(
    "**Eligibility Criteria**\n\n"
    "1. **Active in January 2026** — Patient received at least one Vitaline "
    "infusion in the report month.\n"
    "2. **3+ contiguous months of treatment** — The patient must have received "
    "infusions in at least 3 distinct months, counting backwards from January, "
    "with at most a 1-month gap between any two consecutive months.\n\n"
    "For example, a patient who visited in Jan, Dec, and Oct (skipping Nov) qualifies — "
    "the 1-month gap between Oct and Dec is allowed. But a patient who only visited "
    "in Jan and Sep does not qualify (the gap is too large)."
)

c1, c2, c3 = st.columns(3)
with c1:
    card("Patients Active in January", str(received_visits),
         "Total patients who received a Vitaline infusion in January 2026. "
         "Each patient visits once per month.")
with c2:
    card("Eligible Patients", str(n_eligible),
         f"Out of {received_visits} active patients, {n_eligible} "
         f"({pct(n_eligible, received_visits)}) met the 3+ contiguous month "
         f"criteria, meaning they have a sustained treatment history.")
with c3:
    card("Not Eligible", str(received_visits - n_eligible),
         f"These {received_visits - n_eligible} patients had fewer than 3 "
         f"contiguous months of Vitaline treatment and are excluded from the analysis.")

with st.expander(f"View all {received_visits} patients with eligibility details"):
    st.dataframe(data["eligible"].rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "all_visit_months": "All Visit Months", "contiguous_chain": "Contiguous Chain",
        "chain_length": "Chain Length", "eligible": "Eligible", "company": "Company",
    }), use_container_width=True, hide_index=True, height=400)

st.markdown("---")

# ── SECTION 3: LONG-STAY ────────────────────────────────────────────────────

st.header("3. Determining Long-Stay Residents")

st.markdown(
    "The CMS quality measures for falls (KPIs 1 & 2) apply only to **long-stay** residents. "
    "We follow the exact CMS definition from the "
    "*MDS 3.0 Quality Measures User's Manual V17 (January 2025)*:"
)

st.info(
    "**CMS Long-Stay Definition**\n\n"
    "A resident is classified as **long-stay** if their **Cumulative Days in Facility "
    "(CDIF)** is **101 days or more**.\n\n"
    "**How CDIF is calculated:**\n"
    "- We reconstruct each patient's stay history from MDS entry/discharge tracking records.\n"
    "- An **episode** starts with an admission and spans one or more stays.\n"
    "- If a patient is discharged with **return anticipated** and re-enters within "
    "**30 days**, it's a **reentry** within the same episode. Otherwise, it starts a new one.\n"
    "- **CDIF** = total in-facility days across all stays in the latest episode. "
    "Days spent outside (e.g., hospitalized) do **not** count.\n"
    "- Admission vs reentry is determined by **A1700** on the entry record.\n\n"
    "*Source: CMS QM User's Manual V17, Chapter 1 Sections 1-2, Chapter 4*"
)

ls_df = data["longstay"]
median_cdif = int(ls_df[ls_df["is_long_stay"] == True]["cdif"].median()) if n_longstay else 0

c1, c2, c3 = st.columns(3)
with c1:
    card("Eligible Patients", str(n_eligible),
         "These are the 3+ month Vitaline patients identified in Step 2. "
         "We now check how long each has been at their facility.")
with c2:
    card("Long-Stay (101+ Days)", str(n_longstay),
         f"Out of {n_eligible} eligible patients, {n_longstay} "
         f"({pct(n_longstay, n_eligible)}) have been at their facility for "
         f"101 or more cumulative days — qualifying as long-stay per CMS.")
with c3:
    card("Median CDIF", f"{median_cdif} days",
         "Half of the long-stay patients have been at their facility longer than "
         f"this. This indicates a predominantly long-term care population.")

with st.expander(f"View long-stay classification for all {n_eligible} eligible patients"):
    st.dataframe(ls_df.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "episode_start": "Episode Start", "num_stays": "Stays in Episode",
        "stay_details": "Stay Details", "cdif": "CDIF (days)",
        "is_long_stay": "Long-Stay",
    }), use_container_width=True, hide_index=True, height=400)

st.markdown("---")

# ── SECTION 4: KPI 1 — FALLS WITH MAJOR INJURY ──────────────────────────────

st.header("4. KPI 1 — Falls with Major Injury")

st.markdown(
    "This KPI mirrors the CMS quality measure **N013.02** (*\"Percent of Residents "
    "Experiencing One or More Falls with Major Injury — Long Stay\"*). "
    "It answers: **among our long-stay Vitaline patients, what percentage experienced "
    "a fall with major injury?**"
)

st.info(
    "**How it's calculated (exact CMS methodology)**\n\n"
    "1. **Find the target assessment**: the patient's most recent qualifying assessment "
    "within their current episode, no more than 120 days before the episode end.\n"
    "2. **Look-back scan**: from the target assessment, scan all qualifying assessments "
    "going back up to **275 days** within the same episode. This covers approximately "
    "1 year of fall history (3 quarterly assessments x ~93 days each).\n"
    "3. **Qualifying assessments**: OBRA assessments (A0310A = 01-06), PPS 5-day "
    "(A0310B = 01), or discharge assessments (A0310F = 10, 11).\n"
    "4. **Denominator**: patients with at least one scan assessment where J1900C is coded.\n"
    "5. **Numerator**: patients where **J1900C = 1 or 2** on any scan assessment.\n\n"
    "*Source: CMS QM User's Manual V17, Table 2-12, Chapter 1 Section 4*"
)

k1 = data["kpi1"]
k1_ls = k1[k1["is_long_stay"] == True]
k1_denom = int(((k1_ls["has_assessment"] == True)
                 & (k1_ls["excluded"] == False)).sum())
k1_num = int((k1_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"Out of {n_eligible} eligible Vitaline patients, "
         f"{n_longstay} are long-stay residents (CDIF >= 101 days).")
with c2:
    card("In Denominator", str(k1_denom),
         f"Of {n_longstay} long-stay patients, {k1_denom} had qualifying "
         f"assessments where falls with major injury (J1900C) was coded. "
         f"The look-back scan covers up to 275 days of assessments.")
with c3:
    card("Had Major-Injury Fall", str(k1_num),
         f"Of those {k1_denom} assessed patients, {k1_num} had at least one "
         f"assessment reporting a fall with major injury (J1900C = 1 or 2).")
with c4:
    card("Fall with Major Injury Rate", pct(k1_num, k1_denom),
         f"This means {pct(k1_num, k1_denom)} of assessed long-stay "
         f"Vitaline patients experienced a major-injury fall."
         if k1_denom > 0 else "No patients had assessments with J1900C coded.")

with st.expander("View KPI 1 patient-level detail"):
    disp = k1_ls[k1_ls["has_assessment"] == True].copy()
    disp_cols = {"surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
                 "n_assessments": "Assessments Scanned", "item_values": "J1900C Values",
                 "excluded": "Excluded (not coded)", "in_numerator": "Had Major-Injury Fall",
                 "scan_detail": "Scan Window"}
    st.dataframe(disp.rename(columns=disp_cols)[list(disp_cols.values())],
                 use_container_width=True, hide_index=True)

st.markdown("---")

# ── SECTION 5: KPI 2 — PREVALENCE OF FALLS ──────────────────────────────────

st.header("5. KPI 2 — Prevalence of Falls")

st.markdown(
    "This KPI mirrors the CMS quality measure **N032.02** (*\"Prevalence of Falls — "
    "Long Stay\"*). It answers: **what percentage of long-stay Vitaline patients "
    "had any fall at all?**"
)

st.info(
    "**How it's calculated (exact CMS methodology)**\n\n"
    "- Same population and look-back scan as KPI 1.\n"
    "- **Denominator**: Patients with at least one scan assessment where **J1800** "
    "(any fall since prior assessment) is coded.\n"
    "- **Numerator**: Patients where **J1800 = 1** (yes, had a fall) on at least "
    "one assessment in the scan.\n"
    "- **Rate** = Numerator / Denominator\n\n"
    "*Source: CMS QM User's Manual V17, Table 2-32*"
)

k2 = data["kpi2"]
k2_ls = k2[k2["is_long_stay"] == True]
k2_denom = int(((k2_ls["has_assessment"] == True)
                 & (k2_ls["excluded"] == False)).sum())
k2_num = int((k2_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"Out of {n_eligible} eligible Vitaline patients who received 3+ months "
         f"of treatment, {n_longstay} are long-term residents.")
with c2:
    card("In Denominator", str(k2_denom),
         f"Of {n_longstay} long-stay patients, {k2_denom} had qualifying "
         f"assessments where falls (J1800) were coded during the 275-day "
         f"look-back scan.")
with c3:
    card("Had a Fall", str(k2_num),
         f"Of those {k2_denom} assessed patients, {k2_num} had at least one "
         f"assessment reporting a fall (J1800 = 1).")
with c4:
    card("Fall Prevalence Rate", pct(k2_num, k2_denom),
         f"This means {pct(k2_num, k2_denom)} of assessed long-stay "
         f"Vitaline patients had a fall reported in their look-back period."
         if k2_denom > 0 else "No patients had assessments with J1800 coded.")

with st.expander("View KPI 2 patient-level detail"):
    disp2 = k2_ls[k2_ls["has_assessment"] == True].copy()
    disp2_cols = {"surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
                  "n_assessments": "Assessments Scanned", "item_values": "J1800 Values",
                  "excluded": "Excluded (not coded)", "in_numerator": "Had a Fall",
                  "scan_detail": "Scan Window"}
    st.dataframe(disp2.rename(columns=disp2_cols)[list(disp2_cols.values())],
                 use_container_width=True, hide_index=True)

st.markdown("---")

# ── SECTION 6: KPI 3 — PRE/POST FALLS ───────────────────────────────────────

st.header("6. KPI 3 — Did Falls Decrease After Vitaline?")

st.markdown(
    "This KPI compares the rate of falls with major injury **before** a patient "
    "started Vitaline treatment versus **after**. It applies to **all "
    f"{n_eligible} eligible patients** (not just long-stay), answering: "
    "**does Vitaline therapy correlate with fewer major-injury falls?**"
)

st.info(
    "**How the comparison windows work**\n\n"
    "- **PRE Window (90 days)**: The most recent 90-day period when the patient was "
    "**not receiving** Vitaline infusions. We scan gaps between consecutive visits "
    "(latest gap first). If no gap of 90+ days exists, we use the "
    "90 days before their very first Vitaline visit.\n\n"
    "- **POST Window (90 days)**: The 90 days ending January 31, 2026 "
    "(Nov 3, 2025 - Jan 31, 2026).\n\n"
    "For each window, we look at MDS assessments and check whether falls "
    "with major injury (J1900C) were reported.\n\n"
    "- **Part A**: % of patients with at least 1 major-injury fall\n"
    "- **Part B**: % of patients with 2+ major-injury falls on a single assessment"
)

k3 = data["kpi3"]
k3_pre_a = int(k3["pre_any_fall"].sum())
k3_post_a = int(k3["post_any_fall"].sum())
k3_pre_b = int(k3["pre_has_j1900c_2"].sum())
k3_post_b = int(k3["post_has_j1900c_2"].sum())

pre_a_pct = k3_pre_a / n_eligible if n_eligible else 0
post_a_pct = k3_post_a / n_eligible if n_eligible else 0
pre_b_pct = k3_pre_b / n_eligible if n_eligible else 0
post_b_pct = k3_post_b / n_eligible if n_eligible else 0
delta_a = post_a_pct - pre_a_pct
delta_b = post_b_pct - pre_b_pct

st.subheader("Part A — At Least 1 Fall with Major Injury")

c1, c2, c3 = st.columns(3)
with c1:
    card("Before Vitaline", f"{pre_a_pct:.1%}",
         f"{k3_pre_a} out of {n_eligible} eligible patients had at least one "
         f"major-injury fall during the 90 days before starting Vitaline treatment.")
with c2:
    card("After Vitaline", f"{post_a_pct:.1%}",
         f"{k3_post_a} out of {n_eligible} eligible patients had at least one "
         f"major-injury fall during the most recent 90 days of treatment.")
with c3:
    change_card("Change", f"{delta_a:+.1%}",
                "A decrease means fewer patients experienced major-injury falls "
                "after starting Vitaline treatment." if delta_a <= 0
                else "An increase — more patients had major-injury falls after treatment.",
                is_good=delta_a <= 0)

st.subheader("Part B — 2+ Major-Injury Falls on a Single Assessment")

c1, c2, c3 = st.columns(3)
with c1:
    card("Before Vitaline", f"{pre_b_pct:.1%}",
         f"{k3_pre_b} out of {n_eligible} patients had an assessment reporting "
         f"2 or more major-injury falls during the pre-Vitaline period.")
with c2:
    card("After Vitaline", f"{post_b_pct:.1%}",
         f"{k3_post_b} out of {n_eligible} patients had an assessment reporting "
         f"2 or more major-injury falls during the post-Vitaline period.")
with c3:
    change_card("Change", f"{delta_b:+.1%}",
                "No change — very few patients experience 2+ major-injury falls "
                "in a single assessment period." if delta_b == 0
                else ("Improvement." if delta_b < 0 else "Increase."),
                is_good=delta_b <= 0)

fig3 = go.Figure()
fig3.add_trace(go.Bar(
    name="Before Vitaline", x=["At least 1 major-injury fall", "2+ major-injury falls"],
    y=[pre_a_pct, pre_b_pct], marker_color="#6c757d",
    text=[f"{pre_a_pct:.1%}", f"{pre_b_pct:.1%}"], textposition="outside",
))
fig3.add_trace(go.Bar(
    name="After Vitaline", x=["At least 1 major-injury fall", "2+ major-injury falls"],
    y=[post_a_pct, post_b_pct], marker_color="#0d6efd",
    text=[f"{post_a_pct:.1%}", f"{post_b_pct:.1%}"], textposition="outside",
))
fig3.update_layout(
    barmode="group", yaxis_tickformat=".1%", yaxis_title="% of Eligible Patients",
    title="Falls with Major Injury: Before vs After Vitaline",
    height=380, margin=dict(t=50, b=30),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
)
st.plotly_chart(fig3, use_container_width=True)

with st.expander("View KPI 3 patient-level detail"):
    st.dataframe(k3.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "first_vitaline_date": "First Vitaline Date",
        "pre_window_source": "PRE Window Source",
        "pre_window_start": "PRE Start", "pre_window_end": "PRE End",
        "post_window_start": "POST Start", "post_window_end": "POST End",
        "pre_n_assessments": "PRE Assessments", "pre_j1900c_values": "PRE J1900C Values",
        "pre_any_fall": "PRE Any Fall?", "pre_has_j1900c_2": "PRE J1900C=2?",
        "post_n_assessments": "POST Assessments", "post_j1900c_values": "POST J1900C Values",
        "post_any_fall": "POST Any Fall?", "post_has_j1900c_2": "POST J1900C=2?",
    }), use_container_width=True, hide_index=True, height=400)

st.markdown("---")

# ── SECTION 7: KPI 4 — PRE/POST HOSPITALIZATIONS ────────────────────────────

st.header("7. KPI 4 — Did Hospitalizations Decrease After Vitaline?")

st.markdown(
    "This KPI uses the same before/after windows as KPI 3 but examines "
    "**acute care hospitalizations** instead of falls. It answers: "
    "**are Vitaline patients hospitalized less frequently after starting treatment?**"
)

st.info(
    "**How hospitalizations are identified**\n\n"
    "A hospitalization is recorded in the MDS when a patient is **discharged from "
    "the nursing facility** to an **acute care hospital**. Each such discharge "
    "record counts as one hospitalization event.\n\n"
    "- **Part A**: % of patients with at least 1 hospitalization in each window\n"
    "- **Part B**: % of patients with 2 or more hospitalizations in each window"
)

k4 = data["kpi4"]
k4_pre_a = int(k4["pre_has_1plus_hosp"].sum())
k4_post_a = int(k4["post_has_1plus_hosp"].sum())
k4_pre_b = int(k4["pre_has_2plus_hosp"].sum())
k4_post_b = int(k4["post_has_2plus_hosp"].sum())

pre_a4 = k4_pre_a / n_eligible if n_eligible else 0
post_a4 = k4_post_a / n_eligible if n_eligible else 0
pre_b4 = k4_pre_b / n_eligible if n_eligible else 0
post_b4 = k4_post_b / n_eligible if n_eligible else 0
d4a = post_a4 - pre_a4
d4b = post_b4 - pre_b4

st.subheader("Part A — At Least 1 Hospitalization")

c1, c2, c3 = st.columns(3)
with c1:
    card("Before Vitaline", f"{pre_a4:.1%}",
         f"{k4_pre_a} out of {n_eligible} eligible patients were hospitalized "
         f"at least once during the 90 days before Vitaline treatment.")
with c2:
    card("After Vitaline", f"{post_a4:.1%}",
         f"{k4_post_a} out of {n_eligible} eligible patients were hospitalized "
         f"at least once during the most recent 90 days of treatment.")
with c3:
    change_card("Change", f"{d4a:+.1%}",
                "A decrease means fewer patients required acute hospitalization "
                "after starting Vitaline treatment." if d4a <= 0
                else "An increase in hospitalizations after treatment.",
                is_good=d4a <= 0)

st.subheader("Part B — 2 or More Hospitalizations")

c1, c2, c3 = st.columns(3)
with c1:
    card("Before Vitaline", f"{pre_b4:.1%}",
         f"{k4_pre_b} out of {n_eligible} patients were hospitalized "
         f"2 or more times during the pre-Vitaline period.")
with c2:
    card("After Vitaline", f"{post_b4:.1%}",
         f"{k4_post_b} out of {n_eligible} patients were hospitalized "
         f"2 or more times during the post-Vitaline period.")
with c3:
    change_card("Change", f"{d4b:+.1%}",
                "Fewer patients experienced repeated hospitalizations "
                "after starting Vitaline." if d4b <= 0
                else "More patients had repeated hospitalizations.",
                is_good=d4b <= 0)

fig4 = go.Figure()
fig4.add_trace(go.Bar(
    name="Before Vitaline", x=["At least 1 hospitalization", "2+ hospitalizations"],
    y=[pre_a4, pre_b4], marker_color="#6c757d",
    text=[f"{pre_a4:.1%}", f"{pre_b4:.1%}"], textposition="outside",
))
fig4.add_trace(go.Bar(
    name="After Vitaline", x=["At least 1 hospitalization", "2+ hospitalizations"],
    y=[post_a4, post_b4], marker_color="#198754",
    text=[f"{post_a4:.1%}", f"{post_b4:.1%}"], textposition="outside",
))
fig4.update_layout(
    barmode="group", yaxis_tickformat=".1%", yaxis_title="% of Eligible Patients",
    title="Hospitalizations: Before vs After Vitaline",
    height=380, margin=dict(t=50, b=30),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
)
st.plotly_chart(fig4, use_container_width=True)

with st.expander("View KPI 4 patient-level detail"):
    st.dataframe(k4.rename(columns={
        "surrogate_patient_id": "Patient ID", "surrogate_facility_id": "Facility",
        "pre_window_source": "PRE Window Source",
        "pre_window_start": "PRE Start", "pre_window_end": "PRE End",
        "post_window_start": "POST Start", "post_window_end": "POST End",
        "pre_n_discharges": "PRE Discharges", "pre_n_hospitalizations": "PRE Hospitalizations",
        "pre_has_1plus_hosp": "PRE >=1?", "pre_has_2plus_hosp": "PRE >=2?",
        "post_n_discharges": "POST Discharges", "post_n_hospitalizations": "POST Hospitalizations",
        "post_has_1plus_hosp": "POST >=1?", "post_has_2plus_hosp": "POST >=2?",
    }), use_container_width=True, hide_index=True, height=400)

st.markdown("---")

# ── SECTION 8: FACILITY BREAKDOWN ───────────────────────────────────────────

st.header("8. Results by Facility")

fac = data["summary"][data["summary"]["Facility"] != "OVERALL"].copy()
fac = fac[fac["Eligible Patients"] > 0]

display_cols = {
    "Facility": "Facility",
    "Company": "Company",
    "Eligible Patients": "Eligible Patients",
    "Long-Stay Patients": "Long-Stay Patients",
    "KPI1 Denom": "Falls Major Injury — Assessed",
    "KPI1 Num": "Falls Major Injury — Had Fall",
    "KPI1 Rate": "Falls Major Injury — Rate",
    "KPI2 Denom": "Any Fall — Assessed",
    "KPI2 Num": "Any Fall — Had Fall",
    "KPI2 Rate": "Any Fall — Rate",
    "KPI3-A Pre %": "Falls Pre-Vitaline %",
    "KPI3-A Post %": "Falls Post-Vitaline %",
    "KPI4-A Pre %": "Hosp Pre-Vitaline %",
    "KPI4-A Post %": "Hosp Post-Vitaline %",
}

display_fac = fac[list(display_cols.keys())].rename(columns=display_cols)
pct_cols = ["Falls Major Injury — Rate", "Any Fall — Rate",
            "Falls Pre-Vitaline %", "Falls Post-Vitaline %",
            "Hosp Pre-Vitaline %", "Hosp Post-Vitaline %"]

st.dataframe(
    display_fac.style.format(
        {c: "{:.1%}" for c in pct_cols}, na_rep="—"
    ),
    use_container_width=True, hide_index=True, height=500,
)

st.markdown("---")

# ── SECTION 9: KPI DISTRIBUTION ACROSS FACILITIES ───────────────────────────

st.header("9. KPI Distribution Across Facilities")

st.markdown(
    "The charts below show how each KPI varies across individual facilities, "
    "making it easy to spot outliers and compare performance."
)

tab1, tab2, tab3, tab4 = st.tabs([
    "Fall Prevalence (KPI 2)", "Falls Pre vs Post (KPI 3)",
    "Hosp Pre vs Post (KPI 4)", "Eligible & Long-Stay Counts",
])

with tab1:
    st.subheader("KPI 2 — Fall Prevalence Rate by Facility")
    st.caption("Percentage of assessed long-stay patients who had a fall. "
               "Facilities with no assessed patients are omitted.")
    facility_distribution_chart(
        fac, "KPI2 Rate",
        "Fall Prevalence Rate by Facility (January 2026)",
        color="#dc3545",
    )

with tab2:
    st.subheader("KPI 3 — Falls Before vs After Vitaline by Facility")
    st.caption("Percentage of eligible patients with at least 1 major-injury fall. "
               "Gray = before Vitaline, blue = after.")
    plot_k3 = fac[["Facility", "Company", "KPI3-A Pre %", "KPI3-A Post %"]].copy()
    plot_k3 = plot_k3.sort_values("KPI3-A Pre %", ascending=True)
    labels_k3 = plot_k3["Facility"] + " — " + plot_k3["Company"].fillna("")

    fig_k3 = go.Figure()
    fig_k3.add_trace(go.Bar(
        name="Before Vitaline", y=labels_k3, x=plot_k3["KPI3-A Pre %"],
        orientation="h", marker_color="#6c757d",
        text=plot_k3["KPI3-A Pre %"].apply(lambda v: f"{v:.1%}" if pd.notna(v) else ""),
        textposition="outside",
    ))
    fig_k3.add_trace(go.Bar(
        name="After Vitaline", y=labels_k3, x=plot_k3["KPI3-A Post %"],
        orientation="h", marker_color="#0d6efd",
        text=plot_k3["KPI3-A Post %"].apply(lambda v: f"{v:.1%}" if pd.notna(v) else ""),
        textposition="outside",
    ))
    fig_k3.update_layout(
        barmode="group", xaxis_tickformat=".0%",
        height=max(400, len(plot_k3) * 32 + 80),
        margin=dict(l=10, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig_k3, use_container_width=True)

with tab3:
    st.subheader("KPI 4 — Hospitalizations Before vs After Vitaline by Facility")
    st.caption("Percentage of eligible patients with at least 1 hospitalization. "
               "Gray = before Vitaline, green = after.")
    plot_k4 = fac[["Facility", "Company", "KPI4-A Pre %", "KPI4-A Post %"]].copy()
    plot_k4 = plot_k4.sort_values("KPI4-A Pre %", ascending=True)
    labels_k4 = plot_k4["Facility"] + " — " + plot_k4["Company"].fillna("")

    fig_k4 = go.Figure()
    fig_k4.add_trace(go.Bar(
        name="Before Vitaline", y=labels_k4, x=plot_k4["KPI4-A Pre %"],
        orientation="h", marker_color="#6c757d",
        text=plot_k4["KPI4-A Pre %"].apply(lambda v: f"{v:.1%}" if pd.notna(v) else ""),
        textposition="outside",
    ))
    fig_k4.add_trace(go.Bar(
        name="After Vitaline", y=labels_k4, x=plot_k4["KPI4-A Post %"],
        orientation="h", marker_color="#198754",
        text=plot_k4["KPI4-A Post %"].apply(lambda v: f"{v:.1%}" if pd.notna(v) else ""),
        textposition="outside",
    ))
    fig_k4.update_layout(
        barmode="group", xaxis_tickformat=".0%",
        height=max(400, len(plot_k4) * 32 + 80),
        margin=dict(l=10, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig_k4, use_container_width=True)

with tab4:
    st.subheader("Eligible & Long-Stay Patient Counts by Facility")
    st.caption("Number of eligible Vitaline patients and how many are long-stay.")
    plot_cnt = fac[["Facility", "Company", "Eligible Patients", "Long-Stay Patients"]].copy()
    plot_cnt = plot_cnt.sort_values("Eligible Patients", ascending=True)
    labels_cnt = plot_cnt["Facility"] + " — " + plot_cnt["Company"].fillna("")

    fig_cnt = go.Figure()
    fig_cnt.add_trace(go.Bar(
        name="Eligible", y=labels_cnt, x=plot_cnt["Eligible Patients"],
        orientation="h", marker_color="#0d6efd",
    ))
    fig_cnt.add_trace(go.Bar(
        name="Long-Stay", y=labels_cnt, x=plot_cnt["Long-Stay Patients"],
        orientation="h", marker_color="#6610f2",
    ))
    fig_cnt.update_layout(
        barmode="group",
        height=max(400, len(plot_cnt) * 32 + 80),
        margin=dict(l=10, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig_cnt, use_container_width=True)

st.markdown("---")

# ── FOOTER ───────────────────────────────────────────────────────────────────

st.markdown(
    "<p style='text-align:center;color:#868e96;padding:20px;font-size:0.85rem;'>"
    "<strong>Data Sources</strong>: MDS 3.0 assessments (188,250 records) &bull; "
    "Vitaline booking log (30,550 records) &bull; 41 facilities<br>"
    "<strong>Methodology</strong>: CMS MDS 3.0 Quality Measures User's Manual V17 "
    "(Effective January 1, 2025)<br>"
    "<strong>Note</strong>: All data is de-identified. No Protected Health Information "
    "(PHI) is stored or displayed.<br>"
    "Generated March 2026</p>",
    unsafe_allow_html=True,
)
