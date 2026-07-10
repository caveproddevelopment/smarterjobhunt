"""
Job Hunt Agent — Gradio UI
Bypass job boards. Find roles at VC-funded companies directly.

Two separate tools, wired to two separate buttons:
  1. Find Jobs      -> agent.job_orchestrator.run()               (no Apollo calls)
  2. Find Contacts  -> agent.contact_orchestrator.enrich_with_contacts()  (on-demand, Apollo)

Contacts are no longer fetched automatically for every company. You run
Job Finder first, look at the results, and then decide whether to spend
Apollo lookups on the listings, the cold-outreach companies, or both.
"""

import os
import json
import pandas as pd
import gradio as gr

from agent.job_orchestrator import run as find_jobs
from agent.contact_orchestrator import enrich_with_contacts

# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────────────────────────────────────

CRUNCHBASE_COL_MAP = {
    "Organization Name":   "company_name",
    "Name":                "company_name",
    "Company":             "company_name",
    "Website":             "website",
    "Homepage URL":        "website",
    "Last Funding Type":   "funding_round",
    "Funding Round":       "funding_round",
    "Round":               "funding_round",
    "Last Funding Amount": "funding_amount",
    "Funding Amount":      "funding_amount",
    "Amount":              "funding_amount",
    "Last Funding Date":   "funding_date",
    "Funding Date":        "funding_date",
    "Date":                "funding_date",
    "Announced Date":      "funding_date",
}


def parse_company_csv(file_obj) -> tuple[list[dict], str]:
    if file_obj is None:
        return [], "No file uploaded."

    try:
        df = pd.read_csv(file_obj.name if hasattr(file_obj, "name") else file_obj)
    except Exception as e:
        return [], f"Could not read CSV: {e}"

    rename = {col: CRUNCHBASE_COL_MAP[col] for col in df.columns if col in CRUNCHBASE_COL_MAP}
    df = df.rename(columns=rename)

    if "company_name" not in df.columns:
        return [], (
            "Could not find a company name column. "
            "Expected one of: 'Organization Name', 'Company', 'Name'."
        )

    for col in ["website", "funding_round", "funding_amount", "funding_date"]:
        if col not in df.columns:
            df[col] = ""

    companies = df[["company_name", "website", "funding_round", "funding_amount", "funding_date"]].to_dict("records")
    companies = [c for c in companies if str(c.get("company_name", "")).strip()]

    return companies, ""


def parse_manual_companies(text: str) -> list[dict]:
    companies = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        companies.append({
            "company_name":   parts[0],
            "website":        parts[1] if len(parts) > 1 else "",
            "funding_round":  parts[2] if len(parts) > 2 else "",
            "funding_amount": "",
            "funding_date":   "",
        })
    return companies


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────────────────────

def format_contacts(contacts: list[dict]) -> str:
    if not contacts:
        return ""
    lines = []
    for c in contacts:
        name  = c.get("name") or "—"
        title = c.get("title", "")
        url   = c.get("linkedin_url", "")
        src   = "🔍" if c.get("source") == "linkedin_search" else "✅"
        lines.append(f"{src} {name} | {title} | {url}")
    return "\n".join(lines)


def build_listings_df(with_listings: list[dict]) -> pd.DataFrame:
    cols = ["Company", "Round", "Job Title", "Department", "Location",
            "Posted", "Match %", "Apply Link", "Contacts"]
    if not with_listings:
        return pd.DataFrame(columns=cols)

    rows = []
    for j in with_listings:
        rows.append({
            "Company":    j["company_name"],
            "Round":      j.get("funding_round", ""),
            "Job Title":  j["job_title"],
            "Department": j.get("department", ""),
            "Location":   j.get("location", ""),
            "Posted":     j.get("posted_at", ""),
            "Match %":    f"{int(j.get('match_score', 0) * 100)}%",
            "Apply Link": j.get("apply_url", ""),
            "Contacts":   format_contacts(j.get("contacts", [])),
        })
    return pd.DataFrame(rows)


def build_cold_df(without_listings: list[dict]) -> pd.DataFrame:
    cols = ["Company", "Round", "Funding Amount", "Funding Date",
            "Website", "ATS Detected", "Contacts"]
    if not without_listings:
        return pd.DataFrame(columns=cols)

    rows = []
    for c in without_listings:
        rows.append({
            "Company":         c["company_name"],
            "Round":           c.get("funding_round", ""),
            "Funding Amount":  c.get("funding_amount", ""),
            "Funding Date":    c.get("funding_date", ""),
            "Website":         c.get("website", ""),
            "ATS Detected":    c.get("ats", "unknown"),
            "Contacts":        format_contacts(c.get("contacts", [])),
        })
    return pd.DataFrame(rows)


def export_to_csv(df: pd.DataFrame, filename: str) -> str:
    path = f"/tmp/{filename}"
    df.to_csv(path, index=False)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Tool 1: Find Jobs (no contacts)
# ─────────────────────────────────────────────────────────────────────────────

def run_job_finder(
    csv_file,
    manual_companies_text: str,
    job_titles_input: str,
    anthropic_key: str,
    max_workers: int,
    progress=gr.Progress(track_tqdm=True),
):
    empty = (pd.DataFrame(), pd.DataFrame(), "[]", "", "", [], [], job_titles_input)

    if not job_titles_input.strip():
        return empty[:4] + ("❌ Please enter at least one job title.",) + empty[5:]

    raw_titles = [t.strip() for t in job_titles_input.replace("\n", ",").split(",")]
    job_titles = [t for t in raw_titles if t]

    companies = []
    if csv_file is not None:
        parsed, err = parse_company_csv(csv_file)
        if err:
            return empty[:4] + (f"❌ CSV error: {err}",) + empty[5:]
        companies = parsed

    if manual_companies_text.strip():
        companies += parse_manual_companies(manual_companies_text)

    if not companies:
        return empty[:4] + ("❌ No companies provided. Upload a CSV or enter companies manually.",) + empty[5:]

    anthropic_key_clean = anthropic_key.strip() or None

    def cb(pct, msg):
        progress(pct, desc=msg)

    result = find_jobs(
        companies=companies,
        job_titles=job_titles,
        anthropic_key=anthropic_key_clean,
        max_workers=int(max_workers),
        progress_callback=cb,
    )

    listings_df = build_listings_df(result["with_listings"])
    cold_df     = build_cold_df(result["without_listings"])
    keywords    = json.dumps(result["keywords"], indent=2)

    errors_text = ""
    if result["errors"]:
        errors_text = "⚠️ Some companies had errors:\n" + "\n".join(result["errors"])

    n_companies = len(set(j["company_name"] for j in result["with_listings"]))
    summary = (
        f"✅ **{len(result['with_listings'])} job matches** across {n_companies} companies.  "
        f"🎯 **{len(result['without_listings'])} cold outreach targets** (funded, no matching listing yet).  "
        f"_Contacts not fetched yet — use the buttons below to look them up on demand._"
    )

    # Raw records (without "contacts") kept in State for the contact-finder step
    return (
        listings_df, cold_df, keywords, summary, errors_text,
        result["with_listings"], result["without_listings"], job_titles_input,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tool 2: Find Contacts (on-demand, separate)
# ─────────────────────────────────────────────────────────────────────────────

def run_contact_finder_listings(listings_state, job_titles_input, apollo_key, max_workers, progress=gr.Progress()):
    if not listings_state:
        return pd.DataFrame(), "⚠️ Run Job Finder first — no job listings to enrich."

    job_title = (job_titles_input or "").split(",")[0].split("\n")[0].strip() or "Program Manager"
    apollo_key_clean = (apollo_key or "").strip() or None

    def cb(pct, msg):
        progress(pct, desc=msg)

    enriched = enrich_with_contacts(
        listings_state, job_title, apollo_key=apollo_key_clean,
        max_workers=int(max_workers), progress_callback=cb,
    )
    return build_listings_df(enriched), f"✅ Found contacts for {len(enriched)} job listing rows."


def run_contact_finder_cold(cold_state, job_titles_input, apollo_key, max_workers, progress=gr.Progress()):
    if not cold_state:
        return pd.DataFrame(), "⚠️ Run Job Finder first — no cold-outreach companies to enrich."

    job_title = (job_titles_input or "").split(",")[0].split("\n")[0].strip() or "Program Manager"
    apollo_key_clean = (apollo_key or "").strip() or None

    def cb(pct, msg):
        progress(pct, desc=msg)

    enriched = enrich_with_contacts(
        cold_state, job_title, apollo_key=apollo_key_clean,
        max_workers=int(max_workers), progress_callback=cb,
    )
    return build_cold_df(enriched), f"✅ Found contacts for {len(enriched)} cold-outreach companies."


# ─────────────────────────────────────────────────────────────────────────────
# Gradio UI
# ─────────────────────────────────────────────────────────────────────────────

DESCRIPTION = """
# 🎯 Job Hunt Agent
**Bypass job boards. Find roles directly from companies that just got funded.**

**Step 1 — Find Jobs.** Upload a CSV from Crunchbase (or enter companies manually),
give it a job title, and it will detect each company's ATS (Greenhouse / Lever / Ashby),
fall back to scraping their careers page when needed, expand your title into keyword
variants, and match jobs against them. No contact lookups happen at this step.

**Step 2 — Find Contacts (optional, separate).** Once you've seen the results, pick
either table below and click its own "Find Contacts" button to run Apollo lookups
for just those companies — report-to, HR/recruiter, and a peer contact per company.
This is deliberately a second, on-demand step: contact lookups are the slowest part
of the pipeline, so you only pay that cost for companies you actually care about.
"""

MANUAL_PLACEHOLDER = """Example (one per line):
NiCE Systems, https://www.nice.com, Series B
Anthropic
Mistral AI, https://mistral.ai
Cohere"""

CSV_INSTRUCTIONS = """**Accepted CSV formats:**
- Crunchbase Pro export (auto-detected columns)
- Custom CSV with columns: `company_name`, `website`, `funding_round`, `funding_amount`, `funding_date`
"""

with gr.Blocks(title="Job Hunt Agent") as demo:
    gr.Markdown(DESCRIPTION)

    # State: raw (contact-less) records from the last Job Finder run
    listings_state = gr.State([])
    cold_state      = gr.State([])

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("## ⚙️ Configuration")

            job_title_input = gr.Textbox(
                label="Job Titles",
                placeholder="AI Program Manager\nTechnical Program Manager\nSenior Project Manager\nAI Product Manager",
                lines=4,
                info="One title per line (or comma-separated). Also used as the persona for contact search.",
            )

            anthropic_key_input = gr.Textbox(
                label="Anthropic API Key (optional)",
                placeholder="sk-ant-...",
                value=os.environ.get("ANTHROPIC_API_KEY", ""),
                type="password",
                info="Powers keyword expansion via Claude Haiku. Falls back to rule-based if empty.",
            )

            apollo_key_input = gr.Textbox(
                label="Apollo.io API Key (optional override)",
                placeholder="Leave blank to use the embedded/default key",
                value="",
                type="password",
                info="Only needed if you want to override the embedded default key for this run.",
            )

            max_workers_input = gr.Slider(
                label="Concurrent companies",
                minimum=2, maximum=25, step=1, value=10,
                info="Higher = faster, but more aggressive against target sites/APIs. 8-12 is a safe default.",
            )

            gr.Markdown("---")
            gr.Markdown("## 🏢 Companies")

            csv_upload = gr.File(
                label="Upload Crunchbase / Company CSV",
                file_types=[".csv"],
            )
            gr.Markdown(CSV_INSTRUCTIONS)

            manual_input = gr.Textbox(
                label="Or enter companies manually",
                placeholder=MANUAL_PLACEHOLDER,
                lines=6,
                info="Format: Company Name, Website (optional), Round (optional)",
            )

            find_jobs_btn = gr.Button("🚀 1. Find Jobs", variant="primary", size="lg")

        with gr.Column(scale=2):
            gr.Markdown("## 📊 Results")

            summary_md = gr.Markdown("")
            errors_md  = gr.Markdown("")

            with gr.Tabs():
                with gr.Tab("✅ Job Listings"):
                    listings_table = gr.Dataframe(
                        label="Companies with Matching Listings",
                        wrap=True,
                        interactive=False,
                    )
                    find_contacts_listings_btn = gr.Button("📇 2. Find Contacts for These Listings")
                    listings_contact_status = gr.Markdown("")
                    export_listings_btn = gr.Button("📥 Export to CSV", visible=False)
                    export_listings_file = gr.File(label="Download", visible=False)

                with gr.Tab("🎯 Cold Outreach"):
                    cold_table = gr.Dataframe(
                        label="Funded Companies — No Listing Yet",
                        wrap=True,
                        interactive=False,
                    )
                    find_contacts_cold_btn = gr.Button("📇 2. Find Contacts for These Companies")
                    cold_contact_status = gr.Markdown("")
                    export_cold_btn = gr.Button("📥 Export to CSV", visible=False)
                    export_cold_file = gr.File(label="Download", visible=False)

                with gr.Tab("🔑 Keywords Used"):
                    keywords_json = gr.Code(
                        label="Expanded Keywords",
                        language="json",
                    )

    # ── Event wiring ──────────────────────────────────────────────────────────
    find_jobs_btn.click(
        fn=run_job_finder,
        inputs=[csv_upload, manual_input, job_title_input, anthropic_key_input, max_workers_input],
        outputs=[listings_table, cold_table, keywords_json, summary_md, errors_md,
                 listings_state, cold_state, job_title_input],
    ).then(
        lambda lt, ct: (gr.update(visible=len(lt) > 0), gr.update(visible=len(ct) > 0)),
        inputs=[listings_state, cold_state],
        outputs=[export_listings_btn, export_cold_btn],
    )

    find_contacts_listings_btn.click(
        fn=run_contact_finder_listings,
        inputs=[listings_state, job_title_input, apollo_key_input, max_workers_input],
        outputs=[listings_table, listings_contact_status],
    )

    find_contacts_cold_btn.click(
        fn=run_contact_finder_cold,
        inputs=[cold_state, job_title_input, apollo_key_input, max_workers_input],
        outputs=[cold_table, cold_contact_status],
    )

    export_listings_btn.click(
        fn=lambda df: export_to_csv(df, "job_listings.csv"),
        inputs=[listings_table],
        outputs=[export_listings_file],
    ).then(lambda: gr.update(visible=True), outputs=[export_listings_file])

    export_cold_btn.click(
        fn=lambda df: export_to_csv(df, "cold_outreach.csv"),
        inputs=[cold_table],
        outputs=[export_cold_file],
    ).then(lambda: gr.update(visible=True), outputs=[export_cold_file])


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
