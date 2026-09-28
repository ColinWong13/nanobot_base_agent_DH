"""Read and curate the venue registry that drives retrieval.

`workspace/registry/domains.json` is *generated* by the `venue-registry` skill,
but everything the user edits here now survives the next rebuild. The builder
lays the file's curation over the freshly generated venue list, so this module
can offer real edits instead of the checkbox-only surface it used to.

The split that makes it work, and that every function below respects:

* ``venues[]`` is the **materialised** list -- what the rest of the system
  reads, and what the page renders. Nothing downstream knows about overrides.
* ``overrides`` is the **user's intent** -- which venues they added or removed
  and which tiers they set. The builder re-applies it on every run, so intent
  survives an arbitrary number of rebuilds and dataset refreshes.
* ``base_tier`` on a generated row is what the *source* says this run. It is
  regenerated each build, never stored as history, so "restore the source
  tiers" restores the source's current opinion rather than a stale snapshot.

``confirmed`` is deliberately inert here: it records that the user read the
list, and gates nothing.
"""

from __future__ import annotations

import json
import re
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

# A domain id becomes a CLI argument (`paperctl domain <id>`) and a JSON key, so
# it is held to something that survives both.
_DOMAIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

# Tiers the CCF dataset and the finance seed use between them. A venue's tier is
# held to this plus whatever tiers the domain already carries, which keeps a
# hand-made domain free-form while stopping 'a' or 'AA' from entering the
# registry and silently never matching anything.
_BASE_TIERS = frozenset({"A*", "A", "B", "C"})

# The fields `update_venue` may patch. `name` is absent on purpose -- it is the
# identity key across the registry, the override maps and the match index, so a
# rename goes through `new_name` and is propagated deliberately.
_PATCHABLE_VENUE_FIELDS = ("tier", "type", "full_name", "area", "issn")
_PATCHABLE_DOMAIN_FIELDS = ("label", "aliases", "arxiv_cats")


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


# --- venue edits ------------------------------------------------------------


def set_venue_enabled(*, domain_id: str, venue_name: str, enabled: bool) -> dict[str, Any]:
    """Toggle one venue and return the updated registry.

    The flag rides on the row rather than in ``overrides``: the builder replays
    it by name, so it already survives a rebuild without needing an entry.
    """

    def apply(entry: dict[str, Any]) -> None:
        _venue_row(entry, domain_id, venue_name)["enabled"] = enabled

    return _mutate(domain_id, apply)


def add_venue(*, domain_id: str, venue: dict[str, Any]) -> dict[str, Any]:
    """Append a hand-made venue and return the updated registry.

    The row is marked ``origin: "user"``: the builder carries those forward
    instead of regenerating them, and a rebuild will not invent a ``base_tier``
    for it, because no source ever ranked it.
    """

    def apply(entry: dict[str, Any]) -> None:
        name = _require_str(venue.get("name"), "venue.name")
        if _find_venue(entry, name) is not None:
            raise ValueError(f"venue already exists in {domain_id}: {name}")

        row: dict[str, Any] = {"name": name, "origin": "user", "enabled": True}
        for field in ("type", "full_name", "area", "issn"):
            if value := venue.get(field):
                row[field] = _require_str(value, f"venue.{field}")
        if tier := venue.get("tier"):
            row["tier"] = _require_tier(entry, domain_id, tier)
        if isinstance(venue.get("enabled"), bool):
            row["enabled"] = venue["enabled"]

        venues = entry.get("venues")
        if not isinstance(venues, list):
            raise ValueError(f"domain {domain_id} has no venue list")
        venues.append(row)

    return _mutate(domain_id, apply)


def update_venue(
    *, domain_id: str, venue_name: str, patch: dict[str, Any]
) -> dict[str, Any]:
    """Patch one venue's fields and return the updated registry.

    A tier change is recorded in ``overrides.tier`` so the rebuild re-applies
    it; the other fields ride on the row, which the builder keeps for a
    hand-made venue and regenerates for a generated one -- so those edits only
    persist for ``origin: "user"`` rows, and the page says so.
    """

    def apply(entry: dict[str, Any]) -> None:
        row = _venue_row(entry, domain_id, venue_name)

        # Validate everything before touching anything. The funnel would discard
        # a partial edit anyway, but only because it writes after `apply`
        # returns -- and a rename lands in the override maps as well as the row,
        # so a half-applied one is the kind of state worth not being able to
        # reach at all.
        new_name = patch.get("new_name")
        if new_name:
            new_name = _require_str(new_name, "new_name")
            if new_name != venue_name and _find_venue(entry, new_name) is not None:
                raise ValueError(f"venue already exists in {domain_id}: {new_name}")

        changes: dict[str, str] = {}
        for field in _PATCHABLE_VENUE_FIELDS:
            if field not in patch:
                continue
            value = patch[field]
            changes[field] = (
                _require_tier(entry, domain_id, value) if field == "tier"
                else _require_str(value, field)
            )

        if new_name and new_name != venue_name:
            _rename_venue(entry, row, venue_name, new_name)
        for field, value in changes.items():
            if field == "tier":
                _set_tier_override(entry, row, value)
            row[field] = value

    return _mutate(domain_id, apply)


def remove_venue(*, domain_id: str, venue_name: str) -> dict[str, Any]:
    """Drop a venue and return the updated registry.

    A generated venue leaves a tombstone, so the next CCF refresh cannot bring
    back one the user rejected. A hand-made venue needs none: there is no source
    that would regenerate it.
    """

    def apply(entry: dict[str, Any]) -> None:
        row = _venue_row(entry, domain_id, venue_name)
        _ledger(entry)["tier"].pop(venue_name, None)
        if row.get("origin") != "user":
            removed = _ledger(entry)["removed"]
            if venue_name not in removed:
                removed.append(venue_name)
        entry["venues"].remove(row)

    return _mutate(domain_id, apply)


def reset_domain_tiers(*, domain_id: str) -> dict[str, Any]:
    """Put every hand-edited tier back to what its source says.

    Self-contained: ``base_tier`` is on the row, so this needs no access to the
    builder or the CCF dataset. A hand-made venue keeps its tier -- no source
    ever ranked it, so there is nothing to restore it to.
    """

    def apply(entry: dict[str, Any]) -> None:
        ledger = _ledger(entry)
        overrides = ledger["tier"]
        if not overrides:
            raise ValueError(f"no tier edits to restore in {domain_id}")
        for row in entry.get("venues") or []:
            if not isinstance(row, dict) or row.get("name") not in overrides:
                continue
            if base := row.get("base_tier"):
                row["tier"] = base
        ledger["tier"] = {}

    return _mutate(domain_id, apply)


# --- domain edits -----------------------------------------------------------


def create_domain(
    *,
    domain_id: str,
    label: str,
    aliases: list[str] | None = None,
    arxiv_cats: list[str] | None = None,
) -> dict[str, Any]:
    """Create a hand-made domain and return the updated registry.

    ``origin: "user"`` is stamped here, never taken from the request: it is what
    tells the builder to pass this domain through instead of regenerating it,
    and what tells the page to hide the source-tier restore button.
    """
    domain_id = _require_str(domain_id, "id")
    if not _DOMAIN_ID_RE.match(domain_id):
        raise ValueError(
            f"invalid domain id: {domain_id} (lowercase letters, digits, - and _)"
        )

    def apply(raw: dict[str, Any]) -> None:
        domains = raw.get("domains")
        if not isinstance(domains, dict):
            raise ValueError("registry has no domains mapping")
        if domain_id in domains:
            raise ValueError(f"domain already exists: {domain_id}")
        domains[domain_id] = {
            "label": _require_str(label, "label"),
            "aliases": _require_str_list(aliases, "aliases"),
            "arxiv_cats": _require_str_list(arxiv_cats, "arxiv_cats"),
            "origin": "user",
            "confirmed": False,
            "venues": [],
            "overrides": {"tier": {}, "removed": []},
        }

    return _mutate_registry(apply)


def update_domain(*, domain_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Patch a domain's own fields and return the updated registry."""

    def apply(entry: dict[str, Any]) -> None:
        for field in _PATCHABLE_DOMAIN_FIELDS:
            if field not in patch:
                continue
            value = patch[field]
            entry[field] = (
                _require_str_list(value, field) if field in {"aliases", "arxiv_cats"}
                else _require_str(value, field)
            )

    return _mutate(domain_id, apply)


def delete_domain(*, domain_id: str) -> dict[str, Any]:
    """Remove a domain and return the updated registry.

    A generated domain comes back on the next rebuild -- the builder only knows
    how to regenerate, not how to remember a deletion, and a tombstone for a
    whole domain is a larger idea than this needs. The page warns instead.
    """

    def apply(raw: dict[str, Any]) -> None:
        domains = raw.get("domains")
        if not isinstance(domains, dict) or domain_id not in domains:
            raise ValueError(f"unknown domain: {domain_id}")
        del domains[domain_id]

    return _mutate_registry(apply)


def set_domain_confirmed(*, domain_id: str, confirmed: bool) -> dict[str, Any]:
    """Mark a domain reviewed (or not) and return the updated registry.

    Inert by design: the rebuild no longer consults this, so nothing is lost by
    leaving it alone. It exists so the page can record that the user read the
    list, and nothing else.
    """

    def apply(entry: dict[str, Any]) -> None:
        entry["confirmed"] = confirmed

    return _mutate(domain_id, apply)


# --- the mutation funnels ---------------------------------------------------


def _mutate_registry(apply: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Load -> apply(raw) -> write, under one lock. For registry-level edits.

    `apply` runs before anything touches the file, so a raise discards the whole
    in-memory object and leaves the file byte-identical -- the invariant the
    tests pin. Nothing may write outside the single `json.dumps` below, which is
    also the only place the file's exact byte format is decided.
    """
    path = domains_registry_path()
    with _REGISTRY_WRITE_LOCK:
        raw = _load_raw(path)
        apply(raw)
        _write_text_atomic(path, json.dumps(raw, ensure_ascii=False, indent=2) + "\n")
        return _public_payload(raw, path)


def _mutate(domain_id: str, apply: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Run `apply` against one domain entry and return the updated registry."""

    def outer(raw: dict[str, Any]) -> None:
        entry = _domain_entry(raw, domain_id)
        apply(entry)
        # Stamped on every edit: the page shows this as "last touched", and a
        # checkbox that moves while the timestamp stays put reads as a failed
        # save. `build_registry.py` writes the same format.
        entry["updated_at"] = _now()

    return _mutate_registry(outer)


# --- entry and row lookup ---------------------------------------------------


def _domain_entry(raw: dict[str, Any], domain_id: str) -> dict[str, Any]:
    domains = raw.get("domains")
    if not isinstance(domains, dict) or domain_id not in domains:
        raise ValueError(f"unknown domain: {domain_id}")
    entry = domains[domain_id]
    if not isinstance(entry, dict):
        raise ValueError(f"domain {domain_id} is not an object")
    if not isinstance(entry.get("venues"), list):
        raise ValueError(f"domain {domain_id} has no venue list")
    return entry


def _find_venue(entry: dict[str, Any], venue_name: str) -> dict[str, Any] | None:
    for row in entry.get("venues") or []:
        if isinstance(row, dict) and row.get("name") == venue_name:
            return row
    return None


def _venue_row(entry: dict[str, Any], domain_id: str, venue_name: str) -> dict[str, Any]:
    row = _find_venue(entry, venue_name)
    if row is None:
        raise ValueError(f"unknown venue in {domain_id}: {venue_name}")
    return row


def _ledger(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the override ledger, creating it on a registry built before it.

    The first rebuild adds the block, so an un-migrated file is normal rather
    than exceptional, and every reader here has to cope with it.
    """
    overrides = entry.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        entry["overrides"] = overrides
    if not isinstance(overrides.get("tier"), dict):
        overrides["tier"] = {}
    if not isinstance(overrides.get("removed"), list):
        overrides["removed"] = []
    return overrides


def _set_tier_override(entry: dict[str, Any], row: dict[str, Any], tier: str) -> None:
    """Record the user's tier, or clear the record when it matches the source.

    Clearing on a match is what keeps the restore button honest: a venue edited
    A -> B -> A has no pending edit, and the count reads zero.
    """
    name = row.get("name")
    if row.get("origin") == "user":
        # No source to disagree with, so the row *is* the record.
        return
    if tier == row.get("base_tier"):
        _ledger(entry)["tier"].pop(name, None)
    else:
        _ledger(entry)["tier"][name] = tier


def _rename_venue(
    entry: dict[str, Any], row: dict[str, Any], old_name: str, new_name: str
) -> None:
    """Rename a row and carry its override entries across.

    Without the carry, a renamed venue would keep its row but silently lose the
    tier the user set on it -- the override maps are keyed by name, and the
    builder would then re-apply nothing.
    """
    ledger = _ledger(entry)
    if old_name in ledger["tier"]:
        ledger["tier"][new_name] = ledger["tier"].pop(old_name)
    if old_name in ledger["removed"]:
        ledger["removed"].remove(old_name)
    row["name"] = new_name


# --- validation -------------------------------------------------------------


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _require_str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _require_tier(entry: dict[str, Any], domain_id: str, tier: Any) -> str:
    """Hold a tier to the domain's own vocabulary.

    A source-backed domain has one -- CCF's A/B/C or FT50's A*/A/B -- and a typo
    there produces a venue that silently never matches. A hand-made domain has
    none: the user invented it, so whatever they name their tiers is the
    vocabulary, and there is nothing to check against.
    """
    tier = _require_str(tier, "tier")
    if entry.get("origin") == "user":
        return tier
    allowed = _BASE_TIERS | {
        row["tier"]
        for row in entry.get("venues") or []
        if isinstance(row, dict) and isinstance(row.get("tier"), str)
    }
    if tier not in allowed:
        raise ValueError(f"unsupported tier for {domain_id}: {tier}")
    return tier


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    it is stored as a mapping, and precompute the counts it displays.

    A whitelist, deliberately. ``venues`` is the exception -- it passes through
    whole, so a per-venue field the builder adds reaches the page without an
    edit here. A *domain-level* field needs one, and the three below are it.
    """
    raw_domains = raw.get("domains")
    domains: list[dict[str, Any]] = []
    if isinstance(raw_domains, dict):
        for domain_id, entry in raw_domains.items():
            if not isinstance(entry, dict):
                continue
            venues = [v for v in entry.get("venues") or [] if isinstance(v, dict)]
            overrides = entry.get("overrides")
            overrides = overrides if isinstance(overrides, dict) else {}
            tier_edits = overrides.get("tier")
            tier_edits = tier_edits if isinstance(tier_edits, dict) else {}
            removed = overrides.get("removed")
            removed = removed if isinstance(removed, list) else []
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
                    # `origin` is what the page keys "can this be restored to
                    # its source?" off, and `tier_override_count` is what makes
                    # that button enable. The manual count covers everything
                    # else a rebuild has to carry, so the page can say so.
                    "origin": entry.get("origin"),
                    "tier_override_count": len(tier_edits),
                    "manual_edit_count": (
                        len(tier_edits)
                        + len(removed)
                        + sum(1 for v in venues if v.get("origin") == "user")
                    ),
                }
            )
    return {
        "version": raw.get("version", 1),
        "path": str(path),
        "domains": domains,
        "suspects": raw.get("_suspects") or [],
    }
