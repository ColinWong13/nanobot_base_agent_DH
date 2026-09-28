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
    add_venue,
    create_domain,
    delete_domain,
    domains_registry_path,
    read_domains_registry,
    remove_venue,
    reset_domain_tiers,
    set_domain_confirmed,
    set_venue_enabled,
    update_domain,
    update_venue,
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


# --- the edits a rebuild now preserves ---------------------------------------


def _curated() -> dict:
    """The registry as `build_registry.py` writes it after Stage 1.

    Differs from `_registry()` in the two ways that matter to the new edits:
    generated rows carry `base_tier`, and each domain carries an override
    ledger, so a test can tell "the user changed this" from "the source says".
    """
    payload = _registry()
    payload["domains"]["ai"]["origin"] = "ccf-2026"
    payload["domains"]["ai"]["overrides"] = {"tier": {}, "removed": []}
    payload["domains"]["ai"]["venues"] = [
        {"name": "ACL", "tier": "A", "base_tier": "A", "type": "conference",
         "enabled": True, "origin": "ccf-2026"},
        {"name": "EMNLP", "tier": "B", "base_tier": "B", "type": "conference",
         "enabled": False, "origin": "ccf-2026"},
    ]
    payload["domains"]["finance"]["origin"] = "finance-seed"
    payload["domains"]["finance"]["overrides"] = {"tier": {}, "removed": []}
    payload["domains"]["finance"]["venues"] = [
        {"name": "JF", "tier": "A*", "base_tier": "A*", "type": "journal",
         "enabled": True, "origin": "ft50"},
    ]
    return payload


def _ai(workspace: Path) -> dict:
    return _read_raw(workspace)["domains"]["ai"]


def _row(workspace: Path, domain: str, name: str) -> dict:
    return next(
        v for v in _read_raw(workspace)["domains"][domain]["venues"] if v["name"] == name
    )


class TestAddVenue:
    def test_appends_a_row_marked_as_the_users(self, workspace: Path) -> None:
        _write(workspace, _curated())

        add_venue(domain_id="ai", venue={"name": "Nature", "tier": "A", "type": "journal"})

        row = _row(workspace, "ai", "Nature")
        assert row["origin"] == "user"
        assert row["tier"] == "A"
        # No source ever ranked it, so there is nothing to restore it to.
        assert "base_tier" not in row

    def test_the_new_row_reaches_the_page(self, workspace: Path) -> None:
        _write(workspace, _curated())

        payload = add_venue(domain_id="ai", venue={"name": "Nature", "type": "journal"})

        ai = next(d for d in payload["domains"] if d["id"] == "ai")
        assert ai["venue_count"] == 3
        assert ai["manual_edit_count"] == 1

    def test_a_duplicate_name_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="already exists in ai: ACL"):
            add_venue(domain_id="ai", venue={"name": "ACL", "tier": "B"})

    def test_a_tier_outside_the_vocabulary_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="unsupported tier for ai: AA"):
            add_venue(domain_id="ai", venue={"name": "Nature", "tier": "AA"})

    def test_a_domain_with_no_venues_still_accepts_its_own_tier(self, workspace: Path) -> None:
        """A hand-made domain is free-form; the base tiers are a floor, not a cap."""
        _write(workspace, _curated())
        create_domain(domain_id="dh", label="数字人文")

        add_venue(domain_id="dh", venue={"name": "DSH", "tier": "顶刊"})

        assert _row(workspace, "dh", "DSH")["tier"] == "顶刊"

    def test_a_nameless_venue_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="venue.name must be a non-empty string"):
            add_venue(domain_id="ai", venue={"tier": "A"})


class TestUpdateVenue:
    def test_a_tier_change_is_recorded_as_an_override(self, workspace: Path) -> None:
        _write(workspace, _curated())

        payload = update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        assert _row(workspace, "ai", "ACL")["tier"] == "C"
        # ...while the source's own opinion is left where it was, for restore.
        assert _row(workspace, "ai", "ACL")["base_tier"] == "A"
        assert _ai(workspace)["overrides"]["tier"] == {"ACL": "C"}
        assert next(d for d in payload["domains"] if d["id"] == "ai")["tier_override_count"] == 1

    def test_setting_a_tier_back_to_the_source_value_clears_the_override(
        self, workspace: Path
    ) -> None:
        """Otherwise an A -> B -> A round trip would leave a restore button lit
        for a venue that has nothing left to restore."""
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "A"})

        assert _ai(workspace)["overrides"]["tier"] == {}

    def test_a_hand_made_venue_records_no_override(self, workspace: Path) -> None:
        _write(workspace, _curated())
        add_venue(domain_id="ai", venue={"name": "Nature", "tier": "B"})

        update_venue(domain_id="ai", venue_name="Nature", patch={"tier": "A"})

        # The row is its own source, so there is nothing to override.
        assert _ai(workspace)["overrides"]["tier"] == {}
        assert _row(workspace, "ai", "Nature")["tier"] == "A"

    def test_other_fields_are_patched_in_place(self, workspace: Path) -> None:
        _write(workspace, _curated())

        update_venue(
            domain_id="ai",
            venue_name="ACL",
            patch={"full_name": "Annual Meeting of the ACL", "issn": "1234-5678"},
        )

        row = _row(workspace, "ai", "ACL")
        assert row["full_name"] == "Annual Meeting of the ACL"
        assert row["issn"] == "1234-5678"
        assert row["tier"] == "A"

    def test_a_rename_carries_the_tier_override_across(self, workspace: Path) -> None:
        """The override maps are keyed by name, so a rename that did not
        propagate would silently drop the tier the user set."""
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        update_venue(domain_id="ai", venue_name="ACL", patch={"new_name": "ACL 2027"})

        assert _row(workspace, "ai", "ACL 2027")["tier"] == "C"
        assert _ai(workspace)["overrides"]["tier"] == {"ACL 2027": "C"}

    def test_a_rename_onto_an_existing_name_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="already exists in ai: EMNLP"):
            update_venue(domain_id="ai", venue_name="ACL", patch={"new_name": "EMNLP"})

    def test_an_unknown_venue_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="unknown venue in ai: NOPE"):
            update_venue(domain_id="ai", venue_name="NOPE", patch={"tier": "A"})


class TestRemoveVenue:
    def test_a_generated_venue_leaves_a_tombstone(self, workspace: Path) -> None:
        _write(workspace, _curated())

        remove_venue(domain_id="ai", venue_name="EMNLP")

        assert [v["name"] for v in _ai(workspace)["venues"]] == ["ACL"]
        assert _ai(workspace)["overrides"]["removed"] == ["EMNLP"]

    def test_a_hand_made_venue_needs_no_tombstone(self, workspace: Path) -> None:
        """There is no source that would regenerate it, so a tombstone would be
        a permanent entry guarding against nothing."""
        _write(workspace, _curated())
        add_venue(domain_id="ai", venue={"name": "Nature", "tier": "A"})

        remove_venue(domain_id="ai", venue_name="Nature")

        assert _ai(workspace)["overrides"]["removed"] == []
        assert "Nature" not in [v["name"] for v in _ai(workspace)["venues"]]

    def test_removing_a_venue_drops_its_tier_override(self, workspace: Path) -> None:
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        remove_venue(domain_id="ai", venue_name="ACL")

        assert _ai(workspace)["overrides"]["tier"] == {}


class TestResetDomainTiers:
    def test_puts_every_edited_tier_back(self, workspace: Path) -> None:
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})
        update_venue(domain_id="ai", venue_name="EMNLP", patch={"tier": "A"})

        reset_domain_tiers(domain_id="ai")

        assert _row(workspace, "ai", "ACL")["tier"] == "A"
        assert _row(workspace, "ai", "EMNLP")["tier"] == "B"
        assert _ai(workspace)["overrides"]["tier"] == {}

    def test_is_self_contained(self, workspace: Path) -> None:
        """It must not need the builder, the CCF dataset or the network: the
        source value is on the row as `base_tier`."""
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        payload = reset_domain_tiers(domain_id="ai")

        assert next(d for d in payload["domains"] if d["id"] == "ai")["tier_override_count"] == 0

    def test_a_hand_made_venue_keeps_its_tier(self, workspace: Path) -> None:
        """The one case where the button visibly does not do what it says, and
        the alternative -- deleting the user's venue -- is worse."""
        _write(workspace, _curated())
        add_venue(domain_id="ai", venue={"name": "Nature", "tier": "B"})
        update_venue(domain_id="ai", venue_name="Nature", patch={"tier": "A"})
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        reset_domain_tiers(domain_id="ai")

        # ACL goes back to the source; Nature stays where the user put it.
        assert _row(workspace, "ai", "ACL")["tier"] == "A"
        assert _row(workspace, "ai", "Nature")["tier"] == "A"

    def test_nothing_to_restore_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="no tier edits to restore in ai"):
            reset_domain_tiers(domain_id="ai")


class TestDomainLifecycle:
    def test_creates_a_domain_marked_as_the_users(self, workspace: Path) -> None:
        _write(workspace, _curated())

        payload = create_domain(
            domain_id="dh", label="数字人文 / DH", aliases=["数字人文"], arxiv_cats=[]
        )

        entry = _read_raw(workspace)["domains"]["dh"]
        assert entry["label"] == "数字人文 / DH"
        assert entry["aliases"] == ["数字人文"]
        # `user` is what makes the builder pass it through instead of
        # regenerating it -- and it is never taken from the request.
        assert entry["origin"] == "user"
        assert entry["venues"] == []
        assert entry["overrides"] == {"tier": {}, "removed": []}
        assert any(d["id"] == "dh" for d in payload["domains"])

    def test_a_bad_id_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="invalid domain id"):
            create_domain(domain_id="数字人文", label="DH")

    def test_a_taken_id_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="domain already exists: ai"):
            create_domain(domain_id="ai", label="Another AI")

    def test_updates_a_domains_own_fields(self, workspace: Path) -> None:
        _write(workspace, _curated())

        update_domain(
            domain_id="ai", patch={"label": "AI（我改过）", "arxiv_cats": ["cs.CL"]}
        )

        entry = _ai(workspace)
        assert entry["label"] == "AI（我改过）"
        assert entry["arxiv_cats"] == ["cs.CL"]
        # The venues are untouched by a domain-level patch.
        assert [v["name"] for v in entry["venues"]] == ["ACL", "EMNLP"]

    def test_deletes_a_domain(self, workspace: Path) -> None:
        _write(workspace, _curated())

        payload = delete_domain(domain_id="ai")

        assert set(_read_raw(workspace)["domains"]) == {"finance"}
        assert [d["id"] for d in payload["domains"]] == ["finance"]

    def test_deleting_an_unknown_domain_is_refused(self, workspace: Path) -> None:
        _write(workspace, _curated())

        with pytest.raises(ValueError, match="unknown domain: nope"):
            delete_domain(domain_id="nope")

    def test_a_created_domain_takes_its_own_venues(self, workspace: Path) -> None:
        _write(workspace, _curated())
        create_domain(domain_id="dh", label="数字人文")

        add_venue(domain_id="dh", venue={"name": "DSH", "tier": "A"})

        assert _row(workspace, "dh", "DSH")["origin"] == "user"


class TestRejectedEditsLeaveNoTrace:
    """Every new mutation must hold this, not just the two that came before.

    `test_rejected_edit_leaves_the_file_byte_identical` pins it for the old
    toggle; these are the paths added since, and the risk is the same: a
    validation that runs *after* the write turns a refused edit into a
    half-applied one.
    """

    @pytest.mark.parametrize(
        "call",
        [
            lambda: add_venue(domain_id="ai", venue={"name": "ACL", "tier": "A"}),
            lambda: add_venue(domain_id="ai", venue={"name": "X", "tier": "AA"}),
            lambda: update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "AA"}),
            lambda: update_venue(domain_id="ai", venue_name="NOPE", patch={"tier": "A"}),
            # The only path that validates *after* it has something to undo: a
            # rename lands in the row and the override maps, so a later failure
            # in the same patch must not leave it half-applied.
            lambda: update_venue(
                domain_id="ai",
                venue_name="ACL",
                patch={"new_name": "ACL 2027", "tier": "AA"},
            ),
            lambda: remove_venue(domain_id="ai", venue_name="NOPE"),
            lambda: reset_domain_tiers(domain_id="ai"),
            lambda: create_domain(domain_id="ai", label="dup"),
            lambda: create_domain(domain_id="BAD ID", label="x"),
            lambda: update_domain(domain_id="ai", patch={"aliases": "not a list"}),
            lambda: delete_domain(domain_id="nope"),
        ],
    )
    def test_a_refused_edit_does_not_move_the_file(self, workspace: Path, call) -> None:
        path = _write(workspace, _curated())
        before = path.read_bytes()

        with pytest.raises(ValueError):
            call()

        assert path.read_bytes() == before

    def test_the_override_ledger_survives_an_unrelated_edit(self, workspace: Path) -> None:
        _write(workspace, _curated())
        update_venue(domain_id="ai", venue_name="ACL", patch={"tier": "C"})

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        assert _ai(workspace)["overrides"]["tier"] == {"ACL": "C"}

    def test_a_top_level_suspects_key_survives_an_edit(self, workspace: Path) -> None:
        """The builder writes its build-time suspects beside the domains; the
        page reads them from there, so a mutation must not drop them."""
        payload = _curated()
        payload["_suspects"] = ["SIG- METRICS (SIGMETRICS) → 连字符后跟空格"]
        _write(workspace, payload)

        set_venue_enabled(domain_id="ai", venue_name="EMNLP", enabled=True)

        assert _read_raw(workspace)["_suspects"] == ["SIG- METRICS (SIGMETRICS) → 连字符后跟空格"]

    def test_suspects_reach_the_payload(self, workspace: Path) -> None:
        payload = _curated()
        payload["_suspects"] = ["SIG- METRICS (SIGMETRICS) → 连字符后跟空格"]
        _write(workspace, payload)

        assert read_domains_registry()["suspects"] == [
            "SIG- METRICS (SIGMETRICS) → 连字符后跟空格"
        ]
