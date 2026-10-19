"""PitchSim uses the whole pitch like real football does.

The reference ranges come from open tracking data (Metrica Sports sample games 1 and 2, aggregates
only, see tests/reference/metrica_derived.json and docs/DETAILS.md). The sim is an event model, not
tracking, so the checks compare like with like: ball share per third and channel, run lengths of
consecutive passes in one zone, pass geometry, and the team shape from `shape.slot`.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest
from pitchsim.config import MatchConfig
from pitchsim.shape import slot
from pitchsim.sim import simulate_match
from playmakers_schema.models import Vec2

REAL = json.loads((Path(__file__).parent / "reference" / "metrica_derived.json").read_text())
SEEDS = range(8)
L, W = 105.0, 68.0


def _pos(e):
    for key in ("end_position", "position", "ball_position", "start_position"):
        p = getattr(e, key, None)
        if p is not None:
            return p
    return None


def _quantile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))]


def _runs(zones):
    out, start = [], 0
    for i in range(1, len(zones)):
        if zones[i] != zones[start]:
            out.append(i - start)
            start = i
    out.append(len(zones) - start)
    return out


def _ball_samples(events):
    """Ball position once per match second, moving in a straight line between event positions."""
    pts = [(e.clock_ms / 1000, _pos(e), e) for e in events if _pos(e) is not None]
    out, j = [], 0
    for t in range(0, 90 * 60):
        while j + 1 < len(pts) and pts[j + 1][0] <= t:
            j += 1
        (t0, p0, e), nxt = pts[j], pts[j + 1] if j + 1 < len(pts) else None
        if nxt and nxt[0] > t0:
            f = min(1.0, (t - t0) / (nxt[0] - t0))
            p0 = Vec2(x=p0.x + (nxt[1].x - p0.x) * f, y=p0.y + (nxt[1].y - p0.y) * f)
        out.append((p0, e.team_id or ""))
    return out


@pytest.fixture(scope="module")
def matches():
    return [simulate_match(MatchConfig(seed=s)) for s in SEEDS]


def _shares(values, size, n=3):
    return [
        sum(1 for v in values if min(n - 1, int(v // size)) == k) / len(values) for k in range(n)
    ]


def test_ball_time_in_each_third_and_channel_matches_real_football(matches) -> None:
    real_thirds = REAL["ball_time_in_thirds_x"]
    real_channels = REAL["ball_time_in_channels_y"]
    all_thirds, all_channels = [], []
    for events in matches:
        samples = _ball_samples(events)
        thirds = _shares([p.x for p, _ in samples], L / 3)
        channels = _shares([p.y for p, _ in samples], W / 3)
        all_thirds.append(thirds)
        all_channels.append(channels)
        # No single match lives in one third or down one wing.
        assert all(0.15 <= share <= 0.6 for share in thirds), thirds
        assert all(0.22 <= share <= 0.45 for share in channels), channels
    for k in range(3):
        assert abs(statistics.mean(t[k] for t in all_thirds) - real_thirds[k]) < 0.07
        assert abs(statistics.mean(c[k] for c in all_channels) - real_channels[k]) < 0.05


def test_ball_spread_matches_real_football(matches) -> None:
    xs, ys = [], []
    for events in matches:
        for p, _ in _ball_samples(events):
            xs.append(p.x)
            ys.append(p.y)
    real = REAL["ball_spread_sd_m"]
    assert statistics.pstdev(xs) == pytest.approx(real["x"], rel=0.2)
    assert statistics.pstdev(ys) == pytest.approx(real["y"], rel=0.15)


def test_no_long_spells_in_one_third_or_channel(matches) -> None:
    thirds, channels = [], []
    for events in matches:
        passes = [e for e in events if e.event_type == "pass"]
        thirds += _runs([min(2, int(e.end_position.x // (L / 3))) for e in passes])
        channels += _runs([min(2, int(e.end_position.y // (W / 3))) for e in passes])
    real_t, real_c = REAL["third_spell_passes"], REAL["channel_spell_passes"]
    assert _quantile(thirds, 0.5) <= real_t["p50"] + 1
    assert _quantile(thirds, 0.9) <= real_t["p90"] + 3
    assert _quantile(thirds, 0.99) <= real_t["p99"] * 1.5
    assert _quantile(channels, 0.9) <= real_c["p90"] + 3
    assert _quantile(channels, 0.99) <= real_c["p99"] * 1.5


def test_pass_geometry_matches_real_football(matches) -> None:
    passes = [e for events in matches for e in events if e.event_type == "pass"]
    lengths = [e.distance_m for e in passes]
    dx = [abs(e.end_position.x - e.start_position.x) for e in passes]
    dy = [abs(e.end_position.y - e.start_position.y) for e in passes]
    assert statistics.median(lengths) == pytest.approx(REAL["pass_length_m"]["p50"], rel=0.2)
    assert _quantile(lengths, 0.9) == pytest.approx(REAL["pass_length_m"]["p90"], rel=0.25)
    assert statistics.median(dx) == pytest.approx(REAL["pass_abs_dx_m"]["p50"], rel=0.35)
    assert statistics.median(dy) == pytest.approx(REAL["pass_abs_dy_m"]["p50"], rel=0.3)
    switches = sum(1 for d in dy if d > 30) / len(dy)
    assert (
        0.5 * REAL["switch_share_dy_over_30m"] <= switches <= 2 * REAL["switch_share_dy_over_30m"]
    )


def test_team_shape_matches_real_football(matches) -> None:
    width = {True: [], False: []}
    line = {True: [], False: []}
    keeper_off, keeper_ratio = [], []
    for events in matches:
        for p, team in _ball_samples(events)[::5]:
            for home in (True, False):
                attacking = team.endswith("_HOME") == home
                slots = [slot(i, p, home=home, attacking=attacking) for i in range(11)]
                outfield = slots[1:]
                width[attacking].append(max(s.y for s in outfield) - min(s.y for s in outfield))
                us = sorted((s.x if home else L - s.x) for s in outfield)
                line[attacking].append(us[1])
                bu = p.x if home else L - p.x
                if bu < L / 3:
                    gu = slots[0].x if home else L - slots[0].x
                    keeper_off.append(gu)
                    if abs(p.y - W / 2) > 3:
                        keeper_ratio.append((slots[0].y - W / 2) / (p.y - W / 2))
    real_w, real_l = REAL["team_width_m"], REAL["def_line_height_m"]
    assert statistics.median(width[True]) == pytest.approx(real_w["in_possession"]["p50"], rel=0.12)
    assert statistics.median(width[False]) == pytest.approx(
        real_w["out_of_possession"]["p50"], rel=0.12
    )
    # Wide in possession, compact out of it.
    assert statistics.median(width[True]) > statistics.median(width[False]) + 3
    for phase, key in ((True, "in_possession"), (False, "out_of_possession")):
        assert statistics.median(line[phase]) == pytest.approx(real_l[key]["p50"], rel=0.2)
        # The back line steps up and drops off with the ball rather than sitting still.
        assert _quantile(line[phase], 0.9) - _quantile(line[phase], 0.1) > 25
    real_gk = REAL["keeper_off_line_m_when_ball_in_own_third_or_mid"]
    assert statistics.median(keeper_off) == pytest.approx(real_gk["p50"], abs=1.5)
    assert 0.03 <= statistics.median(keeper_ratio) <= 0.2
