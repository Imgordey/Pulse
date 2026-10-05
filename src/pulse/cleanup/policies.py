"""Explicit, immutable cache policies. No arbitrary directories or user documents."""

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pulse.cleanup.filesystem import valid_relative


@dataclass(frozen=True)
class CachePolicy:
    id: str
    root: Path
    title: str
    minimum_age_days: int
    consequence: str


POLICIES = MappingProxyType(
    {
        policy.id: policy
        for policy in (
            CachePolicy(
                "pip-http",
                Path("Library/Caches/pip/http-v2"),
                "pip downloads (current)",
                7,
                "Removed packages may need to be downloaded again. Close pip/installers first.",
            ),
            CachePolicy(
                "pip-http-legacy",
                Path("Library/Caches/pip/http"),
                "pip downloads (legacy)",
                7,
                "Removed packages may need to be downloaded again. Close pip/installers first.",
            ),
            CachePolicy(
                "npm-content",
                Path(".npm/_cacache/content-v2/sha512"),
                "npm download content",
                30,
                "npm may download missing cached content again. Close npm and Node installers; "
                "offline installs may need these downloads.",
            ),
            CachePolicy(
                "go-build",
                Path("Library/Caches/go-build"),
                "Go build artifacts",
                30,
                "Future Go builds may take longer. Finish all Go builds before cleanup. "
                "Source projects and downloaded modules are kept.",
            ),
            CachePolicy(
                "cargo-downloads",
                Path(".cargo/registry/cache"),
                "Cargo downloaded archives",
                30,
                "Cargo may download removed archives again. Finish Cargo builds first; "
                "offline builds may need these archives. Source trees and credentials are kept.",
            ),
        )
    }
)


def cache_policy(category: str) -> CachePolicy:
    try:
        return POLICIES[category]
    except KeyError as exc:
        raise ValueError("Unsupported cleanup category") from exc


def recognized_path(relative: Path, category: str) -> bool:
    cache_policy(category)
    if not valid_relative(relative):
        return False
    parts = relative.parts
    if category in ("pip-http", "pip-http-legacy"):
        name = parts[-1].removesuffix(".body")
        return (
            len(parts) == 6
            and re.fullmatch(r"[0-9a-f]{56}", name) is not None
            and tuple(name[:5]) == parts[:5]
        )
    if category == "npm-content":
        return (
            len(parts) == 3
            and all(re.fullmatch(r"[0-9a-f]{2}", p) for p in parts[:2])
            and re.fullmatch(r"[0-9a-f]{124}", parts[2]) is not None
        )
    if category == "go-build":
        return (
            len(parts) == 2
            and re.fullmatch(r"[0-9a-f]{64}-[ad]", parts[1]) is not None
            and parts[0] == parts[1][:2]
        )
    if category == "cargo-downloads":
        # Default crates.io registries only. Custom/private registries stay protected.
        return (
            len(parts) == 2
            and re.fullmatch(r"(?:index\.crates\.io|github\.com)-[0-9a-f]{16}", parts[0])
            is not None
            and re.fullmatch(
                r"[A-Za-z0-9_-]+-\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.+-]+)?\.crate", parts[1]
            )
            is not None
        )
    return False
