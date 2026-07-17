"""Reproducible Docker-backed sandbox templates."""

from __future__ import annotations

import io
import json
import re
import tarfile
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

import docker
from docker.errors import DockerException

from agentnest.exceptions import RuntimeNotAvailableError

if TYPE_CHECKING:
    from docker.client import DockerClient


@dataclass(frozen=True, slots=True)
class Template:
    """Declarative, reproducible sandbox image definition."""

    base_image: str = "python:3.12-slim"
    packages: tuple[str, ...] = ()
    system_packages: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    commands: tuple[str, ...] = ()

    def pip_install(self, *packages: str) -> Template:
        return Template(
            self.base_image,
            self.packages + tuple(packages),
            self.system_packages,
            dict(self.environment),
            self.commands,
        )

    def apt_install(self, *packages: str) -> Template:
        return Template(
            self.base_image,
            self.packages,
            self.system_packages + tuple(packages),
            dict(self.environment),
            self.commands,
        )

    def run(self, *commands: str) -> Template:
        return Template(
            self.base_image,
            self.packages,
            self.system_packages,
            dict(self.environment),
            self.commands + tuple(commands),
        )

    def with_environment(self, **environment: str) -> Template:
        return Template(
            self.base_image,
            self.packages,
            self.system_packages,
            {**self.environment, **environment},
            self.commands,
        )

    def dockerfile(self) -> str:
        lines = [f"FROM {self.base_image}"]
        if self.system_packages:
            joined = " ".join(self.system_packages)
            lines.append(
                "RUN apt-get update && apt-get install -y --no-install-recommends "
                f"{joined} && rm -rf /var/lib/apt/lists/*"
            )
        if self.packages:
            lines.append("RUN pip install --no-cache-dir " + " ".join(self.packages))
        for key, value in sorted(self.environment.items()):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) is None:
                raise ValueError(f"invalid environment variable name: {key!r}")
            lines.append(f"ENV {key}={json.dumps(value)}")
        lines.extend(f"RUN {command}" for command in self.commands)
        return "\n".join(lines) + "\n"

    def build(self, tag: str | None = None, *, client: DockerClient | None = None) -> str:
        """Build the template and return its deterministic image tag."""

        content = self.dockerfile().encode()
        image_tag = tag or f"agentnest-template:{sha256(content).hexdigest()[:16]}"
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            info = tarfile.TarInfo("Dockerfile")
            info.size = len(content)
            bundle.addfile(info, io.BytesIO(content))
        archive.seek(0)
        try:
            docker_client = client or docker.from_env()
            docker_client.images.build(fileobj=archive, custom_context=True, tag=image_tag, rm=True)
        except DockerException as exc:
            raise RuntimeNotAvailableError(f"could not build template: {exc}") from exc
        return image_tag
