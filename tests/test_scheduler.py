"""Tests for the scheduler's due-job logic (pure, no subprocesses)."""

from datetime import datetime

from ernest import scheduler


def test_interval_job_seeded_then_fires_after_interval():
    last_i, last_d = {}, {}
    t0 = datetime(2027, 1, 1, 9, 0, 0)
    # first tick with no state → triage fires immediately
    due = scheduler.due_jobs(t0, last_i, last_d)
    assert any(k == "triage" for k, _ in due)
    # 5 min later → not yet (interval 15 min)
    assert scheduler.due_jobs(datetime(2027, 1, 1, 9, 5, 0), last_i, last_d) == []
    # 15 min after the last run → fires again
    due2 = scheduler.due_jobs(datetime(2027, 1, 1, 9, 15, 0), last_i, last_d)
    assert any(k == "triage" for k, _ in due2)


def test_daily_job_fires_once_at_its_minute():
    last_i, last_d = {}, {}
    at_730 = datetime(2027, 1, 1, 7, 30, 0)
    due = scheduler.due_jobs(at_730, last_i, last_d)
    keys = [k for k, _ in due]
    assert "brief-morning" in keys
    # same minute again → does not double-fire
    again = scheduler.due_jobs(datetime(2027, 1, 1, 7, 30, 30), last_i, last_d)
    assert "brief-morning" not in [k for k, _ in again]


def test_daily_job_not_at_other_times():
    last_i, last_d = {}, {}
    due = scheduler.due_jobs(datetime(2027, 1, 1, 12, 0, 0), last_i, last_d)
    assert [k for k, _ in due if k.startswith("brief")] == []


def test_daily_job_fires_next_day():
    last_i, last_d = {}, {}
    scheduler.due_jobs(datetime(2027, 1, 1, 21, 0, 0), last_i, last_d)
    nxt = scheduler.due_jobs(datetime(2027, 1, 2, 21, 0, 0), last_i, last_d)
    assert "brief-evening" in [k for k, _ in nxt]


def test_job_argvs_are_module_form():
    for _key, argv, _iv in scheduler.INTERVAL_JOBS:
        assert argv[0] == "-m" and argv[1].startswith("jobs.")
    for _key, argv, _hm in scheduler.DAILY_JOBS:
        assert argv[0] == "-m" and argv[1].startswith("jobs.")
