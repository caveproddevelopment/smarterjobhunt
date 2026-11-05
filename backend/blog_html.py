"""Sanitizing the rich-text HTML that The JobBeggar Brief editor sends.

Only a small allowlist survives: paragraphs, headings, lists, quotes, links,
bold/italic/underline/strike, and <span style> with four CSS properties
(color, font-size, font-family, font-weight) whose values are checked one by
one. Scripts, event handlers, iframes, images, classes and any other CSS are
dropped. Runs on every save, so the stored HTML is always safe to render.
"""
import html as html_lib
import re

import nh3

ALLOWED_TAGS = {
    "p", "br", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote", "span", "hr",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "target"}, "span": {"style"}}
URL_SCHEMES = {"http", "https", "mailto"}
STYLE_PROPERTIES = {"color", "font-size", "font-family", "font-weight"}

_STYLE_VALUE_PATTERNS = {
    "color": re.compile(
        r"^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.]+%?\s*,\s*[\d.]+%?\s*,\s*[\d.]+%?\s*(,\s*[\d.]+\s*)?\)|[a-zA-Z]{3,20})$"
    ),
    "font-size": re.compile(r"^(\d{1,3}(\.\d{1,2})?)(px|rem|em|pt|%)$"),
    "font-family": re.compile(r"^[A-Za-z0-9 ,'\"\-]{1,120}$"),
    "font-weight": re.compile(r"^(normal|bold|lighter|bolder|[1-9]00)$"),
}
_FONT_SIZE_PX_LIMITS = {"px": (8, 96), "pt": (6, 72), "rem": (0.5, 6), "em": (0.5, 6), "%": (50, 600)}

MAX_HTML_CHARS = 200_000


def _clean_style(value):
    kept = []
    for decl in value.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop, val = prop.strip().lower(), val.strip()
        pattern = _STYLE_VALUE_PATTERNS.get(prop)
        if not pattern or not pattern.match(val):
            continue
        if prop == "font-size":
            m = pattern.match(val)
            low, high = _FONT_SIZE_PX_LIMITS[m.group(3)]
            if not low <= float(m.group(1)) <= high:
                continue
        kept.append(f"{prop}: {val}")
    return "; ".join(kept) or None


def _attribute_filter(tag, attr, value):
    if attr == "style":
        return _clean_style(value)
    if attr == "target":
        return "_blank" if value == "_blank" else None
    return value


def sanitize(raw_html):
    """Allowlisted, safe HTML (may be an empty string)."""
    cleaned = nh3.clean(
        str(raw_html or "")[:MAX_HTML_CHARS],
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=URL_SCHEMES,
        filter_style_properties=STYLE_PROPERTIES,
        link_rel="noopener noreferrer",
    )
    # drop spans left with no attributes and empty trailing paragraphs
    cleaned = re.sub(r"<span>(.*?)</span>", r"\1", cleaned, flags=re.S)
    cleaned = re.sub(r"(<p>\s*(<br\s*/?>)?\s*</p>\s*)+$", "", cleaned)
    return cleaned.strip()


_BLOCK_END = re.compile(r"</(p|h2|h3|li|blockquote)>|<br\s*/?>|<hr\s*/?>", re.I)


def to_text(safe_html):
    """Plain text version (paragraphs separated by blank lines) for excerpts,
    reading time and length checks."""
    text = _BLOCK_END.sub("\n\n", safe_html)
    text = html_lib.unescape(nh3.clean(text, tags=set()))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip()
