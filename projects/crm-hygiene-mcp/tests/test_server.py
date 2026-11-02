"""End-to-end tests through a real MCP client connected in-process."""

import asyncio
from pathlib import Path

import pytest
from mcp import Client

from crm_hygiene.server import server
from crm_hygiene.synth import generate, write_csvs


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch) -> Path:
    write_csvs(generate(seed=3, n_accounts=60, n_contacts=120, n_opps=80), tmp_path)
    monkeypatch.setenv("CRM_HYGIENE_DATA_DIR", str(tmp_path))
    return tmp_path


def run(coro):
    return asyncio.run(coro)


async def _call(name: str, args: dict | None = None):
    async with Client(server) as client:
        return await client.call_tool(name, args or {})


def test_tools_are_listed_and_read_only():
    async def go():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in run(go())}
    assert set(tools) == {"list_exports", "audit_crm", "find_duplicate_accounts", "reconcile_migration"}
    for tool in tools.values():
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False


def test_list_exports(data_dir):
    result = run(_call("list_exports"))
    assert not result.is_error
    names = {e["name"] for e in result.structured_content["exports"]}
    assert names == {"accounts", "contacts", "opportunities", "opportunities_migrated"}


def test_audit_crm_returns_score_and_capped_findings(data_dir):
    result = run(_call("audit_crm", {"as_of": "2026-10-31", "max_findings": 2}))
    assert not result.is_error
    report = result.structured_content
    assert 0 <= report["hygiene_score"] <= 100
    for findings in report["findings"].values():
        assert findings["shown"] <= 2


def test_reconcile_migration_with_field_map(data_dir):
    result = run(_call("reconcile_migration", {"field_map": {"amount": "Amount__c"}}))
    assert not result.is_error
    summary = result.structured_content["summary"]
    assert summary["source_records"] == 80
    assert set(summary["divergences_by_category"]) == {
        "format_only", "lost_in_target", "added_in_target", "value_changed"
    }


@pytest.mark.parametrize("name", ["../secrets", "/etc/passwd", "accounts.csv", "a b"])
def test_rejects_paths_outside_the_data_directory(data_dir, name):
    result = run(_call("audit_crm", {"accounts": name}))
    assert result.is_error


def test_errors_when_data_directory_is_not_configured(monkeypatch):
    monkeypatch.delenv("CRM_HYGIENE_DATA_DIR", raising=False)
    result = run(_call("list_exports"))
    assert result.is_error
    # The model gets an actionable message, not a generic crash.
    assert "CRM_HYGIENE_DATA_DIR" in result.content[0].text


def test_bad_arguments_return_readable_errors(data_dir):
    bad_date = run(_call("audit_crm", {"as_of": "31/10/2026"}))
    assert bad_date.is_error and "ISO date" in bad_date.content[0].text
    bad_threshold = run(_call("find_duplicate_accounts", {"name_threshold": 0.1}))
    assert bad_threshold.is_error and "name_threshold" in bad_threshold.content[0].text
