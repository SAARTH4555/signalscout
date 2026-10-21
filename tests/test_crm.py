from __future__ import annotations

from pathlib import Path

from signalscout.crm import CrmGuess, SiteScan, detect, guess_crm, scan_site
from signalscout.fetch import FakeFetcher, FetchError, Response
from signalscout.roles import StackEvidence

SITES = Path(__file__).parent / "fixtures" / "sites"


def page(name: str) -> str:
    return (SITES / name).read_text()


def test_detect_signatures() -> None:
    assert detect(page("hubspot_home.html")) == {"hubspot", "segment"}
    assert detect(page("pardot_contact.html")) == {"pardot"}
    assert detect(page("gtm_container.js")) == {"marketo"}
    assert detect('<script src="https://widget.intercom.io/widget/x"></script>') == {"intercom"}
    assert detect("<html>plain</html>") == set()


def test_scan_reads_home_and_one_form_page() -> None:
    fake = FakeFetcher(
        {
            "https://orbitstack.example/": page("hubspot_home.html"),
            "https://orbitstack.example/demo": page("pardot_contact.html"),
            "https://orbitstack.example/contact": "<html></html>",
        }
    )
    scan = scan_site(fake, "orbitstack.example")
    assert scan.tools == ("hubspot", "pardot", "segment")
    assert scan.pages == ("https://orbitstack.example/", "https://orbitstack.example/demo")
    assert "https://orbitstack.example/contact" not in fake.calls


def test_scan_follows_the_tag_manager_container() -> None:
    fake = FakeFetcher(
        {
            "https://harborview.example/": page("gtm_home.html"),
            "https://www.googletagmanager.com/gtm.js?id=GTM-AB12CD": page("gtm_container.js"),
        }
    )
    scan = scan_site(fake, "harborview.example")
    assert scan.gtm_container == "GTM-AB12CD" and scan.tools == ("marketo",)


def test_scan_counts_robots_blocks_and_survives_errors() -> None:
    class Site(FakeFetcher):
        def get(self, url: str) -> Response:
            self.calls.append(url)
            if url.endswith("/demo"):
                return Response(url, 0, "blocked by robots.txt")
            if url.endswith("/contact") or "googletagmanager" in url:
                raise FetchError("down")
            return Response(url, 200, page("gtm_home.html"))

    scan = scan_site(Site(), "acme.io")
    assert scan.blocked == 1 and scan.pages == ("https://acme.io/",) and scan.tools == ()
    assert scan.failed == 2  # /contact and the tag-manager container


def site(*tools: str) -> SiteScan:
    return SiteScan(tuple(tools), ("https://x/",), 0, None)


def test_job_postings_beat_website_scripts() -> None:
    jobs = StackEvidence({"salesforce": 3, "hubspot": 1}, "salesforce")
    guess = guess_crm(jobs, site("hubspot"))
    assert guess == CrmGuess(
        "salesforce",
        "high",
        ("3 job postings name Salesforce", "1 job posting names HubSpot", "site runs HubSpot"),
    )


def test_website_only_guesses() -> None:
    assert guess_crm(None, site("hubspot")).confidence == "medium"
    assert guess_crm(StackEvidence({}, None), site("pardot")).crm == "salesforce"
    assert guess_crm(None, site("marketo")) == CrmGuess(
        "salesforce", "low", ("site runs Marketo, which usually feeds Salesforce",)
    )
    assert guess_crm(None, site("hubspot", "salesforce")).crm == "both"
    assert guess_crm(None, site("intercom")) == CrmGuess(None, "none", ())
    assert guess_crm(None, None).confidence == "none"
