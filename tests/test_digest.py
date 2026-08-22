"""Tests for the noise-filtered triage digest."""

import dataclasses

from ernest.config import Config
from jobs.triage import _format


def _grouped():
    return {
        "gmail:work": {
            "needs_reply": ["• author — send the proofs"],
            "newsletter": ["• BookBub — promo", "• Kindlepreneur — promo"],
            "cold": ["• spammer — buy now"],
        }
    }


def _cfg(cats=("urgent", "needs_reply", "needs_action")):
    return dataclasses.replace(Config(), digest_categories=tuple(cats))


def test_shows_actionable_hides_noise():
    out = _format(_grouped(), _cfg())
    assert "send the proofs" in out          # actionable shown
    assert "BookBub" not in out              # newsletter hidden
    assert "spammer" not in out              # cold hidden
    assert "Filed quietly" in out            # tally present
    assert "2 newsletter" in out and "1 cold" in out


def test_all_noise_stays_silent():
    # Nothing actionable → no message at all (newsletters don't interrupt).
    grouped = {"gmail:work": {"newsletter": ["• x", "• y", "• z"]}}
    assert _format(grouped, _cfg()) == ""


def test_config_can_widen_categories():
    out = _format(_grouped(), _cfg(("needs_reply", "newsletter")))
    assert "BookBub" in out                  # now shown because configured
    assert "1 cold" in out                   # cold still filed
