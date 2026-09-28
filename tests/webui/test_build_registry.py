"""Tests for the venue-registry rebuilder.

`build_registry.py` is the only program that rewrites the whole registry, and
its failure mode is silent: a bug does not raise, it just drops a venue, a tier
or a checkbox, and the next `normalize.py` run tiers papers off the reduced
list. Until this file existed it had no test anywhere.

The script lives outside the package, in the user's workspace, so it is loaded
by path and every test skips cleanly when that workspace is absent.

**The live registry is Colin's curated data.** Every test points the module at
``tmp_path``; ``_guard_live_registry`` fails the session if one ever forgets.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _workspace_root() -> Path:
    return Path.home() / ".nanobot" / "workspace"


def _script_path() -> Path:
    return _workspace_root() / "skills" / "venue-registry" / "scripts" / "build_registry.py"


def _live_registry() -> Path:
    return _workspace_root() / "registry" / "domains.json"


def _fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="session", autouse=True)
def _guard_live_registry():
    """Fail loudly if any test in this file touched the real registry.

    Every test here patches `_REGISTRY` to a temp path. This is what makes that
    convention load-bearing rather than a comment: a test that forgets it does
    not corrupt Colin's registry in silence, it fails.
    """
    before = _fingerprint(_live_registry())
    yield
    after = _fingerprint(_live_registry())
    if before != after:
        raise AssertionError(
            f"a test in this file modified the live registry {_live_registry()} "
            f"({before} -> {after}); every test must patch the module's _REGISTRY"
        )


@pytest.fixture(scope="module")
def builder():
    """The loaded `build_registry` module, or a skip when it is not installed."""
    path = _script_path()
    if not path.is_file():
        pytest.skip(f"venue-registry skill not present at {path}")
    spec = importlib.util.spec_from_file_location("_build_registry_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- fixtures that stand in for the CCF dataset and the finance seed ---------

_CCF_AREAS = ("人工智能", "数据库/数据挖掘/内容检索", "计算机图形学与多媒体")


def _ccf_records() -> list[dict]:
    return [
        {"area": "人工智能", "rank": "A", "abbreviation": "ACL",
         "full_name": "Annual Meeting of the ACL", "type": "conference"},
        {"area": "人工智能", "rank": "B", "abbreviation": "EMNLP",
         "full_name": "Conference on EMNLP", "type": "conference"},
        {"area": "人工智能", "rank": "A", "abbreviation": "AAAI AAAI",
         "full_name": "AAAI Conference", "type": "conference"},
        {"area": "数据库/数据挖掘/内容检索", "rank": "A", "abbreviation": "SIGIR",
         "full_name": "SIGIR Conference", "type": "conference"},
        {"area": "计算机图形学与多媒体", "rank": "C", "abbreviation": "PacificVis",
         "full_name": "Pacific Visualization", "type": "conference"},
        # Outside the seeded areas: must never reach the registry.
        {"area": "网络与信息安全", "rank": "A", "abbreviation": "S&P",
         "full_name": "Security and Privacy", "type": "conference"},
    ]


def _finance_seed() -> dict:
    return {
        "venues": [
            {"name": "Journal of Finance", "issn": "0022-1082", "tier": "A*",
             "tier_source": "ft50"},
            {"name": "Review of Finance", "issn": "1572-3097", "tier": "A",
             "tier_source": "field"},
            {"name": "Finance Letters", "issn": "0000-0000", "tier": "B",
             "tier_source": "field"},
        ]
    }


@pytest.fixture()
def sandbox(builder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp registry with fake sources, so nothing here reads the real data."""
    ccf = tmp_path / "rankings.json"
    ccf.write_text(json.dumps(_ccf_records(), ensure_ascii=False), encoding="utf-8")
    seed = tmp_path / "finance_venues.json"
    seed.write_text(json.dumps(_finance_seed(), ensure_ascii=False), encoding="utf-8")

    registry = tmp_path / "registry" / "domains.json"
    monkeypatch.setattr(builder, "_CCF_RANKINGS", ccf)
    monkeypatch.setattr(builder, "_FINANCE_SEED", seed)
    monkeypatch.setattr(builder, "_REGISTRY", registry)
    return registry


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _venues(payload: dict, domain: str) -> dict[str, dict]:
    return {v["name"]: v for v in payload["domains"][domain]["venues"]}


def _enabled(payload: dict, domain: str) -> set[str]:
    return {name for name, v in _venues(payload, domain).items() if v.get("enabled")}


# --- the core promise: a rebuild does not lose the user's work ---------------


def test_a_fresh_build_seeds_from_the_sources(builder, sandbox: Path) -> None:
    payload = builder.build(force=False)
    ai = payload["domains"]["ai"]
    # Only the seeded areas; the corrupt 'AAAI AAAI' is repaired, not dropped.
    assert set(_venues(payload, "ai")) == {"ACL", "EMNLP", "AAAI", "SIGIR", "PacificVis"}
    # A-tier venues start on, the rest off.
    assert _enabled(payload, "ai") == {"ACL", "AAAI", "SIGIR"}
    assert ai["overrides"] == {"tier": {}, "removed": []}
    assert ai["origin"] == f"ccf-{builder._CCF_YEAR}"
    # base_tier mirrors the source on a clean build.
    assert {n: v["base_tier"] for n, v in _venues(payload, "ai").items()} == {
        "ACL": "A", "AAAI": "A", "SIGIR": "A", "EMNLP": "B", "PacificVis": "C",
    }


def test_preserves_enabled_toggles_across_a_rebuild(builder, sandbox: Path) -> None:
    """The bug this whole change exists to fix.

    Preservation used to be gated on `confirmed`, so an unconfirmed domain lost
    every checkbox on the next rebuild -- which is the state both live domains
    are in.
    """
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    builder._write_atomic(sandbox, json.dumps(builder.build(force=False)) + "\n")

    # Untick a default-on venue and tick a default-off one, without confirming.
    payload = _read(sandbox)
    for venue in payload["domains"]["ai"]["venues"]:
        venue["enabled"] = venue["name"] == "EMNLP"
    assert payload["domains"]["ai"]["confirmed"] is False
    sandbox.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    rebuilt = builder.build(force=False)
    assert _enabled(rebuilt, "ai") == {"EMNLP"}


def test_an_untouched_domain_rebuilds_identically(builder, sandbox: Path) -> None:
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    builder._write_atomic(sandbox, json.dumps(builder.build(force=False), ensure_ascii=False) + "\n")
    first = _read(sandbox)

    builder._write_atomic(sandbox, json.dumps(builder.build(force=False), ensure_ascii=False) + "\n")
    second = _read(sandbox)

    # `updated_at` is stamped fresh every run, so compare the curated content.
    for payload in (first, second):
        for domain in payload["domains"].values():
            domain.pop("updated_at")
    assert first == second


def test_preserves_a_tier_override_and_keeps_base_tier_honest(
    builder, sandbox: Path
) -> None:
    """`base_tier` is regenerated each run; the override is the user's."""
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    payload["domains"]["ai"]["overrides"]["tier"]["ACL"] = "C"
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=False)
    acl = _venues(rebuilt, "ai")["ACL"]
    assert acl["tier"] == "C"          # the user's value is what lands
    assert acl["base_tier"] == "A"     # the source's opinion is still recorded
    assert rebuilt["domains"]["ai"]["overrides"]["tier"] == {"ACL": "C"}


def test_a_removed_venue_stays_removed(builder, sandbox: Path) -> None:
    """The tombstone must survive, or the next CCF refresh resurrects it."""
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    ai = payload["domains"]["ai"]
    ai["overrides"]["removed"].append("PacificVis")
    ai["venues"] = [v for v in ai["venues"] if v["name"] != "PacificVis"]
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=False)
    assert "PacificVis" not in _venues(rebuilt, "ai")
    assert "PacificVis" in rebuilt["domains"]["ai"]["overrides"]["removed"]


def test_a_user_added_venue_survives_and_is_marked(builder, sandbox: Path) -> None:
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    payload["domains"]["ai"]["venues"].append(
        {"name": "Colin Journal of DH", "type": "journal", "tier": "A",
         "enabled": True, "origin": "user"}
    )
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=False)
    added = _venues(rebuilt, "ai")["Colin Journal of DH"]
    assert added["origin"] == "user"
    assert added["enabled"] is True
    # No source gave it a tier, so there is nothing to restore it to.
    assert "base_tier" not in added


def test_domain_fields_the_user_edited_are_not_reverted(builder, sandbox: Path) -> None:
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    payload["domains"]["ai"]["label"] = "人工智能（我改过）"
    payload["domains"]["ai"]["arxiv_cats"] = ["cs.CL"]
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=False)
    assert rebuilt["domains"]["ai"]["label"] == "人工智能（我改过）"
    assert rebuilt["domains"]["ai"]["arxiv_cats"] == ["cs.CL"]


def test_a_hand_made_domain_passes_through_untouched(builder, sandbox: Path) -> None:
    """A domain with no upstream must come back byte-for-byte, not be dropped."""
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    handmade = {
        "label": "数字人文 / DH",
        "aliases": ["数字人文"],
        "arxiv_cats": [],
        "origin": "user",
        "confirmed": True,
        "updated_at": "2026-01-01T00:00:00Z",
        "venues": [{"name": "DSH", "type": "journal", "tier": "A",
                    "enabled": True, "origin": "user"}],
        "overrides": {"tier": {}, "removed": []},
    }
    payload["domains"]["dh"] = handmade
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=False)
    assert rebuilt["domains"]["dh"] == handmade


def test_force_discards_the_curation(builder, sandbox: Path) -> None:
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    payload = builder.build(force=False)
    ai = payload["domains"]["ai"]
    ai["overrides"]["tier"]["ACL"] = "C"
    ai["overrides"]["removed"].append("PacificVis")
    ai["venues"] = [v for v in ai["venues"] if v["name"] != "PacificVis"]
    ai["venues"].append({"name": "Mine", "tier": "A", "enabled": True, "origin": "user"})
    payload["domains"]["dh"] = {"label": "DH", "venues": [], "origin": "user"}
    builder._write_atomic(sandbox, json.dumps(payload, ensure_ascii=False) + "\n")

    rebuilt = builder.build(force=True)
    assert _venues(rebuilt, "ai")["ACL"]["tier"] == "A"
    assert "PacificVis" in _venues(rebuilt, "ai")
    assert "Mine" not in _venues(rebuilt, "ai")
    assert rebuilt["domains"]["ai"]["overrides"] == {"tier": {}, "removed": []}
    assert "dh" not in rebuilt["domains"]


# --- durability of the file itself ------------------------------------------


def test_suspects_reach_the_written_file(builder, sandbox: Path) -> None:
    """`_suspects` was popped for printing and never written, so the API's
    suspects list was permanently empty and the page's strip was dead code."""
    broken = _ccf_records() + [
        {"area": "人工智能", "rank": "A", "abbreviation": "SIG- METRICS",
         "full_name": "SIGMETRICS", "type": "conference"}
    ]
    Path(builder._CCF_RANKINGS).write_text(
        json.dumps(broken, ensure_ascii=False), encoding="utf-8"
    )
    payload = builder.build(force=False)
    assert any("SIG- METRICS" in item for item in payload["_suspects"])

    # ...and they must reach the file, not just the returned payload.
    builder.main(["--out", str(sandbox)])
    assert any("SIG- METRICS" in item for item in _read(sandbox)["_suspects"])


def test_the_write_is_atomic_and_leaves_no_temp_files(builder, sandbox: Path) -> None:
    sandbox.parent.mkdir(parents=True, exist_ok=True)
    builder._write_atomic(sandbox, '{"version": 1}\n')
    assert json.loads(sandbox.read_text(encoding="utf-8")) == {"version": 1}
    assert list(sandbox.parent.glob(".*tmp*")) == []


def test_force_without_yes_is_refused(builder, sandbox: Path) -> None:
    """`--force` now discards curation outright, so it must not be a slip."""
    with pytest.raises(SystemExit):
        builder.main(["--force", "--out", str(sandbox)])
    assert not sandbox.exists()


# --- the test that guards the real data -------------------------------------


def test_the_live_registry_rebuilds_without_losing_anything(builder, tmp_path: Path) -> None:
    """Rebuild a *copy* of Colin's actual registry, diverged from the defaults.

    Rebuilding the live file as-is proves less than it looks: both domains are
    unconfirmed, and their checkbox sets happen to already equal the source
    defaults, so a rebuild is a no-op either way. So this edits the copy in
    every way the UI will -- every one of which the old code discarded -- and
    then demands the rebuild keep all of it alongside the 258 real venues.

    What this covers on real data: venue loss, tier overrides, tombstones, and
    hand-added rows. What it cannot cover *today*: a lost checkbox, because the
    live toggles happen to match the defaults exactly, so dropping them changes
    nothing observable. `test_preserves_enabled_toggles_across_a_rebuild` is
    what guards that, off synthetic data; the gap closes on its own the first
    time Colin's toggles diverge, and this test then starts covering it too.
    """
    live = _live_registry()
    if not live.is_file():
        pytest.skip(f"no live registry at {live}")
    if not (builder._WORKSPACE / "skills" / "ccf-rank" / "references").is_dir():
        pytest.skip("ccf-rank dataset not installed")

    copy = tmp_path / "domains.json"
    copy.write_bytes(live.read_bytes())
    payload = _read(copy)

    ai = payload["domains"]["ai"]
    was_on = next(v["name"] for v in ai["venues"] if v.get("enabled"))
    was_off = next(v["name"] for v in ai["venues"] if not v.get("enabled"))
    # `setdefault`, because a registry written before this change has no
    # overrides block yet -- the first rebuild is what adds one.
    ledger = ai.setdefault("overrides", {"tier": {}, "removed": []})
    ledger["tier"][was_on] = "C"
    ledger["removed"].append(was_off)
    ai["venues"] = [v for v in ai["venues"] if v["name"] != was_off]
    ai["venues"].append({"name": "手加的刊", "type": "journal", "tier": "A",
                         "enabled": True, "origin": "user"})
    copy.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    builder.main(["--out", str(copy)])
    after = _read(copy)

    assert set(after["domains"]) == set(payload["domains"])
    for key in payload["domains"]:
        names_before = {v["name"] for v in payload["domains"][key].get("venues", [])}
        names_after = {v["name"] for v in after["domains"][key].get("venues", [])}
        assert names_after >= names_before, f"{key} lost venues on rebuild"

    ai_after = _venues(after, "ai")
    assert ai_after[was_on]["tier"] == "C"                 # the override held
    assert ai_after[was_on]["base_tier"] != "C"            # and stayed honest
    assert was_off not in ai_after                         # the tombstone held
    assert ai_after["手加的刊"]["origin"] == "user"         # the manual row held
    # Every venue still in both files kept its checkbox.
    for name, venue in _venues(payload, "ai").items():
        if name in ai_after:
            assert ai_after[name]["enabled"] == venue.get("enabled"), f"{name} flipped"
