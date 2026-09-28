"""Tests for the venue-registry read and curation layer.

Every test points the module at ``tmp_path``. The real registry lives at
``~/.nanobot/workspace/registry/domains.json`` and is Colin's curated data, so a
test that forgot the monkeypatch would edit live state rather than fail loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.webui import domains_api
from nanobot.webui.domains_api import (
    domains_registry_path,
    read_domains_registry,
    set_domain_confirmed,
    set_venue_enabled,
)


def _registry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "domains": {
            "ai": {
                "label": "人工智能 / AI",
                "aliases": ["AI"],
                "arxiv_cats": ["cs.CL", "cs.LG"],
                "venues": [
                    {"name": "ACL", "tier": "A", "enabled": True, "origin": "ccf-2026"},
                    {"name": "EMNLP", "tier": "B", "enabled": False, "origin": "ccf-2026"},
                ],
                "confirmed": False,
                "updated_at": "2026-09-27T11:47:11Z",
            },
            "finance": {
                "label": "金融 / Finance",
                "aliases": ["金融"],
                "arxiv_cats": ["q-fin.PM"],
                "venues": [{"name": "JF", "tier": "A*", "enabled": True, "origin": "seed"}],
                "confirmed": True,
                "updated_at": "2026-09-27T11:47:11Z",
            },
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the registry at an empty workspace and return it."""
    monkeypatch.setattr(domains_api, "get_workspace_path", lambda: tmp_path)
    return tmp_path


def _write(workspace: Path, payload: object) -> Path:
    path = workspace / "registry" / "domains.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _read_raw(workspace: Path) -> dict:
    return json.loads((workspace / "registry" / "domains.json").read_text(encoding="utf-8"))


class TestPath:
    def test_registry_sits_under_the_workspace(self, workspace: Path) -> None:
        assert domains_registry_path() == workspace / "registry" / "domains.json"


class TestRead:
    def test_missing_registry_raises_file_not_found(self, workspace: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_domains_registry()

    def test_shapes_domains_as_a_list_with_counts(self, workspace: Path) -> None:
        _write(workspace, _registry())

        payload = read_domains_registry()

        assert payload["version"] == 1
        assert payload["path"] == str(domains_registry_path())
        by_id = {d["id"]: d for d in payload["domains"]}
        assert set(by_id) == {"ai", "finance"}
        assert by_id["ai"]["label"] == "人工智能 / AI"
        assert by_id["ai"]["venue_count"] == 2
        # Counts are what the page shows, so they must agree with the venues
        # list rather than a second source of truth.
        assert by_id["ai"]["enabled_count"] == 1
        assert by_id["ai"]["confirmed"] is False
        assert by_id["finance"]["confirmed"] is True
        assert [v["name"] for v in by_id["ai"]["venues"]] == ["ACL", "EMNLP"]

    def test_survives_missing_optional_fields(self, workspace: Path) -> None:
        _write(workspace, {"version": 1, "domains": {"ai": {"venues": [{"name": "ACL"}]}}})

        domain = read_domains_registry()["domains"][0]

        # label falls back to the id so the page never renders a blank heading.
        assert domain["label"] == "ai"
        assert domain["aliases"] == []
        assert domain["arxiv_cats"] == []
        assert domain["confirmed"] is False
        assert domain["enabled_count"] == 0

    def test_domains_not_a_mapping_yields_empty_list(self, workspace: Path) -> None:
        _write(workspace, {"version": 1, "domains": ["nope"]})
        assert read_domains_registry()["domains"] == []

    def test_invalid_json_is_a_value_error(self, workspace: Path) -> None:
        path = workspace / "registry" / "domains.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")

        with pytest.raises(ValueError, match="not valid JSON"):
            read_domains_registry()

    def test_non_object_top_level_is_a_value_error(self, workspace: Path) -> None:
        _write(workspace, [1, 2, 3])
        with pytest.raises(ValueError, match="top level"):
            read_domains_registry()


class TestSetVenueEnabled:
    def test_toggles_one_venue(self, workspace: Path) -> None:
        _write(workspace, _registry())

        payload = set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        ai = next(d for d in payload["domains"] if d["id"] == "ai")
        assert ai["enabled_count"] == 2
        names = {v["name"]: v["enabled"] for v in _read_raw(workspace)["domains"]["ai"]["venues"]}
        assert names == {"ACL": True, "EMNLP": True}

    def test_disabling_works_too(self, workspace: Path) -> None:
        _write(workspace, _registry())

        set_venue_enabled(domain_id="ai", venue_name="ACL", enabled=False)

        names = {v["name"]: v["enabled"] for v in _read_raw(workspace)["domains"]["ai"]["venues"]}
        assert names == {"ACL": False, "EMNLP": False}

    def test_does_not_silently_confirm_the_domain(self, workspace: Path) -> None:
        """Confirming stays an explicit choice.

        The tempting shortcut is to flip `confirmed` whenever a venue moves, so
        the edit is never lost. That would hide a state change the user did not
        ask for; the page warns about the unconfirmed case instead.
        """
        _write(workspace, _registry())

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        assert _read_raw(workspace)["domains"]["ai"]["confirmed"] is False

    def test_leaves_the_other_domain_untouched(self, workspace: Path) -> None:
        _write(workspace, _registry())
        before = _read_raw(workspace)["domains"]["finance"]

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        assert _read_raw(workspace)["domains"]["finance"] == before

    def test_refreshes_updated_at(self, workspace: Path) -> None:
        _write(workspace, _registry())

        payload = set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        stamp = next(d for d in payload["domains"] if d["id"] == "ai")["updated_at"]
        assert stamp != "2026-09-27T11:47:11Z"
        assert stamp.endswith("Z")
        assert _read_raw(workspace)["domains"]["ai"]["updated_at"] == stamp

    def test_unknown_domain(self, workspace: Path) -> None:
        _write(workspace, _registry())
        with pytest.raises(ValueError, match="unknown domain"):
            set_venue_enabled(domain_id="nope", venue_name="ACL", enabled=True)

    def test_unknown_venue(self, workspace: Path) -> None:
        _write(workspace, _registry())
        with pytest.raises(ValueError, match="unknown venue"):
            set_venue_enabled(domain_id="ai", venue_name="NOPE", enabled=True)

    def test_rejected_edit_leaves_the_file_byte_identical(self, workspace: Path) -> None:
        path = _write(workspace, _registry())
        before = path.read_bytes()

        with pytest.raises(ValueError):
            set_venue_enabled(domain_id="ai", venue_name="NOPE", enabled=True)

        assert path.read_bytes() == before


class TestSetDomainConfirmed:
    def test_marks_a_domain_curated(self, workspace: Path) -> None:
        _write(workspace, _registry())

        payload = set_domain_confirmed(domain_id="ai", confirmed=True)

        assert next(d for d in payload["domains"] if d["id"] == "ai")["confirmed"] is True
        assert _read_raw(workspace)["domains"]["ai"]["confirmed"] is True

    def test_can_unconfirm(self, workspace: Path) -> None:
        _write(workspace, _registry())

        set_domain_confirmed(domain_id="finance", confirmed=False)

        assert _read_raw(workspace)["domains"]["finance"]["confirmed"] is False

    def test_unknown_domain(self, workspace: Path) -> None:
        _write(workspace, _registry())
        with pytest.raises(ValueError, match="unknown domain"):
            set_domain_confirmed(domain_id="nope", confirmed=True)


class TestFileContract:
    """The file has to stay in the shape `build_registry.py` and the skills leave it.

    The literature-search scripts read this file directly, so a formatting
    change here would show up as a diff on every rebuild rather than as a test
    failure anywhere.
    """

    def test_writes_the_builders_exact_format(self, workspace: Path) -> None:
        _write(workspace, _registry())

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        text = (workspace / "registry" / "domains.json").read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n" == text

    def test_keeps_non_ascii_labels_unescaped(self, workspace: Path) -> None:
        _write(workspace, _registry())

        set_domain_confirmed(domain_id="ai", confirmed=True)

        text = (workspace / "registry" / "domains.json").read_text(encoding="utf-8")
        assert "人工智能" in text  # not 人...

    def test_preserves_passthrough_keys(self, workspace: Path) -> None:
        """Unknown keys in a domain entry survive an edit.

        The builder owns this file's schema; rewriting it from a whitelist
        would quietly delete whatever it adds next.
        """
        payload = _registry()
        payload["domains"]["ai"]["future_field"] = {"keep": "me"}
        _write(workspace, payload)

        set_domain_confirmed(domain_id="ai", confirmed=True)

        assert _read_raw(workspace)["domains"]["ai"]["future_field"] == {"keep": "me"}

    def test_no_temp_files_left_behind(self, workspace: Path) -> None:
        _write(workspace, _registry())

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        leftovers = [p.name for p in (workspace / "registry").iterdir() if p.name != "domains.json"]
        assert leftovers == []
