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
"""

from bs4 import BeautifulSoup

DESCRIPTION_SNIPPET_CHARS = 1000

_STRIP_TAGS = ["script", "style", "noscript", "svg", "header", "footer", "nav"]


def html_to_text(html: str) -> str:
    """Strip an HTML job-description body down to clean plain text.

    Decomposes non-content chrome tags first, then collapses whitespace.
    Returns "" for empty/None input rather than raising.
    """
    if not html:
        return ""
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
