"""MCP server exposing read-only CRM hygiene and migration-reconciliation tools.

Run over stdio (the default for Claude Code, Claude Desktop and most MCP
clients):

    CRM_HYGIENE_DATA_DIR=./examples/data crm-hygiene-mcp
"""

from __future__ import annotations

import functools
from datetime import date
from typing import Any, Callable, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import audits, data, reconcile

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

server = MCPServer(
    name="crm-hygiene",
    title="CRM Hygiene",
    version="0.1.0",
    instructions=(
        "Read-only tools to audit CRM exports (CSV) and reconcile a migration. "
        "Call list_exports first to see which exports exist. Every tool returns counts plus a "
        "capped list of findings; report counts and the top findings to the user, and never "
        "claim a record was fixed: these tools cannot write to any system."
    ),
)


F = TypeVar("F", bound=Callable[..., Any])


def _anticipated(fn: F) -> F:
    """Turn expected input problems into ToolErrors the model can read and act on.

    Anything else is a real crash: the SDK hides its text from the model and
    logs the traceback on the server.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (data.DataAccessError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper  # type: ignore[return-value]


def _parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"as_of must be an ISO date like 2026-10-31, got {value!r}") from None


def _cap(items: list, limit: int) -> dict[str, Any]:
    limit = max(0, min(limit, 500))
    return {"total": len(items), "shown": min(len(items), limit), "items": items[:limit]}


@server.tool(annotations=READ_ONLY)
@_anticipated
def list_exports() -> dict[str, Any]:
    """List the CSV exports available in the configured data directory, with columns and row counts."""
    return {"exports": data.list_exports()}


@server.tool(annotations=READ_ONLY)
@_anticipated
def audit_crm(
    accounts: str = "accounts",
    contacts: str = "contacts",
    opportunities: str = "opportunities",
    as_of: str | None = None,
    max_findings: int = 25,
) -> dict[str, Any]:
    """Run all hygiene checks and return a 0-100 hygiene score, counts per check and top findings.

    Checks: duplicate accounts, accounts missing owner/segment, invalid contact e-mails,
    contacts pointing to non-existent accounts, and open opportunities with a past close date.
    ``as_of`` is an ISO date (YYYY-MM-DD); defaults to today.
    """
    report = audits.hygiene_report(
        data.load_export(accounts),
        data.load_export(contacts),
        data.load_export(opportunities),
        as_of=_parse_date(as_of),
    )
    report["findings"] = {k: _cap(v, max_findings) for k, v in report["findings"].items()}
    return report


@server.tool(annotations=READ_ONLY)
@_anticipated
def find_duplicate_accounts(
    accounts: str = "accounts", name_threshold: float = 0.9, max_findings: int = 50
) -> dict[str, Any]:
    """Cluster accounts that look like the same company (shared website domain or similar canonical name).

    Lower ``name_threshold`` (0-1) to catch more variants at the cost of false positives.
    """
    if not 0.5 <= name_threshold <= 1.0:
        raise ValueError("name_threshold must be between 0.5 and 1.0")
    clusters = audits.find_duplicate_accounts(data.load_export(accounts), name_threshold=name_threshold)
    return {"clusters": _cap(clusters, max_findings)}


@server.tool(annotations=READ_ONLY)
@_anticipated
def reconcile_migration(
    source: str = "opportunities",
    target: str = "opportunities_migrated",
    key: str = "id",
    fields: list[str] | None = None,
    field_map: dict[str, str] | None = None,
    max_findings: int = 100,
) -> dict[str, Any]:
    """Compare a source-system export with the migrated target export of the same object.

    Every divergence is classified as format_only, lost_in_target, added_in_target or
    value_changed, so cosmetic differences are separated from records that need a fix.
    Use ``field_map`` for renamed columns, e.g. {"amount": "Amount__c"}.
    """
    result = reconcile.reconcile(
        data.load_export(source), data.load_export(target), key=key, fields=fields, field_map=field_map
    )
    result["divergences"] = _cap(result["divergences"], max_findings)
    result["missing_in_target"] = _cap(result["missing_in_target"], max_findings)
    result["unexpected_in_target"] = _cap(result["unexpected_in_target"], max_findings)
    return result


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
