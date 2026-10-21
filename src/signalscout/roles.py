"""Which open roles mean "this company is building GTM operations", and which tools they name.

``classify_title`` maps a job title to a GTM-ops role kind and a seniority, or ``None``. Patterns
are explicit phrases, not the substring "ops", so DevOps, SecOps, People Ops or Revenue
Accounting never match. A posting for a sales leader (CRO, VP Sales) counts too, as a weaker
signal: a new revenue leader usually rebuilds the GTM stack within a year.

``tool_mentions`` reads job descriptions for the GTM tools they name: TheirStack's trick of
learning a company's stack from its own hiring. Tools whose names are ordinary words (Outreach,
Gong, Clay, Apollo) only count when another tool is named close by, so "community outreach" is
not a sales-engagement platform.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

RoleKind = Literal[
    "revops", "sales_ops", "marketing_ops", "gtm_engineer", "crm_admin", "cs_ops", "sales_leader"
]
Seniority = Literal["leader", "manager", "ic"]
Crm = Literal["salesforce", "hubspot", "both"]

# Checked in order; the first kind whose pattern matches wins.
ROLE_PATTERNS: tuple[tuple[RoleKind, re.Pattern[str]], ...] = (
    (
        "gtm_engineer",
        re.compile(
            r"\b(gtm|go[- ]to[- ]market)\s+"
            r"(engineer|engineering|systems|operations|ops|automation)\b"
            r"|\bbusiness systems\b.*\b(gtm|go[- ]to[- ]market)\b"
        ),
    ),
    (
        "crm_admin",
        re.compile(
            r"\b(salesforce|sfdc|hubspot|crm)\s+(admin|administrator|developer|architect|manager|"
            r"specialist|analyst|engineer|lead|consultant)\b|\bbusiness systems (analyst|manager|"
            r"engineer|administrator)\b"
        ),
    ),
    ("revops", re.compile(r"\b(revenue operations|revenue ops|revops|rev ops)\b")),
    (
        "sales_ops",
        re.compile(
            r"\b(sales operations|sales ops|salesops|sales systems|"
            r"sales strategy (and|&) operations|sales enablement operations|deal desk|"
            r"(sales |incentive )?comp(ensation)? (operations|ops))\b"
        ),
    ),
    (
        "marketing_ops",
        re.compile(
            r"\b(marketing operations|marketing ops|mops|marketing automation|marketing technology|"
            r"martech)\b"
        ),
    ),
    (
        "cs_ops",
        re.compile(r"\b(customer success operations|cs operations|cs ops|customer operations)\b"),
    ),
    (
        "sales_leader",
        re.compile(
            r"\b(chief revenue officer|(vp|vice president|svp|head),? (of )?(global )?(sales|"
            r"revenue))\b(?!\s+(enablement|development))"
        ),
    ),
)
EXCLUDE = re.compile(
    r"\b(account executive|sales development|sdr|bdr|recruit\w*|talent|people operations|"
    r"devops|secops|security operations|it operations|revenue (accounting|accountant|cycle|"
    r"management)|tax|payroll|intern(ship)?)\b"
)
# Bare "CRO" is left out: in growth teams it means conversion-rate optimisation.
LEADER = re.compile(r"\b(vp|vice president|svp|head|director|chief)\b")
MANAGER = re.compile(r"\b(manager|lead|principal|senior manager)\b")


@dataclass(frozen=True)
class RoleMatch:
    kind: RoleKind
    seniority: Seniority
    title: str


def classify_title(title: str) -> RoleMatch | None:
    text = " ".join(title.lower().replace("/", " ").split())
    if EXCLUDE.search(text):
        return None
    for kind, pattern in ROLE_PATTERNS:
        if pattern.search(text):
            seniority: Seniority = (
                "leader" if LEADER.search(text) else "manager" if MANAGER.search(text) else "ic"
            )
            if kind == "sales_leader":
                seniority = "leader"
            return RoleMatch(kind, seniority, title.strip())
    return None


# -- tools named in job descriptions -----------------------------------------------------------

DISTINCT_TOOLS: dict[str, re.Pattern[str]] = {
    "salesforce": re.compile(r"\b(salesforce|sfdc|sales cloud|salesforce cpq)\b", re.IGNORECASE),
    "hubspot": re.compile(r"\bhub\s?spot\b", re.IGNORECASE),
    "pardot": re.compile(r"\bpardot\b", re.IGNORECASE),
    "marketo": re.compile(r"\bmarketo\b", re.IGNORECASE),
    "salesloft": re.compile(r"\bsales\s?loft\b", re.IGNORECASE),
    "zoominfo": re.compile(r"\bzoom\s?info\b", re.IGNORECASE),
    "dynamics": re.compile(r"\b(microsoft dynamics|dynamics 365)\b", re.IGNORECASE),
    "pipedrive": re.compile(r"\bpipedrive\b", re.IGNORECASE),
}
# Ordinary words: capitalised, and only near another tool.
CONTEXT_TOOLS: dict[str, re.Pattern[str]] = {
    "outreach": re.compile(r"\bOutreach(\.io)?\b"),
    "gong": re.compile(r"\bGong(\.io)?\b"),
    "clay": re.compile(r"\bClay\b"),
    "apollo": re.compile(r"\bApollo(\.io)?\b"),
}
CONTEXT_WINDOW = 60


def tool_mentions(description: str) -> set[str]:
    found = {name for name, pattern in DISTINCT_TOOLS.items() if pattern.search(description)}
    anchors = [m.start() for p in DISTINCT_TOOLS.values() for m in p.finditer(description)]
    for name, pattern in CONTEXT_TOOLS.items():
        for match in pattern.finditer(description):
            near_anchor = any(abs(match.start() - a) <= CONTEXT_WINDOW for a in anchors)
            near_context_tool = any(
                other != name
                and any(
                    abs(match.start() - m.start()) <= CONTEXT_WINDOW
                    for m in other_pattern.finditer(description)
                )
                for other, other_pattern in CONTEXT_TOOLS.items()
            )
            if near_anchor or near_context_tool or match.group(0).endswith(".io"):
                found.add(name)
                break
    return found


@dataclass(frozen=True)
class StackEvidence:
    tools: dict[str, int]  # tool -> number of postings that name it
    crm: Crm | None


def stack_from_jobs(descriptions: Iterable[str]) -> StackEvidence:
    """Count postings per tool; the CRM is whichever of Salesforce / HubSpot more postings name."""
    counts: Counter[str] = Counter()
    for description in descriptions:
        counts.update(tool_mentions(description))
    sf, hs = counts["salesforce"], counts["hubspot"]
    crm: Crm | None
    if sf == hs == 0:
        crm = None
    elif sf and hs and min(sf, hs) * 2 >= max(sf, hs):
        crm = "both"  # e.g. mid-migration, or one team on each
    else:
        crm = "salesforce" if sf > hs else "hubspot"
    return StackEvidence(dict(sorted(counts.items())), crm)
