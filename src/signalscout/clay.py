"""The Clay table spec: validate it, budget it, render it into a build guide.

Clay tables live in Clay's UI; there is no file format to import one. So the design lives in
``clay/table_spec.yaml`` and three things keep it honest:

* **Validation.** Column names are unique, ``{{placeholders}}`` and ``run_if`` conditions name
  real columns, and the Accounts table's imported columns are exactly what ``tier_a.csv`` holds.
* **Budget.** The worst-case credits per Tier-A account (people search, every email provider
  tried, validation, AI columns) and how many accounts a month the plan covers.
* **Build guide.** ``docs/clay-table.md`` is generated from the spec, so it cannot drift from it.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from signalscout.export import CLAY_FIELDS

ColumnKind = Literal["imported", "provided", "claygent", "ai", "waterfall", "enrichment"]
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
RUN_IF_COLUMN = re.compile(r"^(\w+)\b")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Plan(_Model):
    name: str
    data_credits_per_month: int = Field(gt=0)
    actions_per_month: int = Field(gt=0)
    rows_per_table: int = Field(gt=0)


class Provider(_Model):
    name: str
    credits: float = Field(ge=0)


class Column(_Model):
    name: str
    kind: ColumnKind
    run_if: str | None = None
    credits: float = 0
    actions: int = 0
    prompt: str | None = None
    output: dict[str, str] | None = None
    providers: list[Provider] = Field(default_factory=list)
    stop_at_first_result: bool = False

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind in ("claygent", "ai") and not self.prompt:
            raise ValueError(f"{self.name}: {self.kind} columns need a prompt")
        if self.kind == "waterfall" and not self.providers:
            raise ValueError(f"{self.name}: a waterfall needs providers")
        return self

    @property
    def worst_case_credits(self) -> float:
        if self.kind == "waterfall":
            return sum(p.credits for p in self.providers)  # every provider tried, none found
        return self.credits

    @property
    def worst_case_actions(self) -> int:
        return len(self.providers) if self.kind == "waterfall" else self.actions


class Source(_Model):
    kind: Literal["csv_import", "find_people"]
    file: str | None = None
    from_table: str | None = None
    match_on: str | None = None
    titles: list[str] = Field(default_factory=list)
    max_per_company: int = 1
    credits_per_company: float = 0


class Table(_Model):
    name: str
    purpose: str
    source: Source
    columns: list[Column]

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


class ClaySpec(_Model):
    version: Literal[1]
    plan: Plan
    tables: list[Table]
    contact_policy: list[str]

    @model_validator(mode="after")
    def _references(self) -> Self:
        errors: list[str] = []
        names = [t.name for t in self.tables]
        if len(names) != len(set(names)):
            errors.append("table names must be unique")
        by_name = {t.name: t for t in self.tables}
        for table in self.tables:
            own = table.column_names()
            if len(own) != len(set(own)):
                errors.append(f"{table.name}: duplicate column names")
            visible = set(own)
            if table.source.from_table:
                parent = by_name.get(table.source.from_table)
                if parent is None:
                    errors.append(f"{table.name}: unknown source table {table.source.from_table}")
                else:
                    visible |= set(parent.column_names())  # Clay can look up parent columns
            for column in table.columns:
                for ref in PLACEHOLDER.findall(column.prompt or ""):
                    if ref not in visible:
                        errors.append(f"{table.name}.{column.name}: prompt uses unknown {ref}")
                if column.run_if:
                    first = RUN_IF_COLUMN.match(column.run_if)
                    if first is None or first.group(1) not in visible:
                        errors.append(f"{table.name}.{column.name}: run_if names unknown column")
        imported = [
            c.name
            for t in self.tables
            if t.source.kind == "csv_import"
            for c in t.columns
            if c.kind == "imported"
        ]
        if tuple(imported) != CLAY_FIELDS:
            errors.append(f"imported columns {imported} must equal tier_a.csv columns")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def load_clay_spec(path: Path) -> ClaySpec:
    return ClaySpec.model_validate(yaml.safe_load(path.read_text()))


def budget(spec: ClaySpec) -> dict[str, float]:
    """Worst-case credits and actions per Tier-A account, and accounts per month on the plan."""
    credits = actions = 0.0
    for table in spec.tables:
        rows = 1 if table.source.kind == "csv_import" else table.source.max_per_company
        credits += table.source.credits_per_company
        actions += 1 if table.source.kind == "find_people" else 0
        for column in table.columns:
            credits += rows * column.worst_case_credits
            actions += rows * column.worst_case_actions
    by_credits = math.floor(spec.plan.data_credits_per_month / credits) if credits else 0
    by_actions = math.floor(spec.plan.actions_per_month / actions) if actions else 0
    accounts = min(by_credits, by_actions, spec.plan.rows_per_table)
    return {
        "credits_per_account": round(credits, 1),
        "actions_per_account": round(actions, 1),
        "accounts_per_month": accounts,
        "people_per_month": accounts
        * max(
            (t.source.max_per_company for t in spec.tables if t.source.kind == "find_people"),
            default=0,
        ),
    }


def render_guide(spec: ClaySpec, source: str) -> str:
    b = budget(spec)
    out = [
        "# Building the SignalScout tables in Clay",
        "",
        f"Generated from `{source}` by `signalscout clay-spec`. Do not edit by hand.",
        "",
        f"Plan: **Clay {spec.plan.name}**: {spec.plan.data_credits_per_month} data credits and "
        f"{spec.plan.actions_per_month} actions a month, {spec.plan.rows_per_table} rows per "
        "table. Credit costs are worst-case estimates (Clay publishes no per-provider prices).",
        "",
        "| Budget | Worst case |",
        "|---|---|",
        f"| Credits per Tier-A account | {b['credits_per_account']:g} |",
        f"| Actions per Tier-A account | {b['actions_per_account']:g} |",
        f"| Tier-A accounts per month on this plan | {b['accounts_per_month']:g} |",
        f"| People reached per month | {b['people_per_month']:g} |",
        "",
    ]
    for n, table in enumerate(spec.tables, start=1):
        out += [f"## {n}. {table.name}", "", table.purpose, ""]
        src = table.source
        if src.kind == "csv_import":
            out += [f"Create a table and import `{src.file}` (one row per account).", ""]
        else:
            out += [
                f"Create a table from **Find people** on `{src.from_table}`, matching on "
                f"`{src.match_on}`, at most {src.max_per_company} per company, titles:",
                "",
                *[f"- {title}" for title in src.titles],
                "",
            ]
        out += ["| Column | Kind | Run only if | Worst-case credits |", "|---|---|---|---|"]
        for c in table.columns:
            out.append(
                f"| `{c.name}` | {c.kind} | {c.run_if or 'always'} | {c.worst_case_credits:g} |"
            )
        out.append("")
        for c in table.columns:
            if c.prompt:
                out += [f"**`{c.name}` prompt**", "", "> " + " ".join(c.prompt.split()), ""]
                if c.output:
                    out += [
                        "Output fields: " + ", ".join(f"`{k}` ({v})" for k, v in c.output.items()),
                        "",
                    ]
            if c.kind == "waterfall":
                steps = " -> ".join(f"{p.name} ({p.credits:g})" for p in c.providers)
                out += [f"**`{c.name}` waterfall** (stop at first result): {steps}", ""]
    out += ["## Contact policy", "", *[f"- {line}" for line in spec.contact_policy], ""]
    return "\n".join(out)
