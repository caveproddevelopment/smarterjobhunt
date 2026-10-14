#!/usr/bin/env python3
"""
Builds db/fixes/2026-10-13_india_findings.sql from the 7 Oct findings file
(data/indian_companies_zero_jobs_findings_2026-10-07.csv).

What it writes, per company (matched on companies.name, exact):
  - listing_status = 'no_online_listings' for "No careers page on the company
    site", "Careers page has no job listings", and LinkedIn-only companies
  - listing_status = 'pdf_notices' for "Jobs published as PDF notices"
  - listing_status = 'needs_review' for parked/hijacked domains and stored URLs
    that point at the wrong site with no obvious replacement
  - website = <new> for moved sites with a clear new domain (CURATED below)
  - careers_url = <url> where the findings name the exact careers page or
    hiring-platform board (CURATED below, hand-picked from the
    "What the site check showed" column)
DNS/SSL failures are left 'active' on purpose: the next run re-checks them and
now reports them as website_unreachable / website_ssl_error.

Re-run:  python tools/build_india_db_fixes.py
"""

import csv
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FINDINGS = os.path.join(HERE, "..", "data", "indian_companies_zero_jobs_findings_2026-10-07.csv")
OUT = os.path.join(HERE, "..", "db", "fixes", "2026-10-13_india_findings.sql")

DBX = "/ms/candidate/careers"   # Darwinbox candidate portal path (seen in the findings for several tenants)

# Website moved — clear new domain from the findings.
WEBSITE_FIXES = {
    "Bank of Maharashtra":        "https://bankofmaharashtra.bank.in",
    "Canara Bank":                "https://canarabank.bank.in",
    "Central Bank of India":      "https://centralbank.bank.in",
    "FINO Payments Bank":         "https://www.fino.bank.in",
    "Indian Overseas Bank":       "https://iob.bank.in",
    "Jammu & Kashmir Bank Ltd":   "https://jkb.bank.in",
    "Karur Vysya Bank Ltd":       "https://kvb.bank.in",
    "Paymate":                    "https://paymate.in",
    "Union Bank of India":        "https://www.unionbankofindia.bank.in",
    "Fieldproxy":                 "https://fieldproxy.ai",
    "Pensil":                     "https://pensil.so",
    "Whirlpool of India Ltd":     "https://india.whirlpool.in",
    "Cohance Lifesciences Ltd":   "https://www.cohance.com",
}

# Moved banks whose new careers pages only carry PDF recruitment notices.
MOVED_PDF_BANKS = {"Bank of Maharashtra", "Canara Bank", "Central Bank of India",
                   "Indian Overseas Bank", "Jammu & Kashmir Bank Ltd"}

# Stored URL wrong, no safe automatic replacement.
NEEDS_REVIEW_EXTRA = {
    "Absolute Foods":               "absolutefoods.com redirects to absolute.ag 404 page",
    "Finova Capital":               "finovacapital.com redirects to an unrelated US company",
    "Pragmatic Leaders (Ankai Inc)": "stored URL is a conference listing page",
    "United Spirits Ltd":           "stored URL is a distributor page (United Spirits = Diageo India; check diageoindia.com)",
    "ABB India Ltd":                "new.abb.com/india 404; only the global ABB careers site found",
    "Freshdesk":                    "Freshdesk is a Freshworks product; jobs are on the Freshworks board (duplicate)",
}

LINKEDIN_ONLY = {"Hindustan Zinc Ltd", "Novatr", "Nuvama Wealth Management Ltd", "Vedantu", "Zaggle"}

# Exact careers page / hiring-platform board, hand-picked from the findings.
CAREERS_URLS = {
    # careers page the scraper never found
    "360 ONE WAM Ltd":                     "https://360.one/wealth/careers",
    "Aditya Birla Real Estate Ltd":        "https://www.adityabirlarealestate.com/career",
    "Aequs":                               "https://www.aequs.com/careers/",
    "Anupam Rasayan India Ltd":            "https://www.anupamrasayan.com/career",
    "BookMyShow":                          "https://in.bookmyshow.com/careers/",
    "Choice International Ltd":            "https://www.choiceindia.com/career",
    "Cohance Lifesciences Ltd":            "https://www.cohance.com/careers/",
    "Force Motors Ltd":                    "https://www.forcemotors.com/people/",
    "India Cements Ltd":                   "https://www.indiacements.co.in/join-our-family.html",
    "Indiqube":                            "https://indiqube.com/career/",
    "ITC Hotels Ltd":                      "https://www.itchotels.com/in/en/careers",
    "Mahanagar Gas Ltd":                   "https://www.mahanagargas.com/MGL-corporate/career/current-opportunities",
    "Multi Commodity Exchange of India Ltd": "https://www.mcxindia.com/careers",
    "NHPC Ltd":                            "https://www.nhpcindia.com/welcome/job",
    "PNB Housing Finance Ltd":             "https://www.pnbhousing.com/about-us/employee/careers",
    "Railtel Corporation Of India Ltd":    "https://www.railtel.in/career.html",
    "Redcliffe Lifetech":                  "https://redcliffelabs.com/career",
    "Sapphire Foods India Ltd":            "https://www.sapphirefoods.in/careers",
    "SBI Cards and Payment Services Ltd":  "https://www.sbicard.com/en/who-we-are/careers.page",
    "SJVN Ltd":                            "https://sjvn.nic.in/hi/current-job",
    # hiring platforms / separate careers sites
    "Adani Power Ltd":                     "https://careers.adani.com",
    "Aditya Birla Fashion and Retail Ltd": "https://abfrlcareers.peoplestrong.com/home",
    "Aditya Birla Lifestyle Brands Ltd":   "https://abfrlcareers.peoplestrong.com/home",
    "AgroStar":                            "https://agrostar.darwinbox.in" + DBX,
    "Apollo Hospitals Enterprise Ltd":     "https://careers-myhr-apollo.peoplestrong.com/job/joblist",
    "Ashok Leyland Ltd":                   "https://ashokleyland.darwinbox.in" + DBX,
    "Aurobindo Pharma Ltd":                "https://aurobindo.talentrecruit.com/Search/",
    "Awfis":                               "https://awfis.keka.com/careers",
    "AWL Agri Business Ltd":               "https://awl.darwinbox.in/ms/candidatev2/main/careers/home",
    "Bata India Ltd":                      "https://bata.sensehq.com/careers",
    "Berger Paints India Ltd":             "https://iabiiz.fa.ocs.oraclecloud.com",
    "Billionbrains Garage Ventures Ltd":   "https://job-boards.eu.greenhouse.io/groww",
    "Birlasoft Ltd":                       "https://jobs.birlasoft.com",
    "Blue Star Ltd":                       "https://bluestar.workline.hr/Cportal/GeneralOpening.aspx",
    "Bolna AI":                            "https://jobs.ashbyhq.com/bolna",
    "Brigade Enterprises Ltd":             "https://brigadegroup.darwinbox.in" + DBX,
    "Brightchamps":                        "https://careers.brightchamps.com/jobs/Careers",
    "BrowserStack":                        "https://browserstack.wd3.myworkdayjobs.com/External",
    "C.E. Info Systems Ltd":               "https://about.mappls.com/careers",
    "Capillary Tech":                      "https://capillarytech.sensehq.com/careers",
    "Captain Fresh":                       "https://captainfresh.zohorecruit.com/jobs/Careers",
    "Cashfree":                            "https://careers.kula.ai/cashfree",
    "CCL Products (I) Ltd":                "https://ccl.akriviahcm.com/careers-page",
    "Ceat Ltd":                            "https://ceat.turbohire.co/careerpage",
    "Cipla Ltd":                           "https://careers.cipla.com",
    "Codingal":                            "https://app.dover.com/jobs/codingal",
    "Credgenics":                          "https://recruitcareers.zappyhire.com/en/credgenics",
    "Cyient Ltd":                          "https://careers.cyient.com/cyient",
    "Darwinbox":                           "https://dbx.darwinbox.in" + DBX,
    "Digit Insurance":                     "https://godigit.darwinbox.in" + DBX,
    "eClerx Services Ltd":                 "https://eclerx.com/careers/",
    "ElasticRun":                          "https://elasticruncareers.peoplestrong.com/job/joblist",
    "Elgi Equipments Ltd":                 "https://elgi.darwinbox.in" + DBX,
    "FarEye":                              "https://fareye.darwinbox.in" + DBX,
    "Fortis Healthcare Ltd":               "https://fa-ermg-saasfaprod1.fa.ocs.oraclecloud.com",
    "Fractal Analytics":                   "https://fractal.wd1.myworkdayjobs.com/Careers",
    "Freshworks":                          "https://careers.smartrecruiters.com/Freshworks",
    "Games24x7":                           "https://games24x7.darwinbox.in" + DBX,
    "Glenmark Pharmaceuticals Ltd":        "https://career.glenmarkpharma.com",
    "GMR Airports Ltd":                    "https://careers.gmrgroup.in",
    "Godfrey Phillips India Ltd":          "https://gpi-iacriz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1",
    "Godrej Consumer Products Ltd":        "https://careers.godrejindustries.com/in/en/godrej-consumer",
    "Godrej Properties Ltd":               "https://careers.godrejindustries.com/in/en/godrejproperties",
    "gokwik":                              "https://gokwik.keka.com/careers",
    "GreyOrange":                          "https://careers.greyorange.com/greyorange",
    "Havells India Ltd":                   "https://iabgcp.fa.ocs.oraclecloud.com",
    "HCL Technologies Ltd":                "https://careers.hcltech.com",
    "HealthifyMe":                         "https://healthify.darwinbox.in" + DBX,
    "Hero MotoCorp Ltd":                   "https://jobs.heromotocorp.com",
    "Hexaware Technologies Ltd":           "https://jobs.hexaware.com",
    "HFCL Ltd":                            "https://hifi.darwinbox.in" + DBX,
    "Hindustan Unilever Ltd":              "https://careers.unilever.com/india",
    "Homelane":                            "https://homelane.darwinbox.in" + DBX,
    "Hyundai Motor India Ltd":             "https://careers.hyundai.co.in",
    "Icertis":                             "https://iaaviz.fa.ocs.oraclecloud.com",
    "ICICI Bank Ltd":                      "https://www.icicicareers.com/CareerApplicant/Career/Home",
    "ICICI Prudential Life Insurance Company Ltd": "https://ismarthire.icicilife.com/Career/",
    "IDFC First Bank Ltd":                 "https://careers.idfcfirst.bank.in/in/en/home",
    "IIFL Finance Ltd":                    "https://iifl.darwinbox.in" + DBX,
    "Indegene Ltd":                        "https://careers.indegene.com",
    "Info Edge (India) Ltd":               "https://careers.infoedge.com/infoedge",
    "Innoviti":                            "https://myinnoviti.darwinbox.in/ms/candidate/careers",
    "Insurancedekho":                      "https://insurancedekho.darwinbox.in" + DBX,
    "InterGlobe Aviation Ltd":             "https://www.goindigo.in/careers.html",
    "Inventurus Knowledge Solutions Ltd":  "https://eiyi.fa.ap1.oraclecloud.com",
    "Jupiter":                             "https://jupiter.keka.com/careers",
    "KEI Industries Ltd":                  "https://keihrms.myadrenalin.com/CandidateMAX",
    "Landeed":                             "https://www.ycombinator.com/companies/landeed/jobs",
    "Leap":                                "https://careers.leapfinance.com",
    "Livspace":                            "https://careers.livspace.com/livspace",
    "LTM Ltd":                             "https://careers.ltm.com/search",
    "Lupin Ltd":                           "https://careers.lupin.com",
    "Maruti Suzuki India Ltd":             "https://maruti.app.param.ai/jobs/",
    "Mintifi":                             "https://www.mintifi.com/careers",
    "Moglix":                              "https://moglix.flexiele.com/careers/moglix/jobs",
    "Mosaic Wellness":                     "https://mosaicwellness.keka.com/careers",
    "Mygate":                              "https://mygate.darwinbox.in" + DBX,
    "Nestle India Ltd":                    "https://www.nestle.in/jobs",
    "Ninjacart":                           "https://ninjacart.darwinbox.in" + DBX,
    "Niva Bupa Health Insurance Company Ltd": "https://disha.darwinbox.in/ms/candidatev2/main/careers/home",
    "Niyo":                                "https://niyo.keka.com/careers",
    "Nuvoco Vistas Corporation Ltd":       "https://careers.nuvoco.com",
    "Open":                                "https://openfinancial.keka.com/careers/",
    "Phoenix Mills Ltd":                   "https://egeg.fa.em3.oraclecloud.com",
    "Physicswallah":                       "https://pwhr.darwinbox.in/ms/candidatev2/a62d7a6e288992/careers/home",
    "Piramal Finance Ltd":                 "https://piramalgroup.darwinbox.in" + DBX,
    "Polycab India Ltd":                   "https://polycab.darwinbox.in" + DBX,
    "Practo":                              "https://practo.app.param.ai/jobs/",
    "Pristyn Care":                        "https://pristyncare.skillate.com",
    "Rapido":                              "https://rapido.darwinbox.in" + DBX,
    "RENEE Cosmetics":                     "https://reneecosmetics.keka.com/careers",
    "Sai Life Sciences Ltd":               "https://sailifesciences.darwinbox.in" + DBX,
    "SalaryBox":                           "https://salarybox.zohorecruit.in/jobs/Careers",
    "SRF Ltd":                             "https://career.srf.com/Joblisting",
    "Steel Authority of India Ltd":        "https://sailcareers.com",
    "Sundaram Finance Ltd":                "https://sfempower.darwinbox.com" + DBX,
    "Supreme Industries Ltd":              "https://mysupreme.darwinbox.in" + DBX,
    "Syngene International Ltd":           "https://careers.syngeneintl.com",
    "Tega Industries Ltd":                 "https://tegaindustries.darwinbox.in" + DBX,
    "Tejas Networks Ltd":                  "https://iablcp.fa.ocs.oraclecloud.com",
    "Thermax Ltd":                         "https://thermaxglobal.darwinbox.in" + DBX,
    "Trident Ltd":                         "https://careers.tridentindia.com",
    "Turtlemint":                          "https://careers.turtlemint.com",
    "TVS Motor Company Ltd":               "https://tvsmsampark.darwinbox.in" + DBX,
    "UltraTech Cement Ltd":                "https://abgcareers.peoplestrong.com/job/joblist",
    "Ultraviolette Automotive":            "https://ultraviolette.zohorecruit.in/jobs/Careers",
    "Uniphore":                            "https://uniphore.wd503.myworkdayjobs.com/Uniphore",
    "UNO Minda Ltd":                       "https://inspire-unominda.darwinbox.in" + DBX,
    "Varun Beverages Ltd":                 "https://rjcorphcm-iacbiz.fa.ocs.oraclecloud.com",
    "Vedanta Ltd":                         "https://vhr.darwinbox.in/ms/candidate/careers",
    "Vijaya Diagnostic Centre Ltd":        "https://vmitr.myadrenalin.com/CandidateMAX",
    "Waaree Energies Ltd":                 "https://career.waaree.com",
    "Wakefit":                             "https://wakefit.darwinbox.in" + DBX,
    "WeWork India":                        "https://careers.kula.ai/weworkindia",
    "Yulu":                                "https://careers.yulu.bike",
    "Zetwerk":                             "https://zetwerk.sensehq.com/careers",
    "Zoho":                                "https://careers.zohocorp.com/jobs/Careers",
    # real job links that the old filter rejected / wrong page accepted
    "Gullak Money":                        "https://candid.hub.gullak.money/jobs/",
    "Lambdatest":                          "https://www.testmuai.com/career/",
    "m1xchange":                           "https://www.m1xchange.com/jobs/",
    "Olectra Greentech Ltd":               "https://www.olectra.com/career",
    "Shiprocket":                          "https://careers.shiprocket.in/",
    "OneAssist":                           "https://careers.oneassist.in",
    # moved sites with a known careers page
    "Karur Vysya Bank Ltd":                "https://careers.karurvysya.bank.in",
    "Medgenome":                           "https://diagnostics.medgenome.com/career/",
    "Paymate":                             "https://paymate.in/careers.html",
}


def q(s: str) -> str:
    return "'" + (s or "").replace("'", "''") + "'"


def main():
    rows = list(csv.DictReader(open(FINDINGS, encoding="utf-8-sig")))
    names = {r["Company"] for r in rows}
    unknown = [n for n in list(WEBSITE_FIXES) + list(CAREERS_URLS) + list(NEEDS_REVIEW_EXTRA) + list(LINKEDIN_ONLY)
               if n not in names]
    if unknown:
        raise SystemExit(f"Names not in findings file: {unknown}")

    status: dict[str, tuple[str, str]] = {}
    for r in rows:
        name, group, finding = r["Company"], r["Finding group"], r["Finding"]
        shown = r["What the site check showed"]
        if group in ("No careers page on the company site", "Careers page has no job listings"):
            status[name] = ("no_online_listings", f"{finding}: {shown}"[:300])
        elif group == "Jobs published as PDF notices":
            status[name] = ("pdf_notices", shown[:300])
        elif finding.startswith("Domain parked"):
            status[name] = ("needs_review", f"parked/hijacked: {shown}"[:300])
    for n in LINKEDIN_ONLY:
        status[n] = ("no_online_listings", "jobs only on LinkedIn")
    status["Square Yards"] = ("no_online_listings", "squareyards.com/career has no job links")
    for n, note in NEEDS_REVIEW_EXTRA.items():
        status[n] = ("needs_review", note)
    for n in MOVED_PDF_BANKS:
        status[n] = ("pdf_notices", "moved to .bank.in; recruitment is PDF notices")

    out = [
        "-- Generated by tools/build_india_db_fixes.py on " + date.today().isoformat(),
        "-- Source: data/indian_companies_zero_jobs_findings_2026-10-07.csv (7 Oct run, 655 companies)",
        "-- Requires db/migrations/2026-10-13_listing_status.sql first.",
        "-- Wrapped in one transaction; each UPDATE matches companies.name exactly.",
        "-- Review the careers_url block before running: the Darwinbox ones use the",
        "-- standard candidate-portal path " + DBX + " and are not individually verified.",
        "",
        "BEGIN;",
        "",
        "-- 1. Moved websites",
    ]
    for n, url in sorted(WEBSITE_FIXES.items()):
        out.append(f"UPDATE companies SET website = {q(url)} WHERE name = {q(n)};")
    out += ["", "-- 2. Careers page / hiring-platform overrides (tried first by the agent)"]
    for n, url in sorted(CAREERS_URLS.items()):
        out.append(f"UPDATE companies SET careers_url = {q(url)} WHERE name = {q(n)};")
    out += ["", "-- 3. Listing status (skipped by default; see --listing-status)"]
    counts: dict[str, int] = {}
    for n, (st, note) in sorted(status.items()):
        counts[st] = counts.get(st, 0) + 1
        out.append(f"UPDATE companies SET listing_status = {q(st)}, listing_status_note = {q(note)}, "
                   f"listing_status_updated_at = now() WHERE name = {q(n)};")
    out += ["", "COMMIT;", "",
            "-- Counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            + f", website fixes={len(WEBSITE_FIXES)}, careers_url overrides={len(CAREERS_URLS)}",
            "-- Check afterwards:",
            "--   SELECT listing_status, COUNT(*) FROM companies WHERE company_type = 'indianmajor' GROUP BY 1;",
            "--   SELECT COUNT(*) FROM companies WHERE careers_url IS NOT NULL;", ""]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"Wrote {OUT}: {counts}, website fixes={len(WEBSITE_FIXES)}, overrides={len(CAREERS_URLS)}")


if __name__ == "__main__":
    main()
