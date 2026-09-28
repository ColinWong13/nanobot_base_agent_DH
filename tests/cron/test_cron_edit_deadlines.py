"""Editing task instructions must not postpone or drop an existing occurrence."""

import json
from dataclasses import replace

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule


@pytest.mark.parametrize("kind", ["every", "cron", "at"])
@pytest.mark.parametrize("resend_schedule", [False, True])
async def test_metadata_edit_preserves_due_occurrence(tmp_path, monkeypatch, kind, resend_schedule):
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    schedules = {
        "every": CronSchedule(kind="every", every_ms=60_000),
        "cron": CronSchedule(kind="cron", expr="* * * * *", tz="UTC"),
        "at": CronSchedule(kind="at", at_ms=now + 60_000),
    }
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    job = service.add_job(
        name="Daily report",
        schedule=schedules[kind],
        message="Summarize yesterday",
        session_key="websocket:report",
        origin_channel="websocket",
        origin_chat_id="report",
        delete_after_run=kind == "at",
    )
    due_at = job.state.next_run_at_ms
    assert due_at is not None
    now = due_at + 1_000

    updated = service.update_job(
        job.id,
        name="Updated report",
        message="Include the latest figures",
        schedule=replace(job.schedule) if resend_schedule else None,
    )
    assert isinstance(updated, CronJob)
    assert updated.state.next_run_at_ms == due_at

    calls = []

    async def execute(job):
        calls.append((job.id, job.name, job.payload.message))

    # A separate service consumes the persisted edit, as the gateway does.
    reader = CronService(store_path, on_job=execute)
    loaded = reader.get_job(job.id)
    assert loaded is not None
    assert loaded.state.next_run_at_ms == due_at
    await reader._on_timer()
    await reader._on_timer()
    assert calls == [(job.id, "Updated report", "Include the latest figures")]

    finished = reader.get_job(job.id)
    if kind == "at":
        assert finished is None
    else:
        assert finished is not None
        assert finished.state.next_run_at_ms > now
        assert len(finished.state.run_history) == 1
        assert finished.state.last_status == "ok"


async def test_start_preserves_an_overdue_occurrence(tmp_path, monkeypatch):
    """A restart after a job's slot runs it late rather than dropping it.

    The tick loop's due check is `now >= next_run_at_ms`, so a process that
    sleeps past a deadline runs it once on waking. `start()` used to disagree:
    it rewrote every `next_run_at_ms` to the next *future* occurrence, so a
    gateway restarted after Monday 09:00 silently skipped that week.
    """
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    job = service.add_job(
        name="Weekly inquiry",
        schedule=CronSchedule(kind="cron", expr="0 9 * * 1", tz="UTC"),
        message="What should I look into this week?",
        session_key="feishu:ou_test",
        origin_channel="feishu",
        origin_chat_id="ou_test",
    )
    due_at = job.state.next_run_at_ms
    assert due_at is not None

    # The gateway goes down before the slot and comes back a week later.
    now = due_at + 7 * 24 * 60 * 60 * 1000
    calls = []

    async def execute(job):
        calls.append(job.id)

    reader = CronService(store_path, on_job=execute)
    await reader.start()
    try:
        resumed = reader.get_job(job.id)
        assert resumed is not None
        assert resumed.enabled is True
        assert resumed.state.next_run_at_ms == due_at, "start() postponed the missed run"

        await reader._on_timer()
        assert calls == [job.id], "the missed run never fired"
    finally:
        reader.stop()

    # The next wake is scheduled forward, so the catch-up does not repeat.
    after = reader.get_job(job.id)
    assert after is not None
    assert after.state.next_run_at_ms is not None
    assert after.state.next_run_at_ms > now


async def test_start_still_gives_a_time_to_a_job_with_none(tmp_path, monkeypatch):
    """Jobs with no next run at all must still be scheduled, or they never fire.

    `kind: "at"` jobs whose deadline passed while the gateway was down are left
    as `enabled: true` with `next_run_at_ms: None` -- a zombie that neither runs
    nor gets disabled. Only the missing-time case is recomputed here.
    """
    now = 1_900_000_000_000
    monkeypatch.setattr("nanobot.cron.service._now_ms", lambda: now)
    store_path = tmp_path / "cron" / "jobs.json"
    service = CronService(store_path)
    job = service.add_job(
        name="Zombie deadline",
        schedule=CronSchedule(kind="every", every_ms=60_000),
        message="run me",
        session_key="websocket:test",
        origin_channel="websocket",
        origin_chat_id="test",
    )
    assert job.state.next_run_at_ms is not None
    # An unstarted instance has no live store, so add_job queues an action
    # instead of writing jobs.json. Start it once to get the job on disk.
    await service.start()
    service.stop()

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    for entry in raw["jobs"]:
        entry["state"]["nextRunAtMs"] = None
    store_path.write_text(json.dumps(raw), encoding="utf-8")

    reader = CronService(store_path)
    await reader.start()
    try:
        revived = reader.get_job(job.id)
        assert revived is not None
        assert revived.enabled is True
        assert revived.state.next_run_at_ms == now + 60_000
    finally:
        reader.stop()
