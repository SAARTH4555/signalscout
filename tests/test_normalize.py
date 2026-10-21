"""Contract tests: these normalizers are copied from PipelineOS and must stay identical.

The expected values below are the same golden cases PipelineOS's own tests assert, so if either
copy drifts, one of the two suites fails.
"""

from __future__ import annotations

import pytest

from signalscout.normalize import (
    clean_company_name,
    company_name_key,
    domain_label,
    normalize_name,
    registrable_domain,
    strip_legal_form,
)


@pytest.mark.parametrize(
    ("raw", "domain"),
    [
        ("https://www.acme.io/pricing", "acme.io"),
        ("http://acme.io", "acme.io"),
        ("www.acme.io", "acme.io"),
        ("ACME.IO", "acme.io"),
        ("shop.foo.co.uk", "foo.co.uk"),
        ("", None),
        ("   ", None),
        ("localhost", None),
    ],
)
def test_registrable_domain_matches_pipelineos(raw: str, domain: str | None) -> None:
    assert registrable_domain(raw) == domain


@pytest.mark.parametrize("raw", ["Acme Inc.", "ACME, Inc", "Acme LLC", "acme", "Acme Corp"])
def test_company_name_key_matches_pipelineos(raw: str) -> None:
    assert company_name_key(raw) == "acme"


def test_names_match_pipelineos() -> None:
    assert normalize_name("  JOHN   ") == "John"
    assert normalize_name("McKenzie") == "McKenzie"
    assert clean_company_name("ACME, Inc") == "Acme"
    assert clean_company_name("  DataDog   LLC ") == "DataDog"


def test_signalscout_helpers() -> None:
    assert domain_label("ramp.com") == "ramp"
    assert domain_label("foo.co.uk") == "foo"
    assert strip_legal_form("Ramp Business Corporation") == "Ramp Business"
    assert strip_legal_form("Acme Holdings, Inc.") == "Acme"
    assert strip_legal_form("Coinbase") == "Coinbase"  # "co" only as a separate word
    assert strip_legal_form("  Widget   Co. ") == "Widget"
