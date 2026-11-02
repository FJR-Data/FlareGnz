"""Source-vs-target reconciliation for CRM migrations.

After a migration, "the numbers don't match" is not actionable. This module
splits every divergence into a category, so the team can separate cosmetic
differences (case, accents, number formatting) from records that were lost
or changed and need a fix before go-live sign-off.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from .normalize import is_blank, norm_text

Record = dict[str, str]

CATEGORIES = ("format_only", "lost_in_target", "added_in_target", "value_changed")


def _as_number(value: str) -> float | None:
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        # Keep the last separator as the decimal mark: 1.234,56 or 1,234.56
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def classify(source_value: str | None, target_value: str | None) -> str | None:
    """Return the divergence category, or None when the values agree."""
    if (source_value or "") == (target_value or ""):
        return None
    if is_blank(source_value) and is_blank(target_value):
        return None
    if is_blank(target_value):
        return "lost_in_target"
    if is_blank(source_value):
        return "added_in_target"
    if norm_text(source_value) == norm_text(target_value):
        return "format_only"
    left, right = _as_number(source_value), _as_number(target_value)
    if left is not None and right is not None and abs(left - right) < 1e-9:
        return "format_only"
    return "value_changed"


def reconcile(
    source: Iterable[Record],
    target: Iterable[Record],
    key: str = "id",
    fields: list[str] | None = None,
    field_map: dict[str, str] | None = None,
) -> dict:
    """Compare two exports of the same object.

    ``field_map`` maps source field names to target field names for renamed
    columns (for example ``{"amount": "Amount__c"}``). When ``fields`` is
    omitted, every source column except the key is compared.
    """
    source = list(source)
    target = list(target)
    field_map = field_map or {}
    if fields is None:
        fields = [f for f in (source[0].keys() if source else []) if f != key]

    target_by_key: dict[str, Record] = {}
    duplicate_keys: list[str] = []
    for row in target:
        k = row.get(key, "")
        if k in target_by_key:
            duplicate_keys.append(k)
        target_by_key[k] = row
    source_keys = {row.get(key, "") for row in source}

    missing = sorted(k for k in source_keys if k not in target_by_key)
    unexpected = sorted(k for k in target_by_key if k not in source_keys)

    divergences: list[dict] = []
    for row in source:
        k = row.get(key, "")
        match = target_by_key.get(k)
        if match is None:
            continue
        for field in fields:
            target_field = field_map.get(field, field)
            category = classify(row.get(field), match.get(target_field))
            if category:
                divergences.append({
                    "key": k,
                    "field": field,
                    "source": row.get(field, ""),
                    "target": match.get(target_field, ""),
                    "category": category,
                })

    matched = len(source_keys) - len(missing)
    material = {d["key"] for d in divergences if d["category"] != "format_only"}
    by_category = Counter(d["category"] for d in divergences)
    return {
        "summary": {
            "source_records": len(source_keys),
            "target_records": len(target_by_key),
            "matched": matched,
            "match_rate": round(matched / len(source_keys), 4) if source_keys else 1.0,
            "records_with_material_divergence": len(material),
            "material_divergence_rate": round(len(material) / matched, 4) if matched else 0.0,
            "divergences_by_category": {c: by_category.get(c, 0) for c in CATEGORIES},
        },
        "missing_in_target": missing,
        "unexpected_in_target": unexpected,
        "duplicate_keys_in_target": sorted(set(duplicate_keys)),
        "divergences": divergences,
    }
