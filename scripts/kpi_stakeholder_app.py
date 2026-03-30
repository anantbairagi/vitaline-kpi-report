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
    st.error("Report not found. Run `python scripts/generate_kpi_report.py` first.")
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

# ── KEY DEFINITIONS (always visible) ─────────────────────────────────────────

st.info(
    "**Key Definitions**\n\n"
    "- **Eligible Patient**: Received a Vitaline infusion in the report month "
    "with 3+ contiguous months of treatment (1-month gap allowed).\n"
    "- **Long-Stay**: Cumulative days in facility (CDIF) of 101+ days, per CMS.\n"
    "- **Episode**: Continuous care at a facility. Starts with admission. "
    "If discharged and returned within 30 days, it's a reentry in the same episode.\n"
    "- **Target Assessment**: Patient's most recent qualifying MDS assessment, "
    "no more than 120 days before episode end.\n"
    "- **Target Date**: Entry date for entries, discharge date for discharges, "
    "Assessment Reference Date (ARD) for everything else.\n"
    "- **Qualifying Assessment**: OBRA (A0310A = 01-06), PPS (A0310B = 01-06), "
    "or discharge (A0310F = 10, 11).\n"
    "- **Look-back Scan**: From the target assessment, scan all qualifying "
    "assessments going back up to 275 days within the episode (~1 year of history).\n\n"
    "*Source: CMS MDS 3.0 Quality Measures User's Manual V17 (January 2025)*"
)
st.markdown("---")

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
st.markdown("---")

# ── SECTION 2 ────────────────────────────────────────────────────────────────

st.header("2. Identifying Eligible Patients")
st.info("**Eligibility Criteria**\n\n"
        "1. **Active in January 2026** — received at least one infusion.\n"
        "2. **3+ contiguous months** — counting backwards from January, infusions in at least "
        "3 distinct months with at most a 1-month gap.")

c1, c2, c3 = st.columns(3)
with c1:
    card("Active Patients", str(received_visits),
         "Patients who received a Vitaline infusion in January 2026.")
with c2:
    card("Eligible Patients", str(n_eligible),
         f"{pct(n_eligible, received_visits)} of active patients met the 3+ contiguous month "
         f"criteria -- they have a sustained treatment history.")
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
st.info("**Long-Stay Definition** (CMS V17)\n\n"
        "A resident is long-stay if their **Cumulative Days in Facility (CDIF) is 101+ days**.\n\n"
        "- Stay history reconstructed from MDS entry/discharge records.\n"
        "- Admission vs reentry determined by **A1700** on the entry record.\n"
        "- CDIF counts only in-facility days. Hospital days do not count.\n\n"
        "*Source: CMS QM V17, Chapter 1 Section 1, Chapter 4*")

ls_df = data["longstay"]
median_cdif = int(ls_df[ls_df["is_long_stay"] == True]["cdif"].median()) if n_longstay else 0

c1, c2, c3 = st.columns(3)
with c1:
    card("Eligible Patients", str(n_eligible), "From Step 2 -- patients with 3+ months of treatment.")
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

st.header("4. KPI 1 -- Falls with Major Injury")
st.markdown("CMS measure **N013.02**: *Percent of Residents Experiencing One or More Falls "
            "with Major Injury (Long Stay)*.")
st.info("**How it's calculated** (CMS V17)\n\n"
        "1. Find the **target assessment** -- most recent qualifying assessment within the "
        "current episode, no more than 120 days before episode end.\n"
        "2. **Look-back scan** -- from the target, scan all qualifying assessments going back "
        "up to 275 days within the episode (~1 year).\n"
        "3. **Denominator**: long-stay patients with at least one scan assessment where "
        "J1900C (falls with major injury) was coded.\n"
        "4. **Numerator**: patients where J1900C = 1 or 2 on any scan assessment.\n\n"
        "*Source: CMS V17, Table 2-12, Chapter 1 Section 4*")

k1 = data["kpi1"]
k1_ls = k1[k1["is_long_stay"] == True]
k1_denom = int(((k1_ls["has_assessment"] == True) & (k1_ls["excluded"] == False)).sum())
k1_num = int((k1_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"<b>{n_longstay}</b> eligible patients with 101+ cumulative days at their facility.")
with c2:
    card("In Denominator", str(k1_denom),
         f"Of <b>{n_longstay}</b> long-stay patients, <b>{k1_denom}</b> had qualifying "
         f"assessments where J1900C was coded during the ~1 year look-back scan.")
with c3:
    card("Had Major-Injury Fall", str(k1_num),
         f"Of those <b>{k1_denom}</b> patients, <b>{k1_num}</b> had at least one assessment "
         f"reporting a fall with major injury during the scan period.")
with c4:
    card("Rate", pct(k1_num, k1_denom),
         f"<b>{pct(k1_num, k1_denom)}</b> of assessed long-stay Vitaline patients experienced "
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

st.header("5. KPI 2 -- Prevalence of Falls")
st.markdown("CMS measure **N032.02**: *Prevalence of Falls (Long Stay)*.")
st.info("**How it's calculated** (CMS V17)\n\n"
        "1. Find the **target assessment** -- most recent qualifying assessment within the "
        "current episode, no more than 120 days before episode end.\n"
        "2. **Look-back scan** -- from the target, scan all qualifying assessments going back "
        "up to 275 days within the episode (~1 year).\n"
        "3. **Denominator**: long-stay patients with at least one scan assessment where "
        "J1800 (any fall since prior assessment) was coded.\n"
        "4. **Numerator**: patients where J1800 = 1 (yes, had a fall) on any scan assessment.\n\n"
        "*Source: CMS V17, Table 2-32*")

k2 = data["kpi2"]
k2_ls = k2[k2["is_long_stay"] == True]
k2_denom = int(((k2_ls["has_assessment"] == True) & (k2_ls["excluded"] == False)).sum())
k2_num = int((k2_ls["in_numerator"] == True).sum())

c1, c2, c3, c4 = st.columns(4)
with c1:
    card("Long-Stay Patients", str(n_longstay),
         f"<b>{n_longstay}</b> eligible patients with 101+ cumulative days at their facility.")
with c2:
    card("In Denominator", str(k2_denom),
         f"Of <b>{n_longstay}</b> long-stay patients, <b>{k2_denom}</b> had qualifying "
         f"assessments where J1800 was coded during the ~1 year look-back scan.")
with c3:
    card("Had a Fall", str(k2_num),
         f"Of those <b>{k2_denom}</b> patients, <b>{k2_num}</b> had at least one assessment "
         f"reporting a fall during the scan period.")
with c4:
    card("Rate", pct(k2_num, k2_denom),
         f"<b>{pct(k2_num, k2_denom)}</b> of assessed long-stay Vitaline patients had a fall "
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

st.header("6. KPI 3 -- Falls: Non-Vitaline Period vs Vitaline Treatment Period")
st.markdown(f"Compares major-injury falls **before** Vitaline versus **during** treatment "
            f"for all <b>{n_eligible}</b> eligible patients.", unsafe_allow_html=True)
st.info("**How it works**\n\n"
        "- **Non-Vitaline Period**: Most recent 90 or 120 days when the patient was "
        "not receiving Vitaline infusions.\n"
        "- **Vitaline Treatment Period**: Most recent 90 or 120 days ending Jan 31, 2026.\n\n"
        "For each period, we check MDS assessments for falls with major injury (J1900C):\n"
        "- **Part A**: patients with at least 1 major-injury fall (J1900C = 1 or 2)\n"
        "- **Part B**: patients with 2+ major-injury falls within a single assessment "
        "period (J1900C = 2)")

k3 = data["kpi3"]

for wd in (90, 120):
    s = f"_{wd}d"
    st.subheader(f"{wd}-Day Window")

    pre_a = int(k3[f"pre_any_fall{s}"].sum())
    post_a = int(k3[f"post_any_fall{s}"].sum())
    pre_b = int(k3[f"pre_j1900c2{s}"].sum())
    post_b = int(k3[f"post_j1900c2{s}"].sum())

    pa_pct = pre_a / n_eligible if n_eligible else 0
    oa_pct = post_a / n_eligible if n_eligible else 0
    da = oa_pct - pa_pct

    pb_pct = pre_b / n_eligible if n_eligible else 0
    ob_pct = post_b / n_eligible if n_eligible else 0
    db = ob_pct - pb_pct

    st.markdown(f"**Part A -- At least 1 major-injury fall** "
                f"(<b>{pre_a}</b> non-Vitaline vs <b>{post_a}</b> Vitaline)",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pa_pct:.1%}",
             f"<b>{pre_a}</b> of <b>{n_eligible}</b> patients had a major-injury fall "
             f"during the {wd} days before Vitaline treatment.")
    with c2:
        card("Vitaline Treatment Period", f"{oa_pct:.1%}",
             f"<b>{post_a}</b> of <b>{n_eligible}</b> patients had a major-injury fall "
             f"during the most recent {wd} days of treatment.")
    with c3:
        change_card("Change", f"{da:+.1%}",
                    "Fewer patients experienced major-injury falls during Vitaline treatment."
                    if da <= 0 else "More patients had falls during treatment.", da <= 0)

    st.markdown(f"**Part B -- 2+ major-injury falls in a single assessment period** "
                f"(<b>{pre_b}</b> non-Vitaline vs <b>{post_b}</b> Vitaline)",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pb_pct:.1%}",
             f"<b>{pre_b}</b> of <b>{n_eligible}</b> patients had 2+ major-injury falls "
             f"within a single assessment period (J1900C = 2) during the {wd}-day non-Vitaline window.")
    with c2:
        card("Vitaline Treatment Period", f"{ob_pct:.1%}",
             f"<b>{post_b}</b> of <b>{n_eligible}</b> patients had 2+ major-injury falls "
             f"within a single assessment period during the {wd}-day Vitaline window.")
    with c3:
        change_card("Change", f"{db:+.1%}",
                    "Fewer patients had repeated major-injury falls."
                    if db <= 0 else "More patients had repeated falls.", db <= 0)
    st.markdown("")

st.markdown(
    "<div style='background:#e8f4f8;border-radius:8px;padding:14px 16px;border:1px solid #b8daff;'>"
    "<p style='margin:0 0 6px 0;font-weight:600;color:#004085;'>How to read these results</p>"
    "<p style='margin:0;font-size:0.88rem;color:#004085;'>"
    "A <b>negative change</b> (green) means fewer patients experienced falls during Vitaline "
    "treatment compared to the period before treatment -- suggesting a positive impact. "
    "For example, if Non-Vitaline shows 1.3% and Vitaline shows 0.8%, that means the rate "
    "dropped by 0.5 percentage points. The 120-day window captures more assessment data "
    "than 90 days, giving a broader view of the trend.</p></div>",
    unsafe_allow_html=True)

with st.expander("View KPI 3 patient-level detail"):
    st.dataframe(k3, use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 7: KPI 4 ────────────────────────────────────────────────────────

st.header("7. KPI 4 -- Hospitalizations: Non-Vitaline vs Vitaline Period")
st.markdown(f"Same comparison for <b>acute care hospitalizations</b> -- when a patient is "
            f"discharged to a hospital. All <b>{n_eligible}</b> eligible patients.",
            unsafe_allow_html=True)
st.info("**How hospitalizations are counted**\n\n"
        "A hospitalization = discharge record (A0310F = 10 or 11) to an acute care hospital "
        "(discharge_status = '04').\n\n"
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

    pb_pct = pre_b / n_eligible if n_eligible else 0
    ob_pct = post_b / n_eligible if n_eligible else 0
    db = ob_pct - pb_pct

    st.markdown(f"**Part A -- At least 1 hospitalization** "
                f"(<b>{pre_a}</b> non-Vitaline vs <b>{post_a}</b> Vitaline)",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pa_pct:.1%}",
             f"<b>{pre_a}</b> of <b>{n_eligible}</b> patients were hospitalized at least once "
             f"during the {wd} days before Vitaline treatment.")
    with c2:
        card("Vitaline Treatment Period", f"{oa_pct:.1%}",
             f"<b>{post_a}</b> of <b>{n_eligible}</b> patients were hospitalized at least once "
             f"during the most recent {wd} days of treatment.")
    with c3:
        change_card("Change", f"{da:+.1%}",
                    "Fewer patients required hospitalization during Vitaline treatment."
                    if da <= 0 else "More hospitalizations during treatment.", da <= 0)

    st.markdown(f"**Part B -- 2+ hospitalizations** "
                f"(<b>{pre_b}</b> non-Vitaline vs <b>{post_b}</b> Vitaline)",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        card("Non-Vitaline Period", f"{pb_pct:.1%}",
             f"<b>{pre_b}</b> of <b>{n_eligible}</b> patients were hospitalized 2+ times "
             f"during the {wd}-day non-Vitaline window.")
    with c2:
        card("Vitaline Treatment Period", f"{ob_pct:.1%}",
             f"<b>{post_b}</b> of <b>{n_eligible}</b> patients were hospitalized 2+ times "
             f"during the {wd}-day Vitaline window.")
    with c3:
        change_card("Change", f"{db:+.1%}",
                    "Fewer patients had repeated hospitalizations."
                    if db <= 0 else "More repeated hospitalizations.", db <= 0)
    st.markdown("")

st.markdown(
    "<div style='background:#e8f4f8;border-radius:8px;padding:14px 16px;border:1px solid #b8daff;'>"
    "<p style='margin:0 0 6px 0;font-weight:600;color:#004085;'>How to read these results</p>"
    "<p style='margin:0;font-size:0.88rem;color:#004085;'>"
    "A <b>negative change</b> (green) means fewer patients were hospitalized during Vitaline "
    "treatment. For example, in the 120-day window, hospitalization dropped from <b>11.3%</b> "
    "(non-Vitaline) to <b>5.2%</b> (Vitaline) -- a <b>6.0 percentage point decrease</b>, "
    "meaning roughly half as many patients required acute hospitalization after starting "
    "Vitaline IV therapy.</p></div>",
    unsafe_allow_html=True)

with st.expander("View KPI 4 patient-level detail"):
    st.dataframe(k4, use_container_width=True, hide_index=True, height=400)
st.markdown("---")

# ── SECTION 8: FACILITY TABLE ────────────────────────────────────────────────

st.header("8. All KPIs by Facility")
st.markdown("Complete analysis for every facility. Hover over any column header for a description.")

fac = data["summary"][data["summary"]["Facility"] != "OVERALL"].copy()
fac = fac[fac["Eligible Patients"] > 0]


def _build_review_table(src):
    """Build a clean review table with descriptive columns from summary data."""
    def _pct(n, d):
        return n / d if d > 0 else None

    rows = []
    for _, r in src.iterrows():
        ne = r["Eligible Patients"]
        row = {
            "Facility": r.get("Facility", ""),
            "Company": r.get("Company", ""),
            "Eligible": int(ne),
            "Long-Stay": int(r["Long-Stay Patients"]),
            "KPI1 Assessed": int(r["KPI1 Denom"]),
            "KPI1 Had Fall": int(r["KPI1 Num"]),
            "KPI1 Rate": r["KPI1 Rate"],
            "KPI2 Assessed": int(r["KPI2 Denom"]),
            "KPI2 Had Fall": int(r["KPI2 Num"]),
            "KPI2 Rate": r["KPI2 Rate"],
        }
        for wd in (90, 120):
            pfx = f"{wd}d"
            pre_f = int(r.get(f"KPI3 Pre >=1 fall {wd}d", 0))
            post_f = int(r.get(f"KPI3 Post >=1 fall {wd}d", 0))
            pre_fb = int(r.get(f"KPI3 Pre J1900C=2 {wd}d", 0))
            post_fb = int(r.get(f"KPI3 Post J1900C=2 {wd}d", 0))
            pre_h = int(r.get(f"KPI4 Pre >=1 hosp {wd}d", 0))
            post_h = int(r.get(f"KPI4 Post >=1 hosp {wd}d", 0))
            pre_hb = int(r.get(f"KPI4 Pre >=2 hosp {wd}d", 0))
            post_hb = int(r.get(f"KPI4 Post >=2 hosp {wd}d", 0))

            row.update({
                f"Falls Pre {pfx}": pre_f,
                f"Falls Post {pfx}": post_f,
                f"Falls Pre% {pfx}": _pct(pre_f, ne),
                f"Falls Post% {pfx}": _pct(post_f, ne),
                f"Falls J1900C=2 Pre {pfx}": pre_fb,
                f"Falls J1900C=2 Post {pfx}": post_fb,
                f"Hosp Pre {pfx}": pre_h,
                f"Hosp Post {pfx}": post_h,
                f"Hosp Pre% {pfx}": _pct(pre_h, ne),
                f"Hosp Post% {pfx}": _pct(post_h, ne),
                f"Hosp 2+ Pre {pfx}": pre_hb,
                f"Hosp 2+ Post {pfx}": post_hb,
            })
        rows.append(row)
    df = pd.DataFrame(rows)
    pct_cols = [c for c in df.columns if "Rate" in c or "%" in c]
    for c in pct_cols:
        df[c] = df[c].apply(lambda v: v * 100 if pd.notna(v) else None)
    return df


def _column_config(include_facility=True):
    """Column config with help tooltips for every column."""
    cfg = {}
    if include_facility:
        cfg["Facility"] = st.column_config.TextColumn("Facility", help="De-identified facility ID")
    cfg.update({
        "Company": st.column_config.TextColumn("Company", help="Parent company"),
        "Eligible": st.column_config.NumberColumn("Eligible", help="Vitaline patients with 3+ contiguous months of treatment, active in Jan 2026"),
        "Long-Stay": st.column_config.NumberColumn("Long-Stay", help="Eligible patients with 101+ cumulative days at facility (CMS CDIF)"),
        "KPI1 Assessed": st.column_config.NumberColumn("KPI1 Assessed", help="Long-stay patients with J1900C coded in the 275-day look-back scan (denominator)"),
        "KPI1 Had Fall": st.column_config.NumberColumn("KPI1 Had Fall", help="Patients with J1900C = 1 or 2 (numerator) -- had a fall with major injury"),
        "KPI1 Rate": st.column_config.NumberColumn("KPI1 Rate", format="%.1f%%", help="Falls with Major Injury rate (CMS N013.02). Numerator / Denominator x 100"),
        "KPI2 Assessed": st.column_config.NumberColumn("KPI2 Assessed", help="Long-stay patients with J1800 coded in the 275-day look-back scan (denominator)"),
        "KPI2 Had Fall": st.column_config.NumberColumn("KPI2 Had Fall", help="Patients with J1800 = 1 (numerator) -- had any fall"),
        "KPI2 Rate": st.column_config.NumberColumn("KPI2 Rate", format="%.1f%%", help="Prevalence of Falls rate (CMS N032.02). Numerator / Denominator x 100"),
    })
    for wd in (90, 120):
        pfx = f"{wd}d"
        cfg.update({
            f"Falls Pre {pfx}": st.column_config.NumberColumn(f"Falls Pre {pfx}", help=f"Patients with >=1 major-injury fall during {wd}-day non-Vitaline period"),
            f"Falls Post {pfx}": st.column_config.NumberColumn(f"Falls Post {pfx}", help=f"Patients with >=1 major-injury fall during {wd}-day Vitaline treatment period"),
            f"Falls Pre% {pfx}": st.column_config.NumberColumn(f"Falls Pre% {pfx}", format="%.1f%%", help=f"% of eligible with >=1 fall in {wd}d non-Vitaline period"),
            f"Falls Post% {pfx}": st.column_config.NumberColumn(f"Falls Post% {pfx}", format="%.1f%%", help=f"% of eligible with >=1 fall in {wd}d Vitaline period"),
            f"Falls J1900C=2 Pre {pfx}": st.column_config.NumberColumn(f"J1900C=2 Pre {pfx}", help=f"Patients with 2+ major-injury falls in single assessment ({wd}d non-Vitaline)"),
            f"Falls J1900C=2 Post {pfx}": st.column_config.NumberColumn(f"J1900C=2 Post {pfx}", help=f"Patients with 2+ major-injury falls in single assessment ({wd}d Vitaline)"),
            f"Hosp Pre {pfx}": st.column_config.NumberColumn(f"Hosp Pre {pfx}", help=f"Patients with >=1 acute hospitalization during {wd}-day non-Vitaline period"),
            f"Hosp Post {pfx}": st.column_config.NumberColumn(f"Hosp Post {pfx}", help=f"Patients with >=1 acute hospitalization during {wd}-day Vitaline treatment period"),
            f"Hosp Pre% {pfx}": st.column_config.NumberColumn(f"Hosp Pre% {pfx}", format="%.1f%%", help=f"% of eligible with >=1 hospitalization in {wd}d non-Vitaline period"),
            f"Hosp Post% {pfx}": st.column_config.NumberColumn(f"Hosp Post% {pfx}", format="%.1f%%", help=f"% of eligible with >=1 hospitalization in {wd}d Vitaline period"),
            f"Hosp 2+ Pre {pfx}": st.column_config.NumberColumn(f"Hosp 2+ Pre {pfx}", help=f"Patients with 2+ hospitalizations ({wd}d non-Vitaline)"),
            f"Hosp 2+ Post {pfx}": st.column_config.NumberColumn(f"Hosp 2+ Post {pfx}", help=f"Patients with 2+ hospitalizations ({wd}d Vitaline)"),
        })
    return cfg


fac_table = _build_review_table(fac)

st.dataframe(fac_table, column_config=_column_config(include_facility=True),
             use_container_width=True, hide_index=True, height=600)
st.markdown("---")

# ── SECTION 9: COMPANY TABLE ────────────────────────────────────────────────

st.header("9. All KPIs by Company")
st.markdown("Same analysis aggregated at the company level.")

company_groups = fac.groupby("Company")
company_rows = []
for company, grp in company_groups:
    agg = {"Facility": "", "Company": company}
    for col in fac.columns:
        if col in ("Facility", "Company"):
            continue
        vals = grp[col].dropna()
        if "Rate" in col or "%" in col:
            continue
        agg[col] = vals.sum()

    ne = agg.get("Eligible Patients", 0)
    k1d = agg.get("KPI1 Denom", 0)
    k2d = agg.get("KPI2 Denom", 0)
    agg["KPI1 Rate"] = agg.get("KPI1 Num", 0) / k1d if k1d > 0 else None
    agg["KPI2 Rate"] = agg.get("KPI2 Num", 0) / k2d if k2d > 0 else None
    for wd in (90, 120):
        for k in (f"KPI3 Pre >=1 fall {wd}d %", f"KPI3 Post >=1 fall {wd}d %",
                  f"KPI3 Pre 2+ falls {wd}d %", f"KPI3 Post 2+ falls {wd}d %",
                  f"KPI4 Pre >=1 hosp {wd}d %", f"KPI4 Post >=1 hosp {wd}d %",
                  f"KPI4 Pre >=2 hosp {wd}d %", f"KPI4 Post >=2 hosp {wd}d %"):
            num_col = k.replace(" %", "")
            agg[k] = agg.get(num_col, 0) / ne if ne > 0 else None

    company_rows.append(pd.Series(agg))

company_df = pd.DataFrame(company_rows)
company_table = _build_review_table(company_df)
company_table = company_table.drop(columns=["Facility"], errors="ignore")

st.dataframe(company_table, column_config=_column_config(include_facility=False),
             use_container_width=True, hide_index=True, height=300)
st.markdown("---")

# ── SECTION 10: DISTRIBUTIONS ───────────────────────────────────────────────

st.header("10. KPI Distribution Across Facilities")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Falls Major Injury (KPI 1)", "Fall Prevalence (KPI 2)",
    "Falls Pre vs Post (KPI 3)", "Hosp Pre vs Post (KPI 4)", "Patient Counts"])

with tab1:
    dist_chart(fac, "KPI1 Rate", "Falls with Major Injury Rate by Facility", "#dc3545")
    st.caption("Each bar shows the percentage of assessed long-stay patients at that facility "
               "who had a major-injury fall. Longer bars = higher fall rates.")
with tab2:
    dist_chart(fac, "KPI2 Rate", "Fall Prevalence Rate by Facility", "#fd7e14")
    st.caption("Each bar shows the percentage of assessed long-stay patients who had any fall. "
               "Compare your facility against others to spot outliers.")
with tab3:
    st.caption("90-day window: % of eligible patients with at least 1 major-injury fall. "
               "Gray = non-Vitaline period, blue = Vitaline treatment period.")
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
    st.caption("If the blue bar is shorter than the gray bar for a facility, that facility "
               "shows improvement during Vitaline treatment.")
with tab4:
    st.caption("90-day window: % of eligible patients with at least 1 hospitalization. "
               "Gray = non-Vitaline, green = Vitaline treatment.")
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
    st.caption("A shorter green bar compared to gray means fewer hospitalizations during "
               "Vitaline treatment at that facility.")
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
    st.caption("Blue = eligible Vitaline patients, purple = those classified as long-stay. "
               "Facilities with more patients contribute more to the overall KPI rates.")

st.markdown("---")
st.markdown(
    "<p style='text-align:center;color:#868e96;padding:20px;font-size:0.85rem;'>"
    "<strong>Data</strong>: MDS 3.0 assessments (188,250 records) &bull; "
    "Vitaline booking log (30,550 records) &bull; 41 facilities<br>"
    "<strong>Methodology</strong>: CMS MDS 3.0 Quality Measures User's Manual V17 "
    "(January 2025)<br>"
    "<strong>Privacy</strong>: All data is de-identified. No PHI.</p>",
    unsafe_allow_html=True)
