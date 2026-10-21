from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from signalscout.accounts import Account
from signalscout.crm import CrmGuess
from signalscout.funding import Funding
from signalscout.jobs.ats import Job
from signalscout.roles import RoleMatch, classify_title
from signalscout.score import (
    AccountSignals,
    ScoringConfig,
    decay,
    load_scoring,
    score_account,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_scoring(ROOT / "config" / "scoring.yaml")
AS_OF = date(2026, 10, 15)
ACME = Account(
    "acme.io",
    "Acme",
    "acme.io",
    ("yc",),
    team_size=120,
    location="San Francisco, CA, USA",
    industries=("B2B",),
)


def role(title: str, days_ago: int | None = 10) -> tuple[RoleMatch, Job]:
    match = classify_title(title)
    assert match is not None
    posted = (
        None
        if days_ago is None
        else datetime.combine(AS_OF - timedelta(days=days_ago), datetime.min.time(), UTC)
    )
    job = Job("ashby", "acme", title, "https://x", posted, "publishedAt", "", None, "", "")
    return match, job


def funding(days_ago: int, amount: float | None = 30e6) -> Funding:
    day = AS_OF - timedelta(days=days_ago)
    return Funding("1", "Acme, Inc.", "D", day, day, amount, amount, "Other Technology", "CA")


def signals(**kw: object) -> AccountSignals:
    base = AccountSignals(ACME, has_board=True)
    return replace(base, **kw)  # type: ignore[arg-type]


def test_decay() -> None:
    assert decay(0, 45) == 1.0
    assert decay(45, 45) == 0.5
    assert decay(-3, 45) == 1.0


def test_fit_only_company() -> None:
    result = score_account(signals(), CONFIG, AS_OF)
    assert result.fit == 25 and result.intent == 0 and result.tier == "C"
    assert result.reasons == ("120 people, inside the 50-500 band",)


def test_fresh_revops_leader_after_a_raise_is_tier_a() -> None:
    result = score_account(
        signals(
            gtm_roles=(role("Head of Revenue Operations", 0), role("Salesforce Administrator", 20)),
            funding=funding(30),
            crm=CrmGuess("salesforce", "high", ("2 job postings name Salesforce",)),
        ),
        CONFIG,
        AS_OF,
    )
    assert result.tier == "A"
    assert result.components == {
        "size": 15,
        "us": 5,
        "b2b": 5,
        "crm": 5,
        "role": 30,
        "leader": 5,
        "multiple_roles": 10,
        "funding": 17,
        "stacked": 10,
    }
    assert result.score == 100  # capped
    assert "Hiring: Head of Revenue Operations (Revenue Operations, posted 0 days ago)" in (
        result.reasons
    )
    assert "Runs Salesforce (high confidence: 2 job postings name Salesforce)" in result.reasons
    assert "Raised $30.0M 30 days ago (SEC Form D; stage Series A/B (guess))" in result.reasons
    assert "Hiring for GTM ops right after a raise" in result.reasons


def test_role_value_halves_every_45_days() -> None:
    fresh = score_account(signals(gtm_roles=(role("RevOps Manager", 0),)), CONFIG, AS_OF)
    old = score_account(signals(gtm_roles=(role("RevOps Manager", 45),)), CONFIG, AS_OF)
    assert fresh.components["role"] == 30 and old.components["role"] == 15
    undated = score_account(signals(gtm_roles=(role("RevOps Manager", None),)), CONFIG, AS_OF)
    assert undated.components["role"] == round(30 * decay(30, 45))
    assert "date not given" in undated.reasons[1]


def test_best_role_wins_not_the_first() -> None:
    result = score_account(
        signals(gtm_roles=(role("Marketing Ops Analyst", 0), role("GTM Engineer", 0))),
        CONFIG,
        AS_OF,
    )
    assert result.components["role"] == 30 and "GTM Engineer" in result.reasons[1]


def test_funding_only_tops_out_at_tier_b() -> None:
    rich = Account(
        "acme.io", "Acme", "acme.io", team_size=120, location="NY, USA", industries=("B2B",)
    )
    config = ScoringConfig.model_validate({**CONFIG.model_dump(), "tiers": {"a": 40, "b": 20}})
    result = score_account(
        signals(account=rich, funding=funding(1), crm=CrmGuess("hubspot", "medium", ("x",))),
        config,
        AS_OF,
    )
    assert result.score >= 40 and result.tier == "B"
    assert "No GTM-ops opening on the board, so held at Tier B" in result.reasons
    assert "Runs HubSpot (medium confidence: x)" in result.reasons


def test_stale_funding_is_ignored() -> None:
    result = score_account(signals(funding=funding(400)), CONFIG, AS_OF)
    assert "funding" not in result.components
    undisclosed = score_account(signals(funding=funding(10, None)), CONFIG, AS_OF)
    assert any("an undisclosed sum" in r for r in undisclosed.reasons)


def test_outside_the_band_caps_at_tier_c() -> None:
    big = replace(ACME, team_size=2400)
    result = score_account(
        signals(
            account=big,
            gtm_roles=(role("VP Revenue Operations", 0), role("GTM Engineer", 0)),
            funding=funding(10),
        ),
        CONFIG,
        AS_OF,
    )
    assert result.score >= CONFIG.tiers.b and result.tier == "C"
    assert "2,400 people is outside the 50-500 band, so capped at Tier C" in result.reasons
    tiny = score_account(signals(account=replace(ACME, team_size=8)), CONFIG, AS_OF)
    assert tiny.tier == "C" and not any("capped" in r for r in tiny.reasons)


def test_unknown_size_and_no_board() -> None:
    unknown = Account("x.io", "X", "x.io")
    result = score_account(AccountSignals(unknown), CONFIG, AS_OF)
    assert result.components == {"size": 5}
    assert result.reasons == ("No public job board found",)


def test_both_crms_and_config_validation() -> None:
    result = score_account(signals(crm=CrmGuess("both", "low", ("y",))), CONFIG, AS_OF)
    assert "Runs Salesforce and HubSpot (low confidence: y)" in result.reasons
    with pytest.raises(ValidationError, match="team_min"):
        ScoringConfig.model_validate(
            {**CONFIG.model_dump(), "fit": {**CONFIG.fit.model_dump(), "team_min": 900}}
        )
    with pytest.raises(ValidationError, match="b < a"):
        ScoringConfig.model_validate({**CONFIG.model_dump(), "tiers": {"a": 30, "b": 40}})
