"""
Plain-ASCII text sanitization.

HHS-OIG's online submission form rejects non-ASCII typographic characters
(em/en dashes, curly quotes, ellipsis, etc.). Any narrative text destined for
copy-paste into an OIG intake field — the Hotline tip, the referral packet —
must be normalized to plain 7-bit ASCII first. This module is the single place
that mapping lives so every generator sanitizes identically.
"""
from __future__ import annotations

import unicodedata

# Explicit replacements for the common typographic characters our narrative
# generators emit. Anything not covered here falls through to a Unicode
# NFKD-decompose + ASCII-drop pass.
_REPLACEMENTS = {
    "‐": "-",   # hyphen
    "‑": "-",   # non-breaking hyphen
    "‒": "-",   # figure dash
    "–": "-",   # en dash
    "—": "-",   # em dash
    "―": "-",   # horizontal bar
    "‘": "'",   # left single quote
    "’": "'",   # right single quote / apostrophe
    "‚": "'",   # single low-9 quote
    "‛": "'",   # single high-reversed-9 quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "„": '"',   # double low-9 quote
    "…": "...",  # ellipsis
    "′": "'",   # prime
    "″": '"',   # double prime
    " ": " ",   # non-breaking space
    " ": " ",   # figure space
    " ": " ",   # thin space
    " ": " ",   # narrow no-break space
    "→": "->",  # rightwards arrow
    "←": "<-",  # leftwards arrow
    "·": "-",   # middle dot
    "•": "-",   # bullet
    "®": "(R)",  # registered
    "©": "(C)",  # copyright
    "™": "(TM)",  # trademark
    "°": " deg",  # degree
}


def to_ascii(text: str) -> str:
    """Return ``text`` reduced to plain 7-bit ASCII.

    Known typographic characters map to sensible ASCII equivalents; any
    remaining non-ASCII is NFKD-decomposed and stripped so the output is always
    encodable as ASCII (safe for OIG's submission form).
    """
    if not text:
        return ""
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Decompose accented characters (e.g. "é" -> "e") then drop anything left
    # that still isn't ASCII.
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")
