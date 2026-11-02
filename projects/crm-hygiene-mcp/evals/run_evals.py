"""Score every check against seeded ground truth and gate on minimum quality.

    python evals/run_evals.py            # print the table, exit 1 if a gate fails
    python evals/run_evals.py --write    # also refresh evals/RESULTS.md

Metrics are micro-averaged precision and recall over several random seeds, so
a change that only works on one dataset does not pass.
"""

from __future__ import annotations

import argparse
import sys
from itertools import combinations
from pathlib import Path

from crm_hygiene import audits, reconcile
from crm_hygiene.synth import AS_OF, generate

# Minimum precision / recall per check. Raising a gate is a deliberate decision;
# lowering one needs a written reason in docs/decisions.md.
GATES = {
    "duplicate_accounts": (0.95, 0.80),
    "accounts_missing_required": (1.0, 1.0),
    "invalid_emails": (1.0, 1.0),
    "orphan_contacts": (1.0, 1.0),
    "past_due_open_opportunities": (1.0, 1.0),
    "migration_missing": (1.0, 1.0),
    "migration_unexpected": (1.0, 1.0),
    "migration_divergences": (0.95, 0.95),
}

RESULTS = Path(__file__).with_name("RESULTS.md")


def duplicate_ablation(seeds: list[int]) -> dict[str, tuple[float, float]]:
    """Precision/recall of duplicate detection with and without the veto rules."""
    out = {}
    for label, vetoes in (("with vetoes (default)", True), ("name similarity only", False)):
        tp = fp = fn = 0
        for seed in seeds:
            ds = generate(seed)
            pred = set()
            for cluster in audits.find_duplicate_accounts(ds.accounts, use_vetoes=vetoes):
                pred.update(tuple(sorted(p)) for p in combinations(cluster["ids"], 2))
            truth = {tuple(p) for p in ds.truth["duplicate_pairs"]}
            tp += len(pred & truth)
            fp += len(pred - truth)
            fn += len(truth - pred)
        out[label] = (round(tp / (tp + fp), 3) if tp + fp else 1.0, round(tp / (tp + fn), 3) if tp + fn else 1.0)
    return out


def predict(seed: int) -> tuple[dict[str, set], dict[str, set]]:
    ds = generate(seed)
    truth = ds.truth
    dup_pred = set()
    for cluster in audits.find_duplicate_accounts(ds.accounts):
        dup_pred.update(tuple(sorted(p)) for p in combinations(cluster["ids"], 2))
    rec = reconcile.reconcile(
        ds.opportunities, ds.opportunities_migrated, key="id", field_map={"amount": "Amount__c"}
    )
    predicted = {
        "duplicate_accounts": dup_pred,
        "accounts_missing_required": {
            f["id"] for f in audits.find_missing_required(ds.accounts, ["name", "owner", "segment"])
        },
        "invalid_emails": {f["id"] for f in audits.find_invalid_emails(ds.contacts)},
        "orphan_contacts": {f["id"] for f in audits.find_orphans(ds.contacts, ds.accounts)},
        "past_due_open_opportunities": {f["id"] for f in audits.find_past_due_open(ds.opportunities, AS_OF)},
        "migration_missing": set(rec["missing_in_target"]),
        "migration_unexpected": set(rec["unexpected_in_target"]),
        "migration_divergences": {(d["key"], d["field"], d["category"]) for d in rec["divergences"]},
    }
    expected = {
        "duplicate_accounts": {tuple(p) for p in truth["duplicate_pairs"]},
        "accounts_missing_required": set(truth["accounts_missing_required"]),
        "invalid_emails": set(truth["invalid_emails"]),
        "orphan_contacts": set(truth["orphan_contacts"]),
        "past_due_open_opportunities": set(truth["past_due_open_opportunities"]),
        "migration_missing": set(truth["migration_missing"]),
        "migration_unexpected": set(truth["migration_unexpected"]),
        "migration_divergences": {tuple(d) for d in truth["migration_divergences"]},
    }
    return predicted, expected


def evaluate(seeds: list[int]) -> dict[str, dict]:
    totals = {k: {"tp": 0, "fp": 0, "fn": 0} for k in GATES}
    for seed in seeds:
        predicted, expected = predict(seed)
        for check in GATES:
            p, e = predicted[check], expected[check]
            totals[check]["tp"] += len(p & e)
            totals[check]["fp"] += len(p - e)
            totals[check]["fn"] += len(e - p)
    results = {}
    for check, t in totals.items():
        precision = t["tp"] / (t["tp"] + t["fp"]) if t["tp"] + t["fp"] else 1.0
        recall = t["tp"] / (t["tp"] + t["fn"]) if t["tp"] + t["fn"] else 1.0
        min_p, min_r = GATES[check]
        results[check] = {
            **t,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "passed": precision >= min_p and recall >= min_r,
            "gate": f"P≥{min_p:.2f} · R≥{min_r:.2f}",
        }
    return results


def to_markdown(results: dict[str, dict], seeds: list[int], ablation: dict | None = None) -> str:
    lines = [
        "# Eval results",
        "",
        f"Synthetic datasets, seeds {seeds[0]}–{seeds[-1]} ({len(seeds)} runs), micro-averaged. "
        "Regenerate with `python evals/run_evals.py --write`.",
        "",
        "| Check | Seeded issues | Precision | Recall | Gate | Status |",
        "|---|---:|---:|---:|---|---|",
    ]
    for check, r in results.items():
        status = "pass" if r["passed"] else "**FAIL**"
        lines.append(
            f"| `{check}` | {r['tp'] + r['fn']} | {r['precision']:.3f} | {r['recall']:.3f} | {r['gate']} | {status} |"
        )
    if ablation:
        lines += [
            "",
            "## Ablation: duplicate-account vetoes",
            "",
            "| Variant | Precision | Recall |",
            "|---|---:|---:|",
        ]
        lines += [f"| {label} | {p:.3f} | {r:.3f} |" for label, (p, r) in ablation.items()]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10, help="number of random datasets to score")
    parser.add_argument("--write", action="store_true", help="refresh evals/RESULTS.md")
    args = parser.parse_args()
    seeds = list(range(1, args.seeds + 1))
    results = evaluate(seeds)
    table = to_markdown(results, seeds, duplicate_ablation(seeds))
    print(table)
    if args.write:
        RESULTS.write_text(table, encoding="utf-8")
    failed = [c for c, r in results.items() if not r["passed"]]
    if failed:
        print(f"Gate failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
