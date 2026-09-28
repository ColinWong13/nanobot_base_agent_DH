"""Read and curate the venue registry that drives retrieval.

`workspace/registry/domains.json` is *generated* by the `venue-registry` skill,
so this module stays a thin layer over that file instead of becoming a second
source of truth. Only the two edits a rebuild actually preserves are offered:

* ``enabled`` on a venue -- ``build_registry.py`` replays it onto the freshly
  generated venue list, matched by venue name.
* ``confirmed`` on a domain -- the flag that switches that replay on at all.

Everything else is deliberately absent. A venue added here, or a tier edited
here, would be silently discarded the next time ``build_registry.py`` runs: it
rebuilds the list from the CCF dataset and carries over nothing but the
``enabled`` flags. Offering a control whose result evaporates is worse than not
offering it, so the API does not pretend to support those edits.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from nanobot.config.paths import get_workspace_path
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

# Serialises read-modify-write cycles within this process. One small file, so a
# single lock for every mutation is enough -- and without it two toggles racing
# from the same page would each write a copy that is missing the other's edit.
_REGISTRY_WRITE_LOCK = threading.Lock()


def domains_registry_path() -> Path:
    """Return the registry path under the agent workspace.

    This is the workspace the skills live in, not the per-session project scope:
    the `literature-search` scripts resolve the same file the same way.
    """
    return get_workspace_path() / "registry" / "domains.json"


def read_domains_registry() -> dict[str, Any]:
    """Return the registry shaped for the domains page.

    Raises ``FileNotFoundError`` when the skill has not produced a registry yet
    and ``ValueError`` when the file is there but unusable; the caller turns
    those into a 404 and a 400 respectively.
    """
    path = domains_registry_path()
    if not path.is_file():
        raise FileNotFoundError(path)
    return _public_payload(_load_raw(path), path)


def set_venue_enabled(*, domain_id: str, venue_name: str, enabled: bool) -> dict[str, Any]:
    """Toggle one venue and return the updated registry.

    Does not touch ``confirmed``. An edit to an unconfirmed domain is lost on
    the next rebuild, so the payload carries the flag and the page warns about
    it -- confirming stays a decision the user makes explicitly rather than a
    side effect of ticking a box.
    """

    def apply(entry: dict[str, Any]) -> None:
        venues = entry.get("venues")
        if not isinstance(venues, list):
            raise ValueError(f"domain {domain_id} has no venue list")
        for venue in venues:
            if isinstance(venue, dict) and venue.get("name") == venue_name:
                venue["enabled"] = enabled
                return
        raise ValueError(f"unknown venue in {domain_id}: {venue_name}")

    return _mutate(domain_id, apply)


def set_domain_confirmed(*, domain_id: str, confirmed: bool) -> dict[str, Any]:
    """Mark a domain curated (or not) and return the updated registry."""

    def apply(entry: dict[str, Any]) -> None:
        entry["confirmed"] = confirmed

    return _mutate(domain_id, apply)


def _mutate(domain_id: str, apply: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    path = domains_registry_path()
    with _REGISTRY_WRITE_LOCK:
        raw = _load_raw(path)
        domains = raw.get("domains")
        if not isinstance(domains, dict) or domain_id not in domains:
            raise ValueError(f"unknown domain: {domain_id}")
        entry = domains[domain_id]
        if not isinstance(entry, dict):
            raise ValueError(f"domain {domain_id} is not an object")
        apply(entry)
        # Stamped on every edit: the page shows this as "last touched", and a
        # checkbox that moves while the timestamp stays put reads as a failed
        # save. `build_registry.py` writes the same format.
        entry["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_text_atomic(path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        return _public_payload(raw, path)


def _load_raw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"registry is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("registry top level is not an object")
    return raw


def _public_payload(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Turn the ``domains`` mapping into a list so the page never has to know
    it is stored as a mapping, and precompute the two counts it displays."""
    raw_domains = raw.get("domains")
    domains: list[dict[str, Any]] = []
    if isinstance(raw_domains, dict):
        for domain_id, entry in raw_domains.items():
            if not isinstance(entry, dict):
                continue
            venues = [v for v in entry.get("venues") or [] if isinstance(v, dict)]
            domains.append(
                {
                    "id": domain_id,
                    "label": entry.get("label") or domain_id,
                    "aliases": entry.get("aliases") or [],
                    "arxiv_cats": entry.get("arxiv_cats") or [],
                    "confirmed": bool(entry.get("confirmed")),
                    "updated_at": entry.get("updated_at"),
                    "venue_count": len(venues),
                    "enabled_count": sum(1 for v in venues if v.get("enabled")),
                    "venues": venues,
                }
            )
    return {
        "version": raw.get("version", 1),
        "path": str(path),
        "domains": domains,
        "suspects": raw.get("_suspects") or [],
    }
