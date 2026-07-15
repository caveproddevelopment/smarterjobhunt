"""
SJH.com Ingestion Agent — Hugging Face Space wrapper.

This is intentionally bare-bones: upload a company CSV, click Run, get
back a job-listings CSV and a per-company timing CSV. No title input,
no keyword matching, no contacts, no API keys required — this agent
only detects ATS and pulls whatever's currently posted.
"""

import os
import time
import tempfile

import gradio as gr
import pandas as pd

from agent.company_source import CSVCompanySource
from agent.job_sink import CSVJobSink
from agent.ingestion_orchestrator import run as run_ingestion

OUTPUT_DIR = tempfile.mkdtemp(prefix="sjh_ingestion_")


def run_agent(company_csv, max_workers, limit, progress=gr.Progress()):
    if company_csv is None:
        return None, None, "⚠️ Upload a company CSV first.", pd.DataFrame()

    limit_val = int(limit) if limit and int(limit) > 0 else None
    source = CSVCompanySource(company_csv.name, limit=limit_val)
    jobs_path = os.path.join(OUTPUT_DIR, "jobs.csv")
    sink = CSVJobSink(jobs_path)

    def cb(pct, msg):
        progress(pct, desc=msg)

    start = time.time()
    summary = run_ingestion(source, sink, max_workers=int(max_workers), progress_callback=cb)
    elapsed = time.time() - start

    # Write the timing log alongside the jobs CSV
    timing_path = os.path.join(OUTPUT_DIR, "jobs.timing.csv")
    pd.DataFrame(summary["per_company_timing"]).to_csv(timing_path, index=False)

    status = (
        f"✅ Done in {elapsed:.1f}s — "
        f"{summary['companies_total']} companies "
        f"({summary['companies_ats_hit']} via ATS API, "
        f"{summary['companies_scraped']} via career-page scrape, "
        f"{summary['companies_failed']} failed/unknown) — "
        f"{summary['jobs_found']} jobs found."
    )
    if summary["errors"]:
        status += f"\n\n⚠️ {len(summary['errors'])} errors (see logs for detail)."

    preview_df = pd.read_csv(jobs_path) if summary["jobs_found"] else pd.DataFrame()

    return jobs_path, timing_path, status, preview_df


with gr.Blocks(title="SJH.com Ingestion Agent (Proof of Concept)") as demo:
    gr.Markdown("# SJH.com Ingestion Agent — Proof of Concept")
    gr.Markdown(
        "Upload a company CSV (`Organization Name, Homepage URL, Last Funding Type, "
        "Last Funding Amount, Last Funding Date`). This agent detects each company's "
        "ATS, pulls every job currently posted (via public API or a career-page scrape "
        "fallback), and returns a job-listings CSV plus a per-company timing log. "
        "No title input, no matching, no contacts — that happens later, at search time."
    )

    with gr.Row():
        with gr.Column(scale=1):
            company_csv_input = gr.File(label="Company CSV", file_types=[".csv"])
            max_workers_input = gr.Slider(
                label="Concurrent companies", minimum=2, maximum=25, step=1, value=10,
                info="Higher = faster, but more aggressive against target sites.",
            )
            limit_input = gr.Number(
                label="Limit (optional)", value=None, precision=0,
                info="Only process the first N companies — useful for a quick smoke test before a full run.",
            )
            run_btn = gr.Button("🚀 Run Ingestion", variant="primary", size="lg")

        with gr.Column(scale=2):
            status_md = gr.Markdown("")
            jobs_file = gr.File(label="Job Listings CSV")
            timing_file = gr.File(label="Per-Company Timing CSV")
            preview_table = gr.Dataframe(label="Preview (first rows)", wrap=True, interactive=False)

    run_btn.click(
        fn=run_agent,
        inputs=[company_csv_input, max_workers_input, limit_input],
        outputs=[jobs_file, timing_file, status_md, preview_table],
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)
