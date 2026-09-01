"""Charts are validated structurally: every spec must build, and the colour
choices must stay inside the validated palette."""

import altair as alt
import pandas as pd
import pytest

from fundraising import charts, metrics

SAMPLE = pd.DataFrame([
    {"id": 1, "occurred_on": "2026-08-01", "person": "Jay", "investor": "Acme",
     "stage": "First Meeting", "channel": "Meeting", "amount": None,
     "next_step": None, "next_step_due": None, "counterpart": None, "notes": None,
     "source": "manual"},
    {"id": 2, "occurred_on": "2026-08-09", "person": "Sam", "investor": "Beta",
     "stage": "Committed", "channel": "Meeting", "amount": 500000,
     "next_step": None, "next_step_due": None, "counterpart": None, "notes": None,
     "source": "manual"},
])

EMPTY = pd.DataFrame()


def test_all_charts_build():
    specs = [
        charts.weekly_volume_chart(metrics.weekly_volume(SAMPLE)),
        charts.cumulative_chart(metrics.cumulative(SAMPLE), target=50),
        charts.funnel_chart(metrics.funnel(SAMPLE)),
        charts.by_person_chart(metrics.by_person(SAMPLE)),
        charts.activity_heatmap(metrics.person_week_matrix(SAMPLE)),
        charts.sparkline(metrics.weekly_volume(SAMPLE)),
    ]
    for spec in specs:
        assert isinstance(spec.to_dict(), dict)


@pytest.mark.parametrize("fn", [
    charts.weekly_volume_chart, charts.cumulative_chart, charts.funnel_chart,
    charts.by_person_chart, charts.activity_heatmap, charts.sparkline,
])
def test_charts_render_an_empty_state(fn):
    assert isinstance(fn(EMPTY).to_dict(), dict)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_both_themes_are_fully_specified(mode):
    """A missing role would silently fall back to a Vega default."""
    required = {"surface", "series", "text", "secondary", "muted", "grid", "axis", "ramp"}
    assert required <= set(charts.palette(mode))


def test_no_chart_uses_two_y_scales():
    """Dual-axis charts invent correlations; the layered chart must share one y."""
    spec = charts.cumulative_chart(metrics.cumulative(SAMPLE), target=50).to_dict()
    scales = {
        enc["scale"].get("domain") if isinstance(enc.get("scale"), dict) else None
        for layer in spec.get("layer", [])
        for key, enc in layer.get("encoding", {}).items() if key == "y"
    }
    assert len(scales) == 1


def test_ramp_is_monotone_in_lightness():
    """A sequential ramp must read light-to-dark (or dark-to-light) throughout."""
    def luminance(hexcolor: str) -> float:
        r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light = [luminance(c) for c in charts.palette("light")["ramp"]]
    dark = [luminance(c) for c in charts.palette("dark")["ramp"]]
    assert light == sorted(light, reverse=True)
    assert dark == sorted(dark)


def test_single_series_charts_carry_no_legend():
    """One series needs no legend box; the title names it."""
    spec = charts.weekly_volume_chart(metrics.weekly_volume(SAMPLE)).to_dict()
    assert "color" not in spec["layer"][0].get("encoding", {})


def test_every_chart_has_tooltips():
    for spec in (charts.weekly_volume_chart(metrics.weekly_volume(SAMPLE)),
                 charts.funnel_chart(metrics.funnel(SAMPLE)),
                 charts.by_person_chart(metrics.by_person(SAMPLE)),
                 charts.activity_heatmap(metrics.person_week_matrix(SAMPLE))):
        assert "tooltip" in str(spec.to_dict())
