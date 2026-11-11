"""
Dry run of the Phenom handler against live career sites. Writes nothing
to the database: it only calls the sites and prints what the nightly
scrape would get.

  python tools/phenom_dry_run.py https://careers.adobe.com https://jobs.chewy.com
  python tools/phenom_dry_run.py --full https://jobs.advanceautoparts.com
  python tools/phenom_dry_run.py --page-size 500 --full https://jobs.advanceautoparts.com

Each URL can be any page of the site, or a company page that redirects to
it (www.acadiahealthcare.com/about/careers/ -> www.acadiacareers.com).

Default: the nightly limits (MAX_JOBS_PER_COMPANY jobs, LIST_BUDGET_SECONDS).
--full:   no job cap and no time budget, so boards past 9,999 jobs are
          split by state/country to get every job (Advance Auto ~16,300).

Per site it prints: the token, the total the site reports, jobs fetched,
time and requests, how many descriptions are 100+ characters, empty
titles/locations, duplicate links, sample jobs with their links (open a
few to check they go to the right job), and the full description of the
first two samples from the job-detail call.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests  # noqa: E402

from agent import ats_api  # noqa: E402
from agent.platforms import parse_phenom_config, phenom_token  # noqa: E402

PAGE_HEADERS = {**ats_api.HEADERS, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}


def find_site(url: str):
    """(config, token, final_url) for the Phenom site behind `url`."""
    if not url.startswith("http"):
        url = "https://" + url
    tried = [url]
    r = requests.get(url, headers=PAGE_HEADERS, timeout=20, allow_redirects=True)
    cfg = parse_phenom_config(r.text) if r.status_code == 200 else None
    if not cfg:
        # The page itself isn't Phenom; try the common search page paths.
        root = r.url.split("/", 3)[:3]
        for path in ("/us/en/search-results", "/global/en/search-results", "/search-results"):
            u = "/".join(root) + path
            tried.append(u)
            try:
                r2 = requests.get(u, headers=PAGE_HEADERS, timeout=20, allow_redirects=True)
            except requests.RequestException:
                continue
            if r2.status_code == 200:
                cfg = parse_phenom_config(r2.text)
                if cfg:
                    r = r2
                    break
    if not cfg:
        raise RuntimeError(f"no Phenom config (phApp) found; HTTP {r.status_code} at {r.url}; "
                           f"tried {', '.join(tried)}")
    return cfg, phenom_token(cfg), r.url


def reported_total(cfg: dict) -> int:
    rs = ats_api._phenom_search(cfg, 0, 1)
    return rs.get("totalHits") or 0


def run_one(url: str, full: bool, page_size: int, samples: int) -> str:
    print("=" * 100)
    print(f"SITE  {url}")
    try:
        cfg, token, final = find_site(url)
    except Exception as e:
        print(f"RESULT  FAILS: {type(e).__name__}: {e}")
        return f"{url}: fails ({type(e).__name__}: {str(e)[:120]})"
    print(f"  page      {final}")
    print(f"  token     phenom / {token}")
    print(f"  api       {cfg['widgetApiEndpoint']}  locale={cfg['locale']} country={cfg['country']} "
          f"siteType={cfg.get('siteType')}")

    try:
        total = reported_total(cfg)
    except Exception as e:
        print(f"RESULT  FAILS: search call: {type(e).__name__}: {e}")
        return f"{url}: fails (search call: {type(e).__name__}: {str(e)[:120]})"

    calls = {"n": 0}
    real_post = ats_api.requests.post

    def counting_post(*a, **kw):
        calls["n"] += 1
        return real_post(*a, **kw)

    diag: dict = {}
    ats_api.requests.post = counting_post
    old_budget = ats_api.LIST_BUDGET_SECONDS
    t0 = time.monotonic()
    try:
        if full:
            ats_api.LIST_BUDGET_SECONDS = 3600
            ats_api._CALL.deadline = time.monotonic() + 3600
            ats_api._CALL.diag = diag
            jobs = ats_api._fetch_phenom(token, True, False, cap=10 ** 6, page_size=page_size)
        else:
            old_size = ats_api.PHENOM_PAGE_SIZE
            ats_api.PHENOM_PAGE_SIZE = page_size
            try:
                jobs = ats_api.fetch_jobs("phenom", token, diag=diag)
            finally:
                ats_api.PHENOM_PAGE_SIZE = old_size
    finally:
        ats_api.requests.post = real_post
        ats_api.LIST_BUDGET_SECONDS = old_budget
        ats_api._CALL.deadline = None
        ats_api._CALL.diag = None
    secs = time.monotonic() - t0

    n = len(jobs)
    desc_ok = sum(1 for j in jobs if len(j["description_snippet"]) >= 100)
    no_title = sum(1 for j in jobs if not j["title"])
    no_loc = sum(1 for j in jobs if not j["location"])
    dup_links = n - len({j["apply_url"] for j in jobs})
    expected = total if full else min(total, ats_api.MAX_JOBS_PER_COMPANY)

    print(f"  reported  {total} jobs on the site")
    print(f"  fetched   {n} jobs in {secs:.1f}s, {calls['n']} widget calls, page size {page_size}"
          + ("  (--full: no cap)" if full else f"  (nightly cap {ats_api.MAX_JOBS_PER_COMPANY})"))
    if diag:
        print(f"  diag      {diag}")
    print(f"  checks    descriptions 100+ chars: {desc_ok}/{n}   empty titles: {no_title}   "
          f"empty locations: {no_loc}   duplicate links: {dup_links}")
    print("  samples (open 3 or 4 of these links):")
    for j in jobs[:samples]:
        print(f"    - {j['title']}  |  {j['location'] or '(no location)'}  |  {j['posted_at'] or '-'}"
              f"  |  {j['department'] or '-'}")
        print(f"      {j['apply_url']}")
        print(f"      desc {len(j['description_snippet'])} chars: {j['description_snippet'][:110]!r}")

    detail_note = ""
    for j in jobs[:2]:
        job_id = j["apply_url"].split("/job/")[-1].split("/")[0] if "/job/" in j["apply_url"] else ""
        if not job_id:
            continue
        try:
            text = ats_api.detail_phenom(cfg, requests.utils.unquote(job_id))
            print(f"  detail    {job_id}: {len(text)} chars: {text[:110]!r}")
        except Exception as e:
            detail_note = f"; detail call failed: {type(e).__name__}"
            print(f"  detail    {job_id}: FAILED {type(e).__name__}: {e}")

    problems = []
    if n == 0:
        problems.append("0 jobs")
    elif n < expected * 0.98:
        problems.append(f"got {n} of {expected} expected")
    if n and desc_ok < n * 0.95:
        problems.append(f"only {desc_ok}/{n} descriptions 100+ chars")
    if no_title:
        problems.append(f"{no_title} empty titles")
    if n and no_loc > n * 0.2:
        problems.append(f"{no_loc}/{n} empty locations")
    if dup_links:
        problems.append(f"{dup_links} duplicate links")
    if n == 0:
        verdict = "fails (" + "; ".join(problems) + ")"
    elif problems:
        verdict = "partly works (" + "; ".join(problems) + detail_note + ")"
    else:
        verdict = f"works ({n}/{total} jobs, {secs:.0f}s{detail_note})"
    print(f"RESULT  {verdict}")
    return f"{url}: {verdict}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--full", action="store_true", help="no job cap or time budget")
    ap.add_argument("--page-size", type=int, default=ats_api.PHENOM_PAGE_SIZE,
                    help=f"jobs per widget call (default {ats_api.PHENOM_PAGE_SIZE}, API max 500)")
    ap.add_argument("--samples", type=int, default=5)
    args = ap.parse_args()

    lines = [run_one(u, args.full, args.page_size, args.samples) for u in args.urls]
    print("=" * 100)
    print("SUMMARY")
    for line in lines:
        print("  " + line)


if __name__ == "__main__":
    main()
