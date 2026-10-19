"""Canonical four-part version handling."""

from __future__ import annotations

import re
from dataclasses import dataclass


CANONICAL_VERSION = "1.0.0.1"
STABLE_VERSION = "1.0.0.1"
_VERSION = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)\."
    r"(?P<build>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?$"
)


@dataclass(frozen=True)
class CanonicalVersion:
    major: int
    minor: int
    patch: int
    build: int
    prerelease: str | None = None

    @classmethod
    def parse(cls, value: str) -> "CanonicalVersion":
        match = _VERSION.fullmatch(value)
        if not match:
            raise ValueError(f"invalid four-part version: {value}")
        groups = match.groupdict()
        return cls(
            major=int(groups["major"]),
            minor=int(groups["minor"]),
            patch=int(groups["patch"]),
            build=int(groups["build"]),
            prerelease=groups["prerelease"],
        )

    def canonical(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}.{self.build}"
        return f"{base}-{self.prerelease}" if self.prerelease else base

    def semver(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        pre = f"-{self.prerelease}" if self.prerelease else ""
        return f"{base}{pre}+build.{self.build}"


def platform_version(canonical: str, supports_four_part: bool) -> str:
    parsed = CanonicalVersion.parse(canonical)
    return parsed.canonical() if supports_four_part else parsed.semver()
