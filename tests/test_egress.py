from __future__ import annotations

import pytest

from agentnest._egress_proxy import host_allowed, normalize_patterns
from agentnest.egress import as_domains
from agentnest.exceptions import UnsupportedCapabilityError
from agentnest.policy import NetworkPolicy


def test_normalize_patterns_trims_and_lowercases() -> None:
    assert normalize_patterns(" PyPI.org , files.pythonhosted.org ,") == (
        "pypi.org",
        "files.pythonhosted.org",
    )
    assert normalize_patterns("") == ()


@pytest.mark.parametrize(
    "host",
    ["pypi.org", "PyPI.org", "files.pypi.org", "a.b.pypi.org", "pypi.org."],
)
def test_host_allowed_matches_domain_and_subdomains(host: str) -> None:
    assert host_allowed(host, ("pypi.org",))


@pytest.mark.parametrize(
    "host",
    ["evil.com", "notpypi.org", "pypi.org.evil.com", "", "pypi-org.com"],
)
def test_host_allowed_rejects_everything_else(host: str) -> None:
    assert not host_allowed(host, ("pypi.org",))


def test_host_allowed_multiple_patterns() -> None:
    patterns = ("pypi.org", "files.pythonhosted.org")
    assert host_allowed("files.pythonhosted.org", patterns)
    assert host_allowed("pypi.org", patterns)
    assert not host_allowed("github.com", patterns)


def test_as_domains_rejects_cidr_allowlists() -> None:
    policy = NetworkPolicy.allowlist(domains=("pypi.org",), cidrs=("10.0.0.0/8",))
    with pytest.raises(UnsupportedCapabilityError, match="CIDR"):
        as_domains(policy.domains, policy.cidrs)


def test_as_domains_passes_domain_only() -> None:
    assert as_domains(("pypi.org",), ()) == ("pypi.org",)
