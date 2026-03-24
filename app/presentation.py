from __future__ import annotations

import re

PLAN_DISPLAY_NOISE_PATTERNS = (
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:mb|gb)(?:/day)?\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*day(?:s)?\b", re.IGNORECASE),
    re.compile(r"\bunlimited\b", re.IGNORECASE),
)


def sanitize_plan_display_name(plan_name: str) -> str:
    cleaned = plan_name
    for pattern in PLAN_DISPLAY_NOISE_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s*[-|/]\s*$", "", cleaned)
    cleaned = cleaned.strip(" -|/")
    return cleaned.strip() or plan_name.strip()
