from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from signalscout.roles import classify_title, stack_from_jobs, tool_mentions

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("title", "kind", "seniority"),
    [
        ("Revenue Operations Manager", "revops", "manager"),
        ("Head of RevOps", "revops", "leader"),
        ("GTM Engineer", "gtm_engineer", "ic"),
        ("Business Systems Analyst, Go-to-Market", "gtm_engineer", "ic"),
        ("Business Systems Analyst", "crm_admin", "ic"),
        ("Salesforce Administrator", "crm_admin", "ic"),
        ("Sales Ops / Deal Desk Lead", "sales_ops", "manager"),
        ("Marketing Automation Manager", "marketing_ops", "manager"),
        ("Customer Success Operations Lead", "cs_ops", "manager"),
        ("VP Sales", "sales_leader", "leader"),
        ("Chief Revenue Officer", "sales_leader", "leader"),
    ],
)
def test_gtm_ops_titles(title: str, kind: str, seniority: str) -> None:
    match = classify_title(title)
    assert match is not None and (match.kind, match.seniority) == (kind, seniority)


@pytest.mark.parametrize(
    "title",
    [
        "Account Executive",
        "SDR, Outbound",
        "DevOps Engineer",
        "SecOps Analyst",
        "People Operations Partner",
        "Revenue Accountant",
        "Revenue Cycle Manager",
        "Recruiter, Sales",
        "CRO Specialist",
        "Sales Operations Intern",
        "Operations Manager",
    ],
)
def test_not_gtm_ops(title: str) -> None:
    assert classify_title(title) is None


def test_tool_mentions_need_context_for_common_words() -> None:
    assert tool_mentions("We run Salesforce and HubSpot.") == {"salesforce", "hubspot"}
    assert tool_mentions("Our stack: Salesforce, Outreach, Gong and Clay.") == {
        "salesforce",
        "outreach",
        "gong",
        "clay",
    }
    assert tool_mentions("Lead community outreach events and clay pottery classes.") == set()
    assert tool_mentions("Experience with Outreach and Gong.") == {"outreach", "gong"}
    assert tool_mentions("Outreach.io power user") == {"outreach"}
    assert tool_mentions("Hub Spot certified, uses ZoomInfo") == {"hubspot", "zoominfo"}
    assert tool_mentions("Apollo mission history buff") == set()


def test_stack_from_jobs_picks_the_crm() -> None:
    assert stack_from_jobs([]).crm is None
    sf = stack_from_jobs(["Salesforce admin", "Salesforce CPQ", "We use SFDC", "HubSpot forms"])
    assert sf.crm == "salesforce" and sf.tools == {"hubspot": 1, "salesforce": 3}
    # within 2x of each other: both are in real use
    assert stack_from_jobs(["Salesforce", "Salesforce", "HubSpot"]).crm == "both"
    assert stack_from_jobs(["HubSpot", "HubSpot workflows"]).crm == "hubspot"
    assert stack_from_jobs(["Salesforce", "HubSpot"]).crm == "both"


def test_eval_script_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "roles.json"
    monkeypatch.setattr(sys, "argv", ["eval_roles", "--out", str(out)])
    runpy.run_path(str(ROOT / "scripts" / "eval_roles.py"), run_name="__main__")
    assert '"holdout"' in out.read_text()
