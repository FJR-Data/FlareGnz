"""CRM hygiene checks over plain record dictionaries (one dict per CSV row).

Each check returns JSON-serialisable findings so the MCP layer can pass them
straight to an agent, and so the eval harness can score them against seeded
ground truth.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from difflib import SequenceMatcher
from typing import Iterable

from .normalize import is_blank, is_valid_email, norm_company, norm_domain

Record = dict[str, str]

# Shared mailbox providers say nothing about which company a record belongs to.
FREE_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.com.br", "icloud.com",
    "live.com", "uol.com.br", "bol.com.br",
}

OPEN_STAGES_EXCLUDED = {"closed won", "closed lost", "fechado ganho", "fechado perdido"}

# Tokens that distinguish branches or regional entities of the same group.
# "Acme Norte" and "Acme Sul" are usually different accounts, not duplicates.
BRANCH_QUALIFIERS = {
    "norte", "sul", "leste", "oeste", "nordeste", "sudeste", "centro", "centrooeste", "capital",
    "interior", "litoral", "serra", "filial", "matriz", "bahia", "paulista", "minas",
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb",
    "pr", "pe", "pi", "rj", "rn", "rs", "ro", "rr", "sc", "sp", "se", "to",
}


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _company_domain(account: Record) -> str:
    domain = norm_domain(account.get("website"))
    return "" if domain in FREE_EMAIL_DOMAINS else domain


def _domain_root(domain: str) -> str:
    """'acme.com.br' and 'acme.com' share the root 'acme'."""
    return domain.split(".", 1)[0] if domain else ""


def _conflicting_qualifiers(left: str, right: str) -> bool:
    """True when each name carries a branch qualifier the other lacks (Norte vs Sul)."""
    lt, rt = set(left.split()), set(right.split())
    return bool((lt - rt) & BRANCH_QUALIFIERS) and bool((rt - lt) & BRANCH_QUALIFIERS)


def find_duplicate_accounts(
    accounts: Iterable[Record], name_threshold: float = 0.9, id_field: str = "id", use_vetoes: bool = True
) -> list[dict]:
    """Cluster accounts that look like the same company.

    Two accounts are linked when they share a company website domain, or when
    their canonical names are at least ``name_threshold`` similar. A name match
    is vetoed when both accounts have websites with different domain roots, or
    when the names carry conflicting branch qualifiers (Norte vs Sul): those
    are usually sister entities, and merging them is costlier than missing a
    duplicate. Candidate pairs are blocked by domain and by the first 3
    letters of the canonical name so the check stays near-linear on large
    exports.
    """
    rows = [a for a in accounts if not is_blank(a.get(id_field))]
    by_id = {a[id_field]: a for a in rows}
    blocks: dict[str, list[str]] = defaultdict(list)
    for a in rows:
        name = norm_company(a.get("name"))
        domain = _company_domain(a)
        if domain:
            blocks[f"d:{domain}"].append(a[id_field])
        if name:
            blocks[f"n:{name[:3]}"].append(a[id_field])

    uf = _UnionFind()
    reasons: dict[frozenset[str], tuple[str, float]] = {}
    for key, ids in blocks.items():
        unique = sorted(set(ids))
        for i, left in enumerate(unique):
            for right in unique[i + 1:]:
                pair = frozenset((left, right))
                if pair in reasons:
                    continue
                if key.startswith("d:"):
                    reasons[pair] = ("same_domain", 1.0)
                    uf.union(left, right)
                    continue
                left_name = norm_company(by_id[left].get("name"))
                right_name = norm_company(by_id[right].get("name"))
                left_root = _domain_root(_company_domain(by_id[left]))
                right_root = _domain_root(_company_domain(by_id[right]))
                if use_vetoes and left_root and right_root and left_root != right_root:
                    continue
                if use_vetoes and _conflicting_qualifiers(left_name, right_name):
                    continue
                score = SequenceMatcher(None, left_name, right_name).ratio()
                if score >= name_threshold:
                    reasons[pair] = ("similar_name", round(score, 3))
                    uf.union(left, right)

    clusters: dict[str, set[str]] = defaultdict(set)
    for pair in reasons:
        for member in pair:
            clusters[uf.find(member)].add(member)

    findings = []
    for members in clusters.values():
        ordered = sorted(members)
        evidence = [
            {"pair": sorted(pair), "reason": reason, "score": score}
            for pair, (reason, score) in sorted(reasons.items(), key=lambda kv: sorted(kv[0]))
            if pair <= members
        ]
        findings.append({
            "ids": ordered,
            "names": [by_id[i].get("name", "") for i in ordered],
            "evidence": evidence,
        })
    return sorted(findings, key=lambda f: f["ids"])


def find_missing_required(
    records: Iterable[Record], required: list[str], id_field: str = "id"
) -> list[dict]:
    return [
        {"id": r.get(id_field, ""), "missing": missing}
        for r in records
        if (missing := [f for f in required if is_blank(r.get(f))])
    ]


def find_invalid_emails(contacts: Iterable[Record], field: str = "email", id_field: str = "id") -> list[dict]:
    return [
        {"id": c.get(id_field, ""), "email": c.get(field, "")}
        for c in contacts
        if not is_blank(c.get(field)) and not is_valid_email(c.get(field))
    ]


def find_orphans(
    children: Iterable[Record], parents: Iterable[Record], fk_field: str = "account_id", id_field: str = "id"
) -> list[dict]:
    """Child records whose foreign key points to no existing parent."""
    parent_ids = {p.get(id_field) for p in parents}
    return [
        {"id": c.get(id_field, ""), fk_field: c.get(fk_field, "")}
        for c in children
        if not is_blank(c.get(fk_field)) and c.get(fk_field) not in parent_ids
    ]


def find_past_due_open(
    opportunities: Iterable[Record],
    as_of: date,
    close_field: str = "close_date",
    stage_field: str = "stage",
    id_field: str = "id",
) -> list[dict]:
    """Open opportunities whose expected close date is already in the past.

    These inflate pipeline and forecast; they are the first thing a sales
    leader asks about after a CRM migration.
    """
    findings = []
    for o in opportunities:
        stage = (o.get(stage_field) or "").strip().lower()
        raw = (o.get(close_field) or "").strip()
        if stage in OPEN_STAGES_EXCLUDED or not raw:
            continue
        try:
            close = date.fromisoformat(raw)
        except ValueError:
            findings.append({"id": o.get(id_field, ""), "close_date": raw, "issue": "unparseable_date"})
            continue
        if close < as_of:
            findings.append({
                "id": o.get(id_field, ""),
                "close_date": raw,
                "days_overdue": (as_of - close).days,
                "issue": "past_due_open",
            })
    return findings


def hygiene_report(
    accounts: list[Record],
    contacts: list[Record],
    opportunities: list[Record],
    as_of: date,
    account_required: tuple[str, ...] = ("name", "owner", "segment"),
) -> dict:
    """Run every check and return findings plus a 0-100 hygiene score.

    The score is the share of records with no finding, so it can be tracked
    week over week as a single adoption-friendly KPI.
    """
    duplicates = find_duplicate_accounts(accounts)
    missing = find_missing_required(accounts, list(account_required))
    invalid = find_invalid_emails(contacts)
    orphans = find_orphans(contacts, accounts)
    past_due = find_past_due_open(opportunities, as_of)

    # Record ids are assumed unique across the three tables (e.g. A-, C-, O- prefixes).
    flagged: set[str] = set()
    for cluster in duplicates:
        flagged.update(cluster["ids"][1:])  # keep one survivor per cluster
    flagged.update(m["id"] for m in missing)
    flagged.update(f["id"] for f in invalid)
    flagged.update(f["id"] for f in orphans)
    flagged.update(f["id"] for f in past_due)

    total = len(accounts) + len(contacts) + len(opportunities)
    score = round(100 * (1 - len(flagged) / total), 1) if total else 100.0
    return {
        "as_of": as_of.isoformat(),
        "records": {"accounts": len(accounts), "contacts": len(contacts), "opportunities": len(opportunities)},
        "hygiene_score": score,
        "counts": {
            "duplicate_account_clusters": len(duplicates),
            "accounts_missing_required": len(missing),
            "invalid_emails": len(invalid),
            "orphan_contacts": len(orphans),
            "past_due_open_opportunities": len(past_due),
        },
        "findings": {
            "duplicate_accounts": duplicates,
            "accounts_missing_required": missing,
            "invalid_emails": invalid,
            "orphan_contacts": orphans,
            "past_due_open_opportunities": past_due,
        },
    }
