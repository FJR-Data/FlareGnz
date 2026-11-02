from datetime import date

import pytest

from crm_hygiene import audits, reconcile
from crm_hygiene.normalize import is_valid_email, norm_company, norm_domain


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Vértice Engenharia Ltda.", "vertice engenharia"),
        ("VERTICE ENGENHARIA S/A", "vertice engenharia"),
        ("  Acme,  Inc. ", "acme"),
    ],
)
def test_norm_company_removes_case_accents_and_legal_suffixes(raw, expected):
    assert norm_company(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.acme.com.br/contato", "acme.com.br"),
        ("http://acme.com.br", "acme.com.br"),
        ("ana.silva@Acme.com.br", "acme.com.br"),
        ("", ""),
    ],
)
def test_norm_domain(raw, expected):
    assert norm_domain(raw) == expected


def test_email_validation():
    assert is_valid_email("ana.silva@acme.com.br")
    assert not is_valid_email("ana.silva@")
    assert not is_valid_email("ana silva@acme.com")
    assert not is_valid_email("ana#acme.com")


def test_duplicates_by_domain_and_by_name():
    accounts = [
        {"id": "A1", "name": "Prisma Engenharia Ltda", "website": "https://www.prisma.com.br"},
        {"id": "A2", "name": "PRISMA ENGENHARIA", "website": "http://prisma.com.br/contato"},
        {"id": "A3", "name": "Prisma Engenahria", "website": ""},
        {"id": "A4", "name": "Granito Logística", "website": ""},
    ]
    clusters = audits.find_duplicate_accounts(accounts)
    assert [c["ids"] for c in clusters] == [["A1", "A2", "A3"]]
    reasons = {e["reason"] for e in clusters[0]["evidence"]}
    assert reasons == {"same_domain", "similar_name"}


def test_branch_qualifiers_and_different_domains_are_not_merged():
    accounts = [
        {"id": "A1", "name": "Nova Projetos Leste", "website": ""},
        {"id": "A2", "name": "Nova Projetos Oeste", "website": ""},
        {"id": "A3", "name": "Atlas Energia", "website": "https://atlasenergia.com.br"},
        {"id": "A4", "name": "Atlas Energias", "website": "https://atlas-power.com"},
    ]
    assert audits.find_duplicate_accounts(accounts) == []
    # Without the veto rules the same data produces false positives.
    assert audits.find_duplicate_accounts(accounts, use_vetoes=False)


def test_free_email_domains_do_not_link_accounts():
    accounts = [
        {"id": "A1", "name": "Cedro Saneamento", "website": "gmail.com"},
        {"id": "A2", "name": "Farol Metalúrgica", "website": "gmail.com"},
    ]
    assert audits.find_duplicate_accounts(accounts) == []


def test_missing_invalid_orphans_and_past_due():
    accounts = [{"id": "A1", "name": "Acme", "owner": "", "segment": "AEC"}]
    contacts = [
        {"id": "C1", "account_id": "A1", "email": "ok@acme.com"},
        {"id": "C2", "account_id": "A1", "email": "broken@"},
        {"id": "C3", "account_id": "A9", "email": ""},
    ]
    opps = [
        {"id": "O1", "stage": "Proposta", "close_date": "2026-01-10"},
        {"id": "O2", "stage": "Closed Won", "close_date": "2026-01-10"},
        {"id": "O3", "stage": "Negociação", "close_date": "2027-01-10"},
        {"id": "O4", "stage": "Proposta", "close_date": "10/01/2026"},
    ]
    assert audits.find_missing_required(accounts, ["owner", "segment"]) == [{"id": "A1", "missing": ["owner"]}]
    assert [f["id"] for f in audits.find_invalid_emails(contacts)] == ["C2"]
    assert [f["id"] for f in audits.find_orphans(contacts, accounts)] == ["C3"]
    past_due = audits.find_past_due_open(opps, as_of=date(2026, 10, 31))
    assert [(f["id"], f["issue"]) for f in past_due] == [("O1", "past_due_open"), ("O4", "unparseable_date")]


def test_hygiene_report_score():
    report = audits.hygiene_report(
        accounts=[{"id": "A1", "name": "Acme", "owner": "x", "segment": "y"}],
        contacts=[{"id": "C1", "account_id": "A1", "email": "bad@"}],
        opportunities=[],
        as_of=date(2026, 10, 31),
    )
    assert report["hygiene_score"] == 50.0
    assert report["counts"]["invalid_emails"] == 1


@pytest.mark.parametrize(
    ("source", "target", "category"),
    [
        ("1000.00", "1.000,00", "format_only"),
        ("Proposta", "PROPOSTA", "format_only"),
        ("owner.a", "", "lost_in_target"),
        ("", "owner.a", "added_in_target"),
        ("1000.00", "1100.00", "value_changed"),
        ("same", "same", None),
    ],
)
def test_classify(source, target, category):
    assert reconcile.classify(source, target) == category


def test_reconcile_summary_and_field_map():
    source = [
        {"id": "1", "amount": "100.00", "owner": "a"},
        {"id": "2", "amount": "200.00", "owner": "b"},
        {"id": "3", "amount": "300.00", "owner": "c"},
    ]
    target = [
        {"id": "1", "Amount__c": "100,00", "owner": "a"},
        {"id": "2", "Amount__c": "250.00", "owner": "b"},
        {"id": "4", "Amount__c": "1.00", "owner": "d"},
    ]
    result = reconcile.reconcile(source, target, field_map={"amount": "Amount__c"})
    assert result["missing_in_target"] == ["3"]
    assert result["unexpected_in_target"] == ["4"]
    summary = result["summary"]
    assert summary["matched"] == 2
    assert summary["records_with_material_divergence"] == 1
    assert summary["divergences_by_category"]["format_only"] == 1
    assert summary["divergences_by_category"]["value_changed"] == 1
