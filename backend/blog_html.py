"""Sanitizing the rich-text HTML that The JobBeggar Brief editor sends.

Only a small allowlist survives: paragraphs, headings, lists, quotes, links,
bold/italic/underline/strike, <span style> with four CSS properties
(color, font-size, font-family, font-weight) whose values are checked one by
one, and <img> pointing at an image uploaded to The Brief (/api/blog/images/<id>).
Image sources are stored as that relative path whatever host the editor used.
Scripts, event handlers, iframes, other images, classes and any other CSS are
dropped. Runs on every save, so the stored HTML is always safe to render.
"""
import html as html_lib
import re

import nh3

ALLOWED_TAGS = {
    "p", "br", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "a", "ul", "ol", "li", "blockquote", "span", "hr", "img",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "target"}, "span": {"style"}, "img": {"src", "alt"}}
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

# Only our own uploads, with or without the API host in front.
_IMAGE_SRC = re.compile(
    r"^(?:https?://[^/\s\"'<>]+)?(/api/blog/images/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_IMG_WITHOUT_SRC = re.compile(r"<img(?![^>]*\bsrc=)[^>]*>", re.I)
ALT_MAX = 200

# No practical length limit for writers; this only stops absurd payloads
# (about 2 MB of HTML, far beyond any real article).
MAX_HTML_CHARS = 2_000_000


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
    if tag == "img":
        if attr == "src":
            m = _IMAGE_SRC.match(value.strip())
            return m.group(1).lower() if m else None
        if attr == "alt":
            return value.strip()[:ALT_MAX]
        return None
    if attr == "style":
        return _clean_style(value)
    if attr == "target":
        return "_blank" if value == "_blank" else None
    return value


def sanitize(raw_html):
    """Allowlisted, safe HTML (may be an empty string). Raises ValueError if the
    input is larger than MAX_HTML_CHARS (never silently cuts a post short)."""
    raw_html = str(raw_html or "")
    if len(raw_html) > MAX_HTML_CHARS:
        raise ValueError("too long")
    cleaned = nh3.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=URL_SCHEMES,
        filter_style_properties=STYLE_PROPERTIES,
        link_rel="noopener noreferrer",
    )
    # an <img> whose source was not one of our uploads is removed entirely
    cleaned = _IMG_WITHOUT_SRC.sub("", cleaned)
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
