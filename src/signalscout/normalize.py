"""Company-identity normalizers.

``registrable_domain``, ``company_name_key``, ``clean_company_name`` and ``normalize_name`` are
copied from PipelineOS (``pipelineos/data/normalize.py``) rather than imported: PipelineOS is not
a published package, and a path dependency would break ``uv sync --locked`` in CI. Both repos
must agree on what a company key is, so ``tests/test_normalize.py`` pins the copies to the same
golden cases PipelineOS tests. Change them in both places or not at all.
"""

from __future__ import annotations

import re

import tldextract

# -- copied from PipelineOS: keep identical ----------------------------------------------------

_COMPANY_SUFFIX_RE = re.compile(
    r"[,\s]+(inc|inc\.|llc|l\.l\.c\.|ltd|ltd\.|corp|corp\.|co|co\.|gmbh|plc)\.?$", re.IGNORECASE
)
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def registrable_domain(raw: str) -> str | None:
    """``https://www.acme.io/pricing`` -> ``acme.io``; ``None`` for anything without a suffix."""
    value = raw.strip().lower()
    if not value:
        return None
    domain = _EXTRACT(value).top_domain_under_public_suffix
    return domain or None


def normalize_name(raw: str) -> str:
    """Collapse whitespace; fix ALL CAPS / all lower, but keep deliberate mixed case (McKenzie)."""
    name = " ".join(raw.split())
    if name.isupper() or name.islower():
        return name.title()
    return name


def company_name_key(raw: str) -> str:
    """``ACME, Inc`` / ``Acme LLC`` / ``acme`` -> ``acme``."""
    name = _COMPANY_SUFFIX_RE.sub("", raw.strip())
    return re.sub(r"[^a-z0-9]", "", name.lower())


def clean_company_name(raw: str) -> str:
    name = _COMPANY_SUFFIX_RE.sub("", " ".join(raw.split()))
    return normalize_name(name)


# -- SignalScout only --------------------------------------------------------------------------

# Longer legal forms too: EDGAR's conformed names use "Corp", but people write "Corporation".
_LEGAL_FORM_RE = re.compile(
    r"[,\s]+(incorporated|inc|corporation|corp|company|co|limited|ltd|llc|l\.l\.c|plc|pbc|"
    r"gmbh|holdings)\.?$",
    re.IGNORECASE,
)


def domain_label(domain: str) -> str:
    """Registered name without its suffix: ``ramp.com`` -> ``ramp``, ``foo.co.uk`` -> ``foo``."""
    return _EXTRACT(domain).domain.lower()


def strip_legal_form(name: str) -> str:
    """``Ramp Business Corporation`` -> ``Ramp Business``, repeatedly (``Acme Holdings, Inc.``)."""
    previous = None
    current = " ".join(name.split())
    while previous != current:
        previous = current
        current = _LEGAL_FORM_RE.sub("", current).strip(" ,.")
    return current
