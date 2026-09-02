"""
Facilities Module — Alias Normalizer
=======================================
Normalizes building/project aliases in free text (voice transcripts or typed
messages) to their canonical building codes (GETT, GEBB1, GEBB2, Common).

Usage:
    from facilities.alias_normalizer import normalize_building_aliases
    clean = normalize_building_aliases("Check the water tank in Trade Tower")
    # → "Check the water tank in GETT"

Aliases are sourced from ``facilities.config.BUILDING_ALIASES`` so adding a
new alias only requires editing that dictionary — no code changes here.
"""

import re
import logging
from functools import lru_cache
from typing import List, Tuple

from facilities.config import BUILDING_ALIASES

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _compiled_alias_patterns() -> List[Tuple[re.Pattern, str]]:
    """Build regex patterns from BUILDING_ALIASES, sorted longest-first.

    Longest-first ordering ensures "trade tower building" matches before
    "trade tower", and "good earth business bay 1" before "bay 1".

    Each pattern uses word boundaries (``\\b``) so "Bay 1" inside "Bay 100"
    won't be incorrectly replaced.
    """
    patterns = []
    # Sort aliases by length descending so longer phrases match first
    sorted_aliases = sorted(BUILDING_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        canonical = BUILDING_ALIASES[alias]
        # Build a word-boundary regex — case insensitive
        escaped = re.escape(alias)
        pattern = re.compile(rf"\b{escaped}\b", re.IGNORECASE)
        patterns.append((pattern, canonical))
    return patterns


def normalize_building_aliases(text: str) -> str:
    """Replace all known building aliases in *text* with their canonical codes.

    The replacement is case-insensitive and respects word boundaries.

    Args:
        text: Raw input (voice transcript or typed message).

    Returns:
        Text with building aliases replaced by canonical codes
        (e.g. "Trade Tower" → "GETT").
    """
    if not text:
        return text

    result = text
    for pattern, canonical in _compiled_alias_patterns():
        result = pattern.sub(canonical, result)

    if result != text:
        logger.debug(f"Alias normalizer: '{text}' → '{result}'")

    return result
