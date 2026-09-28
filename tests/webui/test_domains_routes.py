"""The venue-registry routes are registered in four places, and they must agree.

Adding a mutation to `_WEBUI_MUTATION_PATHS` without also adding it to
`_WEBUI_MUTATION_ONLY_PATHS` still *works* over the WebSocket -- the dispatch
chain does not consult that set -- so the omission is invisible until someone
sends the same path over plain HTTP and gets a 200 where they should get a 405.
That is a write reachable without the WS handshake, and nothing else in the
suite would notice.

These tests are cheap and they are the only thing standing between that
invariant and the next person who adds a route in a hurry.
"""

from __future__ import annotations

import pytest

from nanobot.webui import ws_http
from nanobot.webui.ws_http import (
    _DOMAINS_ACTIONS,
    _DOMAINS_MUTATION_ACTIONS,
    _WEBUI_MUTATION_ONLY_PATHS,
    _WEBUI_MUTATION_PATHS,
)

_DOMAIN_ACTIONS = {a for a in _WEBUI_MUTATION_PATHS if a.startswith("domains.")}


def test_every_domains_action_has_a_handler() -> None:
    """Otherwise the route exists and answers 404 at dispatch time."""
    assert _DOMAIN_ACTIONS == set(_DOMAINS_ACTIONS)


def test_every_domains_path_is_a_declared_mutation_path() -> None:
    """The HTTP 405 guard. A path here but not there is a silent write hole
    over plain HTTP."""
    ungated = sorted(set(_DOMAINS_MUTATION_ACTIONS) - _WEBUI_MUTATION_ONLY_PATHS)
    assert ungated == [], f"domains mutation paths missing from the allowlist: {ungated}"


def test_the_allowlist_declares_nothing_it_does_not_serve() -> None:
    """The other direction: a stale entry would 405 a path that no longer
    exists, which reads as a server bug rather than a removed feature."""
    declared = {p for p in _WEBUI_MUTATION_ONLY_PATHS if p.startswith("/api/webui/domains/")}
    served = set(_DOMAINS_MUTATION_ACTIONS) | {"/api/webui/domains"}
    assert declared - served == set()


def test_the_action_table_covers_every_registry_edit() -> None:
    """The feature set, pinned. A mutation added to `domains_api` but not wired
    up here is unreachable from the page, and that is easy to miss because the
    Python tests call the functions directly."""
    assert _DOMAIN_ACTIONS == {
        "domains.venue.set_enabled",
        "domains.venue.add",
        "domains.venue.update",
        "domains.venue.remove",
        "domains.tier_reset",
        "domains.create",
        "domains.update",
        "domains.delete",
        "domains.confirm",
    }


def test_paths_are_unique() -> None:
    """Two actions sharing a path would make the dispatch order decide which
    one runs, and the loser would be silently unreachable."""
    domains_paths = [
        p for a, p in _WEBUI_MUTATION_PATHS.items() if a.startswith("domains.")
    ]
    assert len(domains_paths) == len(set(domains_paths))


@pytest.mark.parametrize(
    "path",
    sorted(_DOMAINS_MUTATION_ACTIONS),
)
def test_the_payload_validators_reject_junk(path: str) -> None:
    """Every handler must turn a malformed body into a ValueError, which
    `_domains_response` maps to a 400. A KeyError or TypeError would escape as a
    500 and read as a server fault rather than a bad request."""
    with pytest.raises(ValueError):
        _DOMAINS_MUTATION_ACTIONS[path]({})
