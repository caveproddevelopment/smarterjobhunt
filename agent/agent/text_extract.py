"""
Text Extract — shared HTML-to-plain-text cleanup and snippet truncation,
used wherever a raw job description (HTML or already-plain) needs to
become a short, storable, searchable snippet.

This is the productionized version of the BeautifulSoup approach that
was previously "analysis-side, not yet productionized" (see
claude/monte_turner_consolidated_knowledge.md Part 6 / Part 9): decompose
script/style/noscript/svg/header/footer/nav tags, then get_text. That
techique reliably strips boilerplate chrome from well-structured pages;
arbitrary career pages with non-semantic markup still need heuristic
handling and won't always clean up perfectly.

DESCRIPTION_SNIPPET_CHARS is a module-level constant (not buried inline)
specifically so the truncation length is a one-line change, not a
find-and-replace across three files, if the length needs revisiting
later — see the evaluation note in the project doc about why a naive
first-N-characters truncation is worth reconsidering.

Hang fix (2026-09-02, run stuck at ~94%/990-1000 every time): every
network call anywhere in the agent (ats_detector.py, ats_api.py,
career_scraper.py) has an explicit timeout, and career_scraper.py
additionally enforces a per-company HARD_TIMEOUT_SECONDS deadline. This
module was the one exception — `BeautifulSoup(html, "html.parser")` is
pure CPU work, not I/O, so none of those timeouts touch it once parsing
starts. Python's built-in html.parser can go quadratic (effectively hang
a thread) on certain large or malformed markup. Because companies load
in a fixed `ORDER BY name` order (see company_source.py), one company's
pathological description HTML landed in the same ~10 still-in-flight
slots every run, one per worker thread, and the run never came back —
no exception, no log line, just a permanently stuck thread blocking
ThreadPoolExecutor's shutdown.

Fix: cap how much raw HTML ever reaches the parser via
MAX_HTML_CHARS_TO_PARSE. We only ever keep the first
DESCRIPTION_SNIPPET_CHARS (1000) characters of *cleaned* text, so there
is no reason to let BeautifulSoup walk an arbitrarily large or
adversarial document to produce it — truncating the raw input bounds
worst-case parse time to a small, predictable range regardless of how
big or malformed the source HTML is. This is a size cap, not a time
cap, but it removes the actual unbounded-input condition that let parse
time run away in the first place.
"""

from bs4 import BeautifulSoup

DESCRIPTION_SNIPPET_CHARS = 1000

# How much raw HTML we'll hand to BeautifulSoup before truncating. Generous
# relative to the 1000-char output we actually keep — real job descriptions
# are almost always well under this — but firm enough to bound parse time
# even on a pathological multi-MB document. Tune down further if a future
# incident shows even this is too slow for html.parser on some input.
MAX_HTML_CHARS_TO_PARSE = 50_000

_STRIP_TAGS = ["script", "style", "noscript", "svg", "header", "footer", "nav"]


def html_to_text(html: str) -> str:
    """Strip an HTML job-description body down to clean plain text.

    Truncates the raw input to MAX_HTML_CHARS_TO_PARSE first (see module
    docstring — this is what keeps parsing from hanging on pathological
    input), decomposes non-content chrome tags, then collapses whitespace.
    Returns "" for empty/None input rather than raising.
    """
    if not html:
        return ""
    if len(html) > MAX_HTML_CHARS_TO_PARSE:
        html = html[:MAX_HTML_CHARS_TO_PARSE]
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag_name in _STRIP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()
        text = soup.get_text(separator=" ")
        return _collapse_whitespace(text)
    except Exception:
        return ""


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def make_snippet(text_or_html: str, is_html: bool = True, max_chars: int = DESCRIPTION_SNIPPET_CHARS) -> str:
    """Clean (if HTML) and truncate to the first `max_chars` characters.

    This is a straight prefix truncation, matching what was asked for.
    See the project doc's evaluation section for why a prefix-only
    truncation risks capturing boilerplate ("About Us", EEO statements)
    instead of the requirements/technology section a keyword search is
    actually trying to match against — worth reading before relying on
    this for recall-sensitive searches like "SAP S4HANA".
    """
    text = html_to_text(text_or_html) if is_html else _collapse_whitespace(text_or_html or "")
    return text[:max_chars]