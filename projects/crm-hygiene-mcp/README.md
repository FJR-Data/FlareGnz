# crm-hygiene-mcp

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server that lets an AI agent audit CRM exports and reconcile a CRM migration, with an eval suite that gates quality on seeded data.

> **Why this exists.** Every CRM go-live I've worked on hits the same wall: the migration "finished", but nobody trusts the pipeline number. Duplicate accounts, contacts pointing at nothing, open deals with close dates months in the past, amounts that changed format or value on the way over. Agents make this worse when they read that data as-is. This server gives an agent a small set of **safe, explainable checks** to run *before* anyone builds a forecast or an AI workflow on top of the CRM.

It is a generalized, public version of work I've done in the field (Sales Ops CRM audits and post-migration stabilization). **No customer data:** everything here runs on a synthetic dataset with planted, labelled problems.

## What the agent can do

| Tool | Answers the question | Output |
|---|---|---|
| `list_exports` | What data do I have? | CSV exports in the allowed folder, with columns and row counts |
| `audit_crm` | How healthy is this CRM, and where are the problems? | 0–100 hygiene score, counts per check, top findings |
| `find_duplicate_accounts` | Which accounts are the same company? | Clusters with the evidence for each link (shared domain or name similarity score) |
| `reconcile_migration` | Did the migration lose or change anything? | Match rate, missing / unexpected records, every divergence classified as `format_only`, `lost_in_target`, `added_in_target` or `value_changed` |

Checks inside `audit_crm`: duplicate accounts · accounts missing owner or segment · invalid contact e-mails · contacts linked to non-existent accounts · open opportunities whose close date is already past.

### Guardrails

- **Read-only by design.** Every tool is annotated `readOnlyHint: true`, `destructiveHint: false`; there is no write path to any system.
- **Scoped file access.** The server reads only `<name>.csv` files directly inside `CRM_HYGIENE_DATA_DIR`. Paths, extensions and traversal attempts are rejected (tested).
- **Capped outputs.** Findings are truncated (`max_findings`, hard limit 500) while counts stay exact, so an agent can't flood its own context.
- **Explainable results.** Each duplicate link carries its reason and score; each migration divergence carries its category. Nothing is a black-box "risk score".

## Quality: evals as a go-live gate

`evals/run_evals.py` generates 10 synthetic CRMs with known problems, runs every check, and fails CI if precision or recall drops below the gate. Current results ([full table](evals/RESULTS.md)):

| Check | Precision | Recall | Gate |
|---|---:|---:|---|
| Duplicate accounts | **1.000** | **0.910** | P ≥ 0.95 · R ≥ 0.80 |
| Missing required fields · invalid e-mails · orphans · past-due deals | 1.000 | 1.000 | P = R = 1.00 |
| Migration: missing / unexpected records | 1.000 | 1.000 | P = R = 1.00 |
| Migration: divergence classification | 1.000 | 1.000 | P ≥ 0.95 · R ≥ 0.95 |

**What the eval caught.** The first version matched duplicates on name similarity alone and scored **0.728 precision**: it merged sister entities like "Nova Projetos Leste" and "Nova Projetos Oeste". Two veto rules (conflicting branch qualifiers; different website domains) raised precision to **1.000 with no recall loss**. The ablation is regenerated on every run.

**Read these numbers honestly.** Deterministic checks score 1.000 because the planted problems match their spec, not because real CRMs are this clean. Duplicate detection is the only fuzzy check; its 9% miss rate comes from abbreviated names on records without a website ("Prisma Eng." vs "Prisma Engenharia"), which is the next thing to fix.

## Quickstart

```bash
git clone <this repo> && cd crm-hygiene-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m crm_hygiene.synth --out examples/data   # regenerate the sample exports (optional)
pytest                                            # unit + end-to-end MCP tests
python evals/run_evals.py                         # quality gates
```

### Connect it to an MCP client

Claude Code:

```bash
claude mcp add crm-hygiene -e CRM_HYGIENE_DATA_DIR="$PWD/examples/data" -- crm-hygiene-mcp
```

Any client that reads an `mcpServers` config (Claude Desktop, Cursor, VS Code and others):

```json
{
  "mcpServers": {
    "crm-hygiene": {
      "command": "crm-hygiene-mcp",
      "env": { "CRM_HYGIENE_DATA_DIR": "/absolute/path/to/your/exports" }
    }
  }
}
```

Then ask: *"Audit the CRM as of 2026-10-31 and tell me the three problems that most distort the pipeline"* or *"Reconcile opportunities against opportunities_migrated; amount was renamed to Amount__c."*

### Use your own exports

Drop CSVs into the data folder. Default names and columns (rename freely and pass the names as tool arguments):

| Export | Columns used |
|---|---|
| `accounts.csv` | `id`, `name`, `website`, `owner`, `segment` |
| `contacts.csv` | `id`, `account_id`, `email` |
| `opportunities.csv` | `id`, `stage`, `close_date` (ISO), plus any fields to reconcile |
| `<target>.csv` | Same object exported from the new system; map renamed columns with `field_map` |

## Design decisions

Short version below; reasoning and rejected alternatives in [docs/decisions.md](docs/decisions.md).

1. **MCP instead of a dashboard:** the same checks work from Claude, Copilot or any agent the customer already uses.
2. **Read-only and file-based first:** zero credentials to approve, so it can be used on day one of an engagement, before CRM API access exists.
3. **Precision over recall for duplicates:** a wrong merge destroys history; a missed duplicate costs a second look.
4. **Evals in CI, not in a notebook:** a quality regression fails the build like any other bug.

## Project layout

```
src/crm_hygiene/
  normalize.py   # names, domains, e-mails: the comparisons everything else relies on
  audits.py      # hygiene checks + 0-100 score
  reconcile.py   # source vs target migration diff with divergence categories
  synth.py       # synthetic CRM with planted, labelled problems
  data.py        # scoped, read-only CSV access
  server.py      # MCP tools (MCP Python SDK v2)
evals/           # precision/recall gates + ablation
tests/           # unit tests and end-to-end tests through an MCP client
```

## Roadmap

- Abbreviation dictionary for company names (target: duplicate recall ≥ 0.95 at precision 1.000)
- Live connectors (Salesforce, Dynamics 365) behind the same read-only tool contract
- Field-level hygiene trends over time, to track hygiene score as a weekly KPI

---

Built by [Fabio Gonzaga](https://github.com/FJR-Data) · MIT License
