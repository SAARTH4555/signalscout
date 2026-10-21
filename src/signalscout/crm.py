"""Which CRM a company runs: from its own job postings first, its website's scripts second.

Two kinds of evidence, never confused:

* **Job postings** that name Salesforce or HubSpot (``roles.stack_from_jobs``). A company asking
  for "Salesforce admin experience" runs Salesforce. High confidence.
* **Website scripts**: a HubSpot tracking or forms script, Pardot (Salesforce's marketing tool),
  Marketo. These are marketing tools, not the CRM itself. At Series A-C a HubSpot script usually
  means HubSpot CRM and Pardot means Salesforce, so they give a medium-confidence guess; Marketo
  alone (it syncs with several CRMs) gives a low one.

The page scan is static HTML: scripts injected by Google Tag Manager are invisible in it, so when
a GTM container id is on the page, the container itself is fetched and scanned too. Signatures
are this project's own short regex list; the GPL-licensed webappanalyzer data was the reference,
not copied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from signalscout.fetch import Fetcher, FetchError
from signalscout.roles import StackEvidence

Crm = Literal["salesforce", "hubspot", "both"]
Confidence = Literal["high", "medium", "low", "none"]

SIGNATURES: dict[str, tuple[re.Pattern[str], ...]] = {
    "hubspot": (
        re.compile(r"js\.hs-scripts\.com"),
        re.compile(r"js\.hsforms\.(net|com)"),
        re.compile(r"js\.hs-analytics\.net"),
        re.compile(r"js\.usemessages\.com"),
        re.compile(r"<!--\s*Start of (Async )?HubSpot", re.IGNORECASE),
    ),
    "pardot": (
        re.compile(r"(pi|go)\.pardot\.com"),
        re.compile(r"\bpiAId\b"),
    ),
    "marketo": (
        re.compile(r"munchkin\.marketo\.net"),
        re.compile(r"\bMunchkin\.init\b"),
        re.compile(r"marketo\.(com|net)/js/forms"),
    ),
    "salesforce": (
        re.compile(r"service\.force\.com"),
        re.compile(r"\bembedded_svc\b"),
        re.compile(r"\.my\.salesforce\.com"),
        re.compile(r"\.exacttarget\.com"),
    ),
    "intercom": (re.compile(r"widget\.intercom\.io"), re.compile(r"js\.intercomcdn\.com")),
    "segment": (re.compile(r"cdn\.segment\.com/analytics\.js"),),
    "drift": (re.compile(r"js\.driftt\.com"),),
}
DISPLAY = {
    "hubspot": "HubSpot",
    "pardot": "Pardot",
    "marketo": "Marketo",
    "salesforce": "Salesforce",
    "intercom": "Intercom",
    "segment": "Segment",
    "drift": "Drift",
}
GTM_ID = re.compile(r"googletagmanager\.com/gtm\.js\?id=(GTM-[A-Z0-9]+)")
EXTRA_PAGES = ("/demo", "/contact")


@dataclass(frozen=True)
class SiteScan:
    tools: tuple[str, ...]
    pages: tuple[str, ...]  # URLs actually read
    blocked: int  # pages robots.txt kept us out of
    gtm_container: str | None
    failed: int = 0  # pages that could not be fetched at all


def detect(text: str) -> set[str]:
    return {tool for tool, patterns in SIGNATURES.items() if any(p.search(text) for p in patterns)}


def scan_site(fetcher: Fetcher, domain: str) -> SiteScan:
    tools: set[str] = set()
    pages: list[str] = []
    blocked = failed = 0
    container: str | None = None
    urls = [f"https://{domain}/"]
    for path in EXTRA_PAGES:
        urls.append(f"https://{domain}{path}")
    read_extra = False
    for url in urls:
        if url != urls[0] and read_extra:
            break  # one of /demo or /contact is enough: that is where the forms are
        try:
            page = fetcher.get(url)
        except FetchError:
            failed += 1
            continue
        if page.blocked:
            blocked += 1
            continue
        if not page.ok:
            continue
        pages.append(url)
        read_extra = url != urls[0]
        tools |= detect(page.text)
        found = GTM_ID.search(page.text)
        if found and container is None:
            container = found.group(1)
    if container is not None:
        try:
            gtm = fetcher.get(f"https://www.googletagmanager.com/gtm.js?id={container}")
            if gtm.ok:
                tools |= detect(gtm.text)
        except FetchError:
            failed += 1
    return SiteScan(tuple(sorted(tools)), tuple(pages), blocked, container, failed)


@dataclass(frozen=True)
class CrmGuess:
    crm: Crm | None
    confidence: Confidence
    evidence: tuple[str, ...]


def guess_crm(jobs: StackEvidence | None, site: SiteScan | None) -> CrmGuess:
    evidence: list[str] = []
    site_tools = set(site.tools) if site else set()
    if jobs is not None and jobs.crm is not None:
        for tool in ("salesforce", "hubspot"):
            n = jobs.tools.get(tool, 0)
            if n:
                postings = "1 job posting names" if n == 1 else f"{n} job postings name"
                evidence.append(f"{postings} {DISPLAY[tool]}")
        crm_tools = sorted(site_tools & {"hubspot", "pardot", "marketo", "salesforce"})
        if crm_tools:
            evidence.append("site runs " + ", ".join(DISPLAY[t] for t in crm_tools))
        return CrmGuess(jobs.crm, "high", tuple(evidence))

    hubspot = "hubspot" in site_tools
    salesforce = bool(site_tools & {"pardot", "salesforce"})
    if hubspot and salesforce:
        return CrmGuess("both", "low", ("site runs HubSpot and Salesforce tools",))
    if hubspot:
        return CrmGuess("hubspot", "medium", ("site runs HubSpot scripts or forms",))
    if salesforce:
        return CrmGuess("salesforce", "medium", ("site runs Pardot / Salesforce scripts",))
    if "marketo" in site_tools:
        return CrmGuess("salesforce", "low", ("site runs Marketo, which usually feeds Salesforce",))
    return CrmGuess(None, "none", ())
