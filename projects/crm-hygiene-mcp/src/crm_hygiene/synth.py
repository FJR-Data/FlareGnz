"""Synthetic CRM dataset with seeded, labelled problems.

No real customer data is used anywhere in this project. The generator plants
known issues (duplicates, missing fields, bad e-mails, orphans, past-due
opportunities, migration drift) and returns the ground truth, which the eval
harness uses to score every check.

Usage:
    python -m crm_hygiene.synth --out examples/data --seed 7
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .normalize import strip_accents

AS_OF = date(2026, 10, 31)

PREFIXES = [
    "Nova", "Alto", "Vale", "Prisma", "Atlas", "Rio", "Delta", "Horizonte", "Sol", "Terra",
    "Ponte", "Vértice", "Aurora", "Lumen", "Orbe", "Granito", "Cedro", "Farol", "Quartzo", "Monte",
]
CORES = [
    "Engenharia", "Construtora", "Arquitetura", "Projetos", "Infraestrutura", "Estruturas",
    "Manufatura", "Logística", "Energia", "Urbanismo", "Saneamento", "Metalúrgica",
]
REGIONS = ["Sul", "Norte", "Bahia", "Paulista", "Minas", "Leste", "Oeste", "Capital", "Litoral", "Serra"]
LEGAL = ["Ltda", "S.A.", "ME", ""]
SEGMENTS = ["AEC", "Manufacturing", "Media", "Public Sector"]
OWNERS = ["owner.a", "owner.b", "owner.c", "owner.d", "owner.e"]
FIRST = ["ana", "bruno", "carla", "diego", "elisa", "fabio", "gabi", "heitor", "iris", "joao", "lara", "marcos"]
LAST = ["silva", "souza", "lima", "costa", "rocha", "alves", "pereira", "ramos", "dias", "melo"]
FREE = ["gmail.com", "hotmail.com", "outlook.com"]
OPEN_STAGES = ["Prospecção", "Qualificação", "Proposta", "Negociação"]
ABBREVIATIONS = {
    "Engenharia": "Eng.", "Construtora": "Constr.", "Infraestrutura": "Infra", "Arquitetura": "Arq.",
    "Logística": "Log.", "Metalúrgica": "Metal.", "Manufatura": "Manuf.", "Saneamento": "San.",
}
CLOSED_STAGES = ["Closed Won", "Closed Lost"]


@dataclass
class Dataset:
    accounts: list[dict] = field(default_factory=list)
    contacts: list[dict] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)
    opportunities_migrated: list[dict] = field(default_factory=list)
    truth: dict = field(default_factory=dict)


def _slug(name: str) -> str:
    return "".join(c for c in strip_accents(name).lower() if c.isalnum())


def _vary_name(name: str, rng: random.Random) -> str:
    """A realistic duplicate: same company, typed differently."""
    base = name
    for suffix in ("Ltda", "S.A.", "ME"):
        base = base.replace(f" {suffix}", "")
    style = rng.choice(["upper", "accents", "suffix", "typo", "abbrev"])
    if style == "abbrev":
        for word, short in ABBREVIATIONS.items():
            if word in base:
                return base.replace(word, short)
        style = "typo"
    if style == "upper":
        return base.upper()
    if style == "accents":
        return strip_accents(base) + " Ltda."
    if style == "suffix":
        return base + " S/A"
    chars = list(base)
    i = rng.randrange(1, len(chars) - 2)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def generate(seed: int = 7, n_accounts: int = 200, n_contacts: int = 400, n_opps: int = 300) -> Dataset:
    rng = random.Random(seed)
    ds = Dataset()
    truth: dict = {
        "duplicate_pairs": [],
        "accounts_missing_required": [],
        "invalid_emails": [],
        "orphan_contacts": [],
        "past_due_open_opportunities": [],
        "migration_missing": [],
        "migration_unexpected": [],
        "migration_divergences": [],
    }

    combos = [(p, c, r) for p in PREFIXES for c in CORES for r in REGIONS]
    rng.shuffle(combos)
    domains: dict[str, str] = {}
    for i, (p, c, r) in enumerate(combos[:n_accounts]):
        name = f"{p} {c} {r} {rng.choice(LEGAL)}".strip()
        acc_id = f"A-{i + 1:05d}"
        website = f"https://www.{_slug(p + c + r)}.com.br" if rng.random() < 0.8 else ""
        if website:
            domains[acc_id] = website.split("www.", 1)[1]
        account = {"id": acc_id, "name": name, "website": website,
                   "owner": rng.choice(OWNERS), "segment": rng.choice(SEGMENTS)}
        if rng.random() < 0.06:
            account[rng.choice(["owner", "segment"])] = ""
            truth["accounts_missing_required"].append(acc_id)
        ds.accounts.append(account)

    # Seed duplicates (about 5% of accounts).
    originals = rng.sample(ds.accounts, k=max(1, n_accounts // 20))
    for j, orig in enumerate(originals):
        dup_id = f"A-{n_accounts + j + 1:05d}"
        website = orig["website"]
        roll = rng.random()
        if roll < 0.3:
            website = ""  # rep created the record without a website
        elif website and roll < 0.65:
            website = website.replace("https://www.", "http://") + "/contato"
        dup = {"id": dup_id, "name": _vary_name(orig["name"], rng), "website": website,
               "owner": rng.choice(OWNERS), "segment": orig["segment"] or rng.choice(SEGMENTS)}
        ds.accounts.append(dup)
        truth["duplicate_pairs"].append(sorted([orig["id"], dup_id]))

    account_ids = [a["id"] for a in ds.accounts]
    for i in range(n_contacts):
        cid = f"C-{i + 1:05d}"
        acc = rng.choice(account_ids)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        domain = domains.get(acc) or rng.choice(FREE)
        email = f"{first}.{last}@{domain}"
        roll = rng.random()
        if roll < 0.04:
            email = rng.choice([f"{first}.{last}@", f"{first}#{last}.com", f"{first} {last}@{domain}"])
            truth["invalid_emails"].append(cid)
        elif roll < 0.07:
            acc = f"A-9{rng.randrange(1000, 9999)}"
            truth["orphan_contacts"].append(cid)
        ds.contacts.append({"id": cid, "account_id": acc, "name": f"{first.title()} {last.title()}", "email": email})

    for i in range(n_opps):
        oid = f"O-{i + 1:05d}"
        if rng.random() < 0.3:
            stage = rng.choice(CLOSED_STAGES)
            close = AS_OF - timedelta(days=rng.randrange(1, 365))
        else:
            stage = rng.choice(OPEN_STAGES)
            if rng.random() < 0.12:
                close = AS_OF - timedelta(days=rng.randrange(1, 180))
                truth["past_due_open_opportunities"].append(oid)
            else:
                close = AS_OF + timedelta(days=rng.randrange(0, 270))
        ds.opportunities.append({
            "id": oid, "account_id": rng.choice(account_ids), "stage": stage,
            "amount": f"{rng.randrange(5, 500) * 1000:.2f}", "owner": rng.choice(OWNERS),
            "close_date": close.isoformat(),
        })

    # Migration drift: target system export with renamed amount column.
    for opp in ds.opportunities:
        roll = rng.random()
        if roll < 0.02:
            truth["migration_missing"].append(opp["id"])
            continue
        row = {"id": opp["id"], "account_id": opp["account_id"], "stage": opp["stage"],
               "Amount__c": opp["amount"], "owner": opp["owner"], "close_date": opp["close_date"]}
        if roll < 0.07:
            value = float(opp["amount"])
            row["Amount__c"] = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            truth["migration_divergences"].append([opp["id"], "amount", "format_only"])
        elif roll < 0.09:
            row["owner"] = ""
            truth["migration_divergences"].append([opp["id"], "owner", "lost_in_target"])
        elif roll < 0.12:
            row["Amount__c"] = f"{float(opp['amount']) * 1.1:.2f}"
            truth["migration_divergences"].append([opp["id"], "amount", "value_changed"])
        elif roll < 0.14:
            row["stage"] = opp["stage"].upper()
            truth["migration_divergences"].append([opp["id"], "stage", "format_only"])
        ds.opportunities_migrated.append(row)
    for k in range(max(1, n_opps // 100)):
        oid = f"O-9{k:04d}"
        ds.opportunities_migrated.append({"id": oid, "account_id": rng.choice(account_ids), "stage": "Proposta",
                                          "Amount__c": "1000.00", "owner": rng.choice(OWNERS),
                                          "close_date": AS_OF.isoformat()})
        truth["migration_unexpected"].append(oid)

    ds.truth = truth
    return ds


def write_csvs(ds: Dataset, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tables = {
        "accounts": ds.accounts,
        "contacts": ds.contacts,
        "opportunities": ds.opportunities,
        "opportunities_migrated": ds.opportunities_migrated,
    }
    for name, rows in tables.items():
        with (out / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("examples/data"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    write_csvs(generate(args.seed), args.out)
    print(f"Wrote synthetic CRM exports to {args.out}")


if __name__ == "__main__":
    main()
