from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from signalscout.clay import ClaySpec, budget, load_clay_spec, render_guide
from signalscout.export import CLAY_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "clay" / "table_spec.yaml"
RAW: dict[str, Any] = yaml.safe_load(SPEC_PATH.read_text())


def mutated() -> dict[str, Any]:
    return copy.deepcopy(RAW)


def problems(raw: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        ClaySpec.model_validate(raw)
    return str(info.value)


def test_shipped_spec_is_valid_and_matches_the_export() -> None:
    spec = load_clay_spec(SPEC_PATH)
    imported = [c.name for c in spec.tables[0].columns if c.kind == "imported"]
    assert tuple(imported) == CLAY_FIELDS  # the Clay import and tier_a.csv agree


def test_budget_is_the_worst_case() -> None:
    b = budget(load_clay_spec(SPEC_PATH))
    # 1 people search + 2 people x (2 + 2 + 3 waterfall + 1 validation) = 17
    assert b == {
        "credits_per_account": 17.0,
        "actions_per_account": 12.0,
        "accounts_per_month": 5,
        "people_per_month": 10,
    }


def test_budget_is_capped_by_actions_and_rows() -> None:
    raw = mutated()
    raw["plan"]["data_credits_per_month"] = 100_000
    assert budget(ClaySpec.model_validate(raw))["accounts_per_month"] == 41  # 500 // 12 actions
    raw["plan"]["actions_per_month"] = 100_000
    assert budget(ClaySpec.model_validate(raw))["accounts_per_month"] == 200  # table row cap


def test_unknown_placeholders_and_conditions_are_caught() -> None:
    raw = mutated()
    raw["tables"][1]["columns"][-1]["prompt"] += " Mention {{favourite_colour}}."
    assert "prompt uses unknown favourite_colour" in problems(raw)
    raw = mutated()
    raw["tables"][0]["columns"][-1]["run_if"] = "ghost = A"
    assert "run_if names unknown column" in problems(raw)


def test_parent_table_columns_are_visible_to_children() -> None:
    raw = mutated()  # opening_line uses why_now from the Accounts table
    assert "{{why_now}}" in raw["tables"][1]["columns"][-1]["prompt"]
    ClaySpec.model_validate(raw)
    raw["tables"][1]["source"]["from_table"] = "Nope"
    assert "unknown source table Nope" in problems(raw)


def test_import_columns_must_match_tier_a_csv() -> None:
    raw = mutated()
    raw["tables"][0]["columns"].pop(3)  # drop "score"
    assert "must equal tier_a.csv columns" in problems(raw)


def test_shape_rules() -> None:
    raw = mutated()
    del raw["tables"][0]["columns"][-1]["prompt"]
    assert "claygent columns need a prompt" in problems(raw)
    raw = mutated()
    raw["tables"][1]["columns"][4]["providers"] = []
    assert "a waterfall needs providers" in problems(raw)
    raw = mutated()
    raw["tables"][1]["columns"].append(copy.deepcopy(raw["tables"][1]["columns"][0]))
    assert "duplicate column names" in problems(raw)
    raw = mutated()
    raw["tables"].append(copy.deepcopy(raw["tables"][1]))
    assert "table names must be unique" in problems(raw)


def test_guide_carries_budget_prompts_and_policy() -> None:
    guide = render_guide(load_clay_spec(SPEC_PATH), "clay/table_spec.yaml")
    for fragment in (
        "| Credits per Tier-A account | 17 |",
        "| Tier-A accounts per month on this plan | 5 |",
        "Create a table and import `data/out/tier_a.csv`",
        "**Find people** on `SignalScout Accounts`, matching on `domain`, at most 2 per company",
        "- Head of Revenue Operations",
        "| `work_email` | waterfall | title is not empty | 7 |",
        "**`work_email` waterfall** (stop at first result): email provider 1 (2) -> "
        "email provider 2 (2) -> email provider 3 (3)",
        "Output fields: `problems` (list of strings)",
        "## Contact policy",
    ):
        assert fragment in guide, fragment
