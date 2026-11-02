# Eval results

Synthetic datasets, seeds 1–10 (10 runs), micro-averaged. Regenerate with `python evals/run_evals.py --write`.

| Check | Seeded issues | Precision | Recall | Gate | Status |
|---|---:|---:|---:|---|---|
| `duplicate_accounts` | 100 | 1.000 | 0.910 | P≥0.95 · R≥0.80 | pass |
| `accounts_missing_required` | 111 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `invalid_emails` | 155 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `orphan_contacts` | 121 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `past_due_open_opportunities` | 246 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `migration_missing` | 63 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `migration_unexpected` | 30 | 1.000 | 1.000 | P≥1.00 · R≥1.00 | pass |
| `migration_divergences` | 366 | 1.000 | 1.000 | P≥0.95 · R≥0.95 | pass |

## Ablation: duplicate-account vetoes

| Variant | Precision | Recall |
|---|---:|---:|
| with vetoes (default) | 1.000 | 0.910 |
| name similarity only | 0.728 | 0.910 |
