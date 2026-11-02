# Decision log

Each entry records the context, the decision, the alternatives rejected and how we would know it was wrong.

## D1 · Expose checks over MCP, not as a BI dashboard

- **Context.** Sales Ops teams already have dashboards; what they lack is a fast way to ask "is this data fit to use?" from wherever they work, increasingly from an AI assistant.
- **Decision.** Package the checks as an MCP server. Any MCP client (Claude, Copilot Studio, IDE agents) can call them.
- **Rejected.** A Power BI report: good for monitoring, poor for ad-hoc questions and unusable by agents.
- **Revisit if.** Users only ever look at the same weekly numbers. Then a scheduled report is cheaper.

## D2 · Read-only, file-based access first

- **Context.** In week one of an engagement, API credentials for a production CRM take days or weeks of security review.
- **Decision.** Read CSV exports from a single allowed folder. No credentials, no write path. Tools carry `readOnlyHint` annotations.
- **Rejected.** Direct Salesforce / Dynamics API access in v1: higher value later, but blocks day-one use.
- **Revisit if.** Export freshness becomes the bottleneck. Then add live connectors behind the same tool contract.

## D3 · Favor precision over recall in duplicate detection

- **Context.** A false merge of two accounts rewrites ownership, history and commission. A missed duplicate costs one more look from a human.
- **Decision.** Veto a name-based match when both accounts have different website domain roots, or when the names carry conflicting branch qualifiers (Norte vs Sul, SP vs RJ). Gate: precision ≥ 0.95, recall ≥ 0.80.
- **Evidence.** On 10 seeded datasets, name similarity alone gave precision 0.728; with the vetoes it reached 1.000 at the same recall (0.910). See `evals/RESULTS.md`.
- **Rejected.** Lowering the similarity threshold to raise recall: it raises false merges first.
- **Revisit if.** A customer's accounts rarely have websites. The domain veto then does little and abbreviation handling becomes the priority.

## D4 · Classify migration divergences instead of reporting a single mismatch rate

- **Context.** "3% of records differ" starts an argument; "most differences are formatting, 7 records lost their owner, 9 amounts changed" ends it.
- **Decision.** Every divergence gets one category: `format_only`, `lost_in_target`, `added_in_target`, `value_changed`. The summary reports a material divergence rate that excludes `format_only`.
- **Revisit if.** Users need per-field business rules (e.g. currency conversion). Then add a rules file per object.

## D5 · Evals in CI as a go-live gate

- **Context.** Fuzzy matching regresses silently when someone "just tweaks the threshold".
- **Decision.** `evals/run_evals.py` scores every check on seeded synthetic data and exits non-zero below the gates. Lowering a gate requires an entry in this log.
- **Limitation.** Synthetic data covers patterns we already know. Real engagements should add a small hand-labelled sample from the customer's own data to the eval set.
