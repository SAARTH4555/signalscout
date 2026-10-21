"""Turn an account's signals into a score, a tier and the reasons for both.

``score_account`` is pure: same signals and config, same result. Fit (size band, US, B2B, CRM
known) says whether a company is the kind that buys GTM-ops help; intent (an open GTM-ops role,
decaying with its age; a recent raise, decaying with its age; both at once) says whether it needs
it now. Two rules keep tiers honest:

* **Tier A needs an opening.** Funding and fit alone top out at Tier B: without a GTM-ops role on
  the board there is no evidence the company is building the function now.
* **Outside the size band caps at Tier C**, whatever else fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from signalscout.accounts import Account
from signalscout.crm import CrmGuess
from signalscout.funding import Funding
from signalscout.jobs.ats import Job
from signalscout.roles import RoleKind, RoleMatch

Tier = Literal["A", "B", "C"]

ROLE_LABELS: dict[str, str] = {
    "revops": "Revenue Operations",
    "gtm_engineer": "GTM engineering",
    "crm_admin": "CRM admin",
    "sales_ops": "Sales Operations",
    "sales_leader": "sales leadership",
    "marketing_ops": "Marketing Operations",
    "cs_ops": "CS Operations",
}


CRM_LABELS = {"salesforce": "Salesforce", "hubspot": "HubSpot", "both": "Salesforce and HubSpot"}


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FitConfig(_Config):
    team_min: int = Field(ge=1)
    team_max: int = Field(ge=1)
    in_band_points: int = Field(ge=0)
    unknown_size_points: int = Field(ge=0)
    us_points: int = Field(ge=0)
    b2b_points: int = Field(ge=0)
    crm_known_points: int = Field(ge=0)

    @model_validator(mode="after")
    def _band(self) -> Self:
        if self.team_min > self.team_max:
            raise ValueError("team_min must not exceed team_max")
        return self


class IntentConfig(_Config):
    role_points: dict[RoleKind, int]
    role_half_life_days: float = Field(gt=0)
    undated_role_age_days: int = Field(ge=0)
    leader_bonus: int = Field(ge=0)
    multiple_roles_bonus: int = Field(ge=0)
    funding_points: int = Field(ge=0)
    funding_window_days: int = Field(ge=1)
    funding_half_life_days: float = Field(gt=0)
    stacked_bonus: int = Field(ge=0)


class TierConfig(_Config):
    a: int
    b: int

    @model_validator(mode="after")
    def _order(self) -> Self:
        if not 0 < self.b < self.a <= 100:
            raise ValueError("need 0 < b < a <= 100")
        return self


class ScoringConfig(_Config):
    fit: FitConfig
    intent: IntentConfig
    tiers: TierConfig


def load_scoring(path: Path) -> ScoringConfig:
    return ScoringConfig.model_validate(yaml.safe_load(path.read_text()))


@dataclass(frozen=True)
class AccountSignals:
    account: Account
    gtm_roles: tuple[tuple[RoleMatch, Job], ...] = ()
    open_jobs: int = 0
    has_board: bool = False
    funding: Funding | None = None
    crm: CrmGuess | None = None


@dataclass(frozen=True)
class ScoredAccount:
    signals: AccountSignals
    score: int
    tier: Tier
    fit: int
    intent: int
    reasons: tuple[str, ...]
    components: dict[str, int] = field(default_factory=dict)


def decay(age_days: float, half_life_days: float) -> float:
    return float(0.5 ** (max(age_days, 0.0) / half_life_days))


def _age_days(when: datetime | date | None, as_of: date) -> int | None:
    if when is None:
        return None
    day = when.date() if isinstance(when, datetime) else when
    return (as_of - day).days


def _is_us(account: Account) -> bool:
    return "USA" in account.location or "United States" in account.location


def score_account(signals: AccountSignals, config: ScoringConfig, as_of: date) -> ScoredAccount:
    account, fit_cfg, intent_cfg = signals.account, config.fit, config.intent
    reasons: list[str] = []
    parts: dict[str, int] = {}

    # -- fit -------------------------------------------------------------------------------
    size = account.team_size
    out_of_band = size is not None and not fit_cfg.team_min <= size <= fit_cfg.team_max
    if size is None:
        parts["size"] = fit_cfg.unknown_size_points
    elif not out_of_band:
        parts["size"] = fit_cfg.in_band_points
        reasons.append(f"{size:,} people, inside the {fit_cfg.team_min}-{fit_cfg.team_max} band")
    if _is_us(account):
        parts["us"] = fit_cfg.us_points
    if "B2B" in account.industries:
        parts["b2b"] = fit_cfg.b2b_points
    if signals.crm is not None and signals.crm.crm is not None:
        parts["crm"] = fit_cfg.crm_known_points
        crm = CRM_LABELS[signals.crm.crm]
        reasons.append(
            f"Runs {crm} ({signals.crm.confidence} confidence: {'; '.join(signals.crm.evidence)})"
        )

    # -- intent: roles ---------------------------------------------------------------------
    role_points = 0.0
    best: tuple[RoleMatch, Job] | None = None
    for match, job in signals.gtm_roles:
        age = _age_days(job.posted_at, as_of)
        effective_age = intent_cfg.undated_role_age_days if age is None else age
        points = intent_cfg.role_points.get(match.kind, 0) * decay(
            effective_age, intent_cfg.role_half_life_days
        )
        if points > role_points:
            role_points, best = points, (match, job)
    if best is not None:
        match, job = best
        age = _age_days(job.posted_at, as_of)
        when = "date not given" if age is None else f"posted {age} days ago"
        reasons.append(f"Hiring: {job.title} ({ROLE_LABELS[match.kind]}, {when})")
        parts["role"] = round(role_points)
        if match.seniority == "leader":
            parts["leader"] = intent_cfg.leader_bonus
            reasons.append("The opening leads the function, so it is being built now")
    if len(signals.gtm_roles) >= 2:
        parts["multiple_roles"] = intent_cfg.multiple_roles_bonus
        reasons.append(f"{len(signals.gtm_roles)} GTM-ops roles open at once")

    # -- intent: funding -------------------------------------------------------------------
    funding = signals.funding
    if funding is not None:
        age = (as_of - funding.round_date).days
        if 0 <= age <= intent_cfg.funding_window_days:
            parts["funding"] = round(
                intent_cfg.funding_points * decay(age, intent_cfg.funding_half_life_days)
            )
            amount = (
                f"${funding.amount_sold / 1e6:,.1f}M"
                if funding.amount_sold
                else "an undisclosed sum"
            )
            reasons.append(
                f"Raised {amount} {age} days ago (SEC Form D; stage {funding.stage_guess})"
            )
    if parts.get("role", 0) > 0 and parts.get("funding", 0) > 0:
        parts["stacked"] = intent_cfg.stacked_bonus
        reasons.append("Hiring for GTM ops right after a raise")

    fit = sum(parts.get(k, 0) for k in ("size", "us", "b2b", "crm"))
    intent = sum(v for k, v in parts.items() if k not in ("size", "us", "b2b", "crm"))
    total = min(100, fit + intent)

    tier: Tier
    if total >= config.tiers.a and best is not None:
        tier = "A"
    elif total >= config.tiers.b:
        tier = "B"
    else:
        tier = "C"
    if total >= config.tiers.a and best is None:
        reasons.append("No GTM-ops opening on the board, so held at Tier B")
    if out_of_band:
        assert size is not None
        if tier != "C":
            reasons.append(
                f"{size:,} people is outside the {fit_cfg.team_min}-{fit_cfg.team_max} band, "
                "so capped at Tier C"
            )
        tier = "C"
    if not signals.has_board:
        reasons.append("No public job board found")
    return ScoredAccount(signals, total, tier, fit, intent, tuple(reasons), parts)
