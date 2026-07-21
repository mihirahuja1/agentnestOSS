"""Egress allowlisting for the Docker backend.

A sandbox that needs partial network access is placed on an ``internal`` Docker
network with no route to the internet. A small sidecar container -- the only
member of that network with a second, internet-connected interface -- runs the
allowlisting CONNECT proxy from :mod:`agentnest._egress_proxy`. The sandbox is
handed ``HTTP_PROXY``/``HTTPS_PROXY`` pointing at the sidecar, so every outbound
connection is checked against the policy's domain list before it is tunnelled.

This gives the most-requested control that a bare ``network on/off`` switch
cannot: "reach PyPI and nothing else", with each decision logged.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentnest.exceptions import RuntimeNotAvailableError, UnsupportedCapabilityError

if TYPE_CHECKING:
    from docker.client import DockerClient
    from docker.models.containers import Container
    from docker.models.networks import Network

PROXY_SCRIPT = Path(__file__).with_name("_egress_proxy.py")
PROXY_ALIAS = "agentnest-egress"
PROXY_PORT = 8080
_PROXY_UID = 65532


class EgressSidecar:
    """Lifecycle for one sandbox's egress proxy and internal network."""

    def __init__(
        self,
        client: DockerClient,
        *,
        sandbox_id: str,
        domains: tuple[str, ...],
        proxy_image: str,
        labels: dict[str, str],
    ) -> None:
        if not domains:
            raise UnsupportedCapabilityError(
                "egress allowlist requires at least one domain; CIDR-only allowlists "
                "need a policy-aware backend such as Kubernetes"
            )
        self._client = client
        self._domains = domains
        self._proxy_image = proxy_image
        self._labels = labels
        self._network: Network | None = None
        self._proxy: Container | None = None
        self._name = f"agentnest-egress-{sandbox_id[:12]}"

    @property
    def network_name(self) -> str:
        network = self._network
        if network is None:  # pragma: no cover - defensive
            raise RuntimeNotAvailableError("egress network has not been created")
        return str(network.name)

    @property
    def proxy_environment(self) -> dict[str, str]:
        """Proxy variables injected into the sandbox container."""

        endpoint = f"http://{PROXY_ALIAS}:{PROXY_PORT}"
        return {
            "HTTP_PROXY": endpoint,
            "HTTPS_PROXY": endpoint,
            "http_proxy": endpoint,
            "https_proxy": endpoint,
            "NO_PROXY": "localhost,127.0.0.1",
            "no_proxy": "localhost,127.0.0.1",
        }

    def start(self) -> None:
        """Create the internal network and launch the filtering proxy."""

        from docker.errors import DockerException, ImageNotFound

        try:
            self._client.images.get(self._proxy_image)
        except ImageNotFound:
            self._client.images.pull(self._proxy_image)

        try:
            self._network = self._client.networks.create(
                self._name,
                driver="bridge",
                internal=True,
                labels=self._labels,
            )
            # The sidecar starts on the default bridge, which is its only route
            # to the internet. The sandbox never gets this interface.
            self._proxy = self._client.containers.run(
                self._proxy_image,
                command=["python", "/agentnest/_egress_proxy.py"],
                detach=True,
                environment={
                    "AGENTNEST_ALLOW": ",".join(self._domains),
                    "AGENTNEST_PROXY_PORT": str(PROXY_PORT),
                    "PYTHONUNBUFFERED": "1",
                },
                user=f"{_PROXY_UID}:{_PROXY_UID}",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                pids_limit=128,
                mem_limit="128m",
                network="bridge",
                labels={**self._labels, "agentnest.role": "egress-proxy"},
                volumes={
                    str(PROXY_SCRIPT): {
                        "bind": "/agentnest/_egress_proxy.py",
                        "mode": "ro",
                    }
                },
            )
            # The internal network is the sandbox's only network; the proxy joins
            # it under a stable alias so the sandbox can resolve it by name.
            self._network.connect(self._proxy, aliases=[PROXY_ALIAS])
        except DockerException as exc:
            self.destroy()
            raise RuntimeNotAvailableError(f"could not start egress proxy: {exc}") from exc

    def destroy(self) -> None:
        from contextlib import suppress

        from docker.errors import DockerException

        proxy = self._proxy
        network = self._network
        self._proxy = None
        self._network = None
        if proxy is not None:
            with suppress(DockerException):
                proxy.remove(force=True)
        if network is not None:
            with suppress(DockerException):
                network.reload()
                for container in network.containers:
                    with suppress(DockerException):
                        network.disconnect(container, force=True)
                network.remove()

    def logs(self) -> str:
        from docker.errors import DockerException

        proxy = self._proxy
        if proxy is None:
            return ""
        try:
            return proxy.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        except (DockerException, OSError):
            return ""


def egress_labels(base: dict[str, str], sandbox_id: str) -> dict[str, str]:
    return {**base, "agentnest.sandbox": sandbox_id}


def as_domains(domains: tuple[str, ...], cidrs: tuple[str, ...]) -> tuple[str, ...]:
    """Validate that an allowlist is expressible by the CONNECT proxy."""

    if cidrs:
        raise UnsupportedCapabilityError(
            "the Docker egress proxy filters by domain name and cannot enforce raw "
            "CIDR allowlists; use the Kubernetes backend for CIDR NetworkPolicies"
        )
    return domains
