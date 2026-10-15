from __future__ import annotations

import re

_EMOJI_RANGES = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"  # Regional indicator flags.
    "\U0001f300-\U0001faff"  # Pictographs, faces, transport and symbols.
    "\u2600-\u26ff"  # Miscellaneous symbols commonly rendered as emoji.
    "\u2700-\u27bf"  # Dingbats.
    "]"
)
_EMOJI_JOINERS = re.compile(r"[\u200d\ufe0e\ufe0f\u20e3]")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([,.;:!?])(?=\s|$)")


def strip_emojis(text: str, *, trim: bool = True) -> str:
    """Remove emoji glyphs while preserving ordinary speech punctuation and layout."""

    cleaned = _EMOJI_RANGES.sub("", text)
    cleaned = _EMOJI_JOINERS.sub("", cleaned)
    cleaned = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", cleaned)
    if not trim:
        return cleaned
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()
