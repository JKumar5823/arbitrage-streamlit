"""Altair charts for the dashboard.

Colour choices follow one rule each: bar/line charts carry a single series, so
they use one hue and let position do the work; the heatmap encodes continuous
magnitude, so it uses a one-hue light-to-dark ramp. No chart uses two y-scales,
and every chart has a table-view twin in the UI so no value is reachable only by
hovering.

The eight-stage funnel deliberately uses one hue rather than an ordinal ramp:
this ramp only fits four steps before adjacent lightness gaps close up, and the
funnel's order is already carried by bar position and direct labels.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Values from the validated reference palette. Dark is the same hues re-stepped
# for the dark surface, not an automatic flip.
PALETTES: dict[str, dict[str, Any]] = {
    "light": {
        "surface": "#fcfcfb",
        "series": "#2a78d6",
        "text": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "good": "#0ca30c",
        "critical": "#d03b3b",
        "warning": "#fab219",
        # Continuous ramp, light -> dark, single hue.
        "ramp": ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
    },
    "dark": {
        "surface": "#1a1a19",
        "series": "#3987e5",
        "text": "#ffffff",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "good": "#0ca30c",
        "critical": "#d03b3b",
        "warning": "#fab219",
        # On a dark surface the ramp runs dark -> light so "more" reads brighter.
        "ramp": ["#0d366b", "#184f95", "#256abf", "#3987e5", "#5598e7", "#86b6ef", "#cde2fb"],
    },
}


def palette(mode: str = "light") -> dict[str, Any]:
    return PALETTES.get(mode, PALETTES["light"])


def active_mode() -> str:
    """Match the viewer's Streamlit theme when it can be read."""
    try:
        import streamlit as st
        from streamlit.runtime import exists as runtime_exists

        if not runtime_exists():        # imported outside a script run (tests, CLI)
            return "light"
        kind = getattr(getattr(st, "context", None), "theme", None)
        kind = getattr(kind, "type", None)
        if kind in ("light", "dark"):
            return kind
    except Exception:
        pass
    return "light"


def _style(chart: alt.Chart, mode: str) -> alt.Chart:
    """Recessive chrome: hairline grid, muted labels, no view border."""
    colors = palette(mode)
    return (
        chart
        .configure_view(strokeWidth=0, fill=colors["surface"])
        .configure_axis(
            labelFont=FONT, titleFont=FONT,
            labelColor=colors["muted"], titleColor=colors["secondary"],
            labelFontSize=11, titleFontSize=11, titlePadding=10,
            domainColor=colors["axis"], tickColor=colors["axis"],
            gridColor=colors["grid"], gridWidth=1, tickSize=4,
        )
        .configure_legend(
            labelFont=FONT, titleFont=FONT,
            labelColor=colors["secondary"], titleColor=colors["secondary"],
            labelFontSize=11, titleFontSize=11, symbolType="square", symbolSize=110,
        )
        .configure_title(font=FONT, fontSize=13, anchor="start",
                         color=colors["text"], fontWeight=600, offset=12)
        .configure_text(font=FONT)
    )


def _empty(message: str, mode: str) -> alt.Chart:
    colors = palette(mode)
    return (
        alt.Chart(pd.DataFrame({"m": [message]}))
        .mark_text(align="center", font=FONT, fontSize=12, color=colors["muted"])
        .encode(text="m:N")
        .properties(height=140)
    )


# --- Charts ------------------------------------------------------------------

def weekly_volume_chart(data: pd.DataFrame, mode: str | None = None,
                        height: int = 260) -> alt.Chart:
    """Conversations per week. One series, so one hue and no legend."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty:
        return _empty("No conversations in this range yet", mode)

    order = data["label"].tolist()
    base = alt.Chart(data).encode(
        x=alt.X("label:N", sort=order, title=None,
                axis=alt.Axis(labelAngle=0, labelOverlap="greedy", labelSeparation=8,
                              labelPadding=6),
                scale=alt.Scale(paddingInner=0.34, paddingOuter=0.16)),
        y=alt.Y("conversations:Q", title="Conversations",
                axis=alt.Axis(grid=True, tickCount=5, format="d")),
        tooltip=[alt.Tooltip("label:N", title="Week of"),
                 alt.Tooltip("conversations:Q", title="Conversations", format="d")],
    )
    bars = base.mark_bar(color=colors["series"], cornerRadiusEnd=4)

    # Direct-label the peak and the most recent week only; the rest read off the
    # axis and the tooltip, and every value is in the table view.
    peak = int(data["conversations"].max())
    highlight = data[(data["conversations"] == peak)
                     | (data["label"] == data["label"].iloc[-1])]
    labels = (
        alt.Chart(highlight[highlight["conversations"] > 0])
        .mark_text(dy=-8, font=FONT, fontSize=11, fontWeight=600,
                   color=colors["secondary"])
        .encode(x=alt.X("label:N", sort=order),
                y=alt.Y("conversations:Q"),
                text=alt.Text("conversations:Q", format="d"))
    )
    return _style((bars + labels).properties(height=height), mode)


def cumulative_chart(data: pd.DataFrame, target: int | None = None,
                     mode: str | None = None, height: int = 260) -> alt.Chart:
    """Running total of conversations, with an optional goal line."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty:
        return _empty("No conversations in this range yet", mode)

    line = alt.Chart(data).mark_line(
        color=colors["series"], strokeWidth=2, interpolate="monotone"
    ).encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(grid=False, format="%b %d")),
        y=alt.Y("total:Q", title="Cumulative conversations",
                axis=alt.Axis(grid=True, tickCount=5, format="d")),
    )
    # A transparent wide-mark layer gives the crosshair a forgiving hit target.
    hover = alt.Chart(data).mark_point(size=200, opacity=0).encode(
        x=alt.X("date:T"), y=alt.Y("total:Q"),
        tooltip=[alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                 alt.Tooltip("total:Q", title="Running total", format="d"),
                 alt.Tooltip("conversations:Q", title="That day", format="d")],
    )
    endpoint = alt.Chart(data.tail(1)).mark_point(
        size=90, filled=True, color=colors["series"],
        stroke=colors["surface"], strokeWidth=2,
    ).encode(x="date:T", y="total:Q")
    endpoint_label = alt.Chart(data.tail(1)).mark_text(
        dx=-6, dy=-14, align="right", font=FONT, fontSize=11, fontWeight=600,
        color=colors["secondary"],
    ).encode(x="date:T", y="total:Q", text=alt.Text("total:Q", format="d"))

    layers = [line, hover, endpoint, endpoint_label]
    reached = float(data["total"].max() or 0)
    # A goal far above the current total would flatten the line against the
    # x-axis and read as a border across the top. The progress bar above the
    # charts already carries "x of y", so the rule only earns its place once the
    # series is within reach of it.
    if target and reached >= float(target) * 0.6:
        goal = pd.DataFrame({"y": [target]})
        layers.insert(0, alt.Chart(goal).mark_rule(
            color=colors["muted"], strokeWidth=1).encode(y="y:Q"))
        layers.append(alt.Chart(goal).mark_text(
            text=f"Goal {target}", align="left", dx=8, dy=-8, x=0,
            font=FONT, fontSize=11, color=colors["muted"],
        ).encode(y="y:Q"))
    return _style(alt.layer(*layers).properties(height=height), mode)


def funnel_chart(data: pd.DataFrame, mode: str | None = None,
                 height: int = 300) -> alt.Chart:
    """Investors that reached each stage. Order is positional, so one hue."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty or data["investors"].sum() == 0:
        return _empty("No investors with a stage recorded yet", mode)

    order = data.sort_values("order")["stage"].tolist()
    frame = data.copy()
    frame["caption"] = frame.apply(
        lambda r: f"{int(r['investors'])}  ({r['conversion']:.0%})", axis=1)

    bars = alt.Chart(frame).mark_bar(
        color=colors["series"], cornerRadiusEnd=4,
    ).encode(
        y=alt.Y("stage:N", sort=order, title=None,
                scale=alt.Scale(paddingInner=0.34, paddingOuter=0.16),
                axis=alt.Axis(labelLimit=140)),
        x=alt.X("investors:Q", title="Investors reaching this stage",
                axis=alt.Axis(grid=True, tickCount=5, format="d")),
        tooltip=[alt.Tooltip("stage:N", title="Stage"),
                 alt.Tooltip("investors:Q", title="Investors", format="d"),
                 alt.Tooltip("conversion:Q", title="Share of all investors", format=".0%")],
    )
    # Labels sit outside the bar end, so a short bar never clips its own label.
    labels = alt.Chart(frame).mark_text(
        align="left", dx=6, font=FONT, fontSize=11, color=colors["secondary"],
    ).encode(y=alt.Y("stage:N", sort=order), x=alt.X("investors:Q"), text="caption:N")
    return _style((bars + labels).properties(height=height), mode)


def by_person_chart(data: pd.DataFrame, mode: str | None = None,
                    height: int | None = None) -> alt.Chart:
    """Conversations per team member. Nominal categories, so one hue."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty:
        return _empty("No one has logged a conversation yet", mode)

    frame = data.sort_values("conversations", ascending=False)
    order = frame["person"].tolist()
    height = height or max(140, 34 * len(frame) + 20)

    bars = alt.Chart(frame).mark_bar(
        color=colors["series"], cornerRadiusEnd=4,
    ).encode(
        y=alt.Y("person:N", sort=order, title=None,
                scale=alt.Scale(paddingInner=0.3, paddingOuter=0.15),
                axis=alt.Axis(labelLimit=160)),
        x=alt.X("conversations:Q", title="Conversations",
                axis=alt.Axis(grid=True, tickCount=5, format="d")),
        tooltip=[alt.Tooltip("person:N", title="Person"),
                 alt.Tooltip("conversations:Q", title="Conversations", format="d"),
                 alt.Tooltip("investors:Q", title="Distinct investors", format="d"),
                 alt.Tooltip("committed:Q", title="Commitments", format="d")],
    )
    labels = alt.Chart(frame).mark_text(
        align="left", dx=6, font=FONT, fontSize=11, fontWeight=600,
        color=colors["secondary"],
    ).encode(y=alt.Y("person:N", sort=order), x=alt.X("conversations:Q"),
             text=alt.Text("conversations:Q", format="d"))
    return _style((bars + labels).properties(height=height), mode)


ROW_HEIGHT = 34
# Room for the x-axis band beneath the plot. Sizing the container to plot +
# chrome stops the axis from being squeezed out of a fixed-height card.
AXIS_BAND = 56


def heatmap_plot_height(data: pd.DataFrame) -> int:
    people = data["person"].nunique() if not data.empty else 1
    return max(ROW_HEIGHT * 2, ROW_HEIGHT * int(people))


def heatmap_height(data: pd.DataFrame) -> int:
    """Container height for the heatmap, including its axis band."""
    if data.empty:
        return 160
    return heatmap_plot_height(data) + AXIS_BAND


def activity_heatmap(data: pd.DataFrame, mode: str | None = None) -> alt.Chart:
    """Person x week intensity. Continuous magnitude, so a one-hue ramp."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty:
        return _empty("Not enough history for a heatmap yet", mode)

    weeks = (data.sort_values("week")["label"].drop_duplicates().tolist())
    people = sorted(data["person"].unique().tolist())
    plot_height = heatmap_plot_height(data)

    return _style(
        alt.Chart(data).mark_rect(
            # A ring in the surface colour is the 2px gap, not a border.
            stroke=colors["surface"], strokeWidth=2, cornerRadius=3,
        ).encode(
            x=alt.X("label:N", sort=weeks, title=None,
                    axis=alt.Axis(labelAngle=0, labelOverlap="greedy",
                                  labelSeparation=8, grid=False)),
            y=alt.Y("person:N", sort=people, title=None,
                    axis=alt.Axis(labelLimit=160, grid=False)),
            color=alt.Color(
                "conversations:Q", title="Conversations",
                scale=alt.Scale(range=colors["ramp"], type="linear"),
                # Kept beside the plot rather than beneath it: a bottom legend
                # competes with the rows for the container's height and
                # collapses them.
                legend=alt.Legend(orient="right", direction="vertical",
                                  gradientLength=max(80, plot_height - 20),
                                  format="d"),
            ),
            tooltip=[alt.Tooltip("person:N", title="Person"),
                     alt.Tooltip("label:N", title="Week of"),
                     alt.Tooltip("conversations:Q", title="Conversations", format="d")],
        ).properties(height=plot_height),
        mode,
    )


def sparkline(data: pd.DataFrame, mode: str | None = None, height: int = 44) -> alt.Chart:
    """A bare trend line for a stat tile. No axes, no legend, no tooltip."""
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty:
        return _empty("", mode)
    return (
        alt.Chart(data)
        .mark_area(line={"color": colors["series"], "strokeWidth": 2},
                   color=alt.Gradient(
                       gradient="linear",
                       stops=[alt.GradientStop(color=colors["surface"], offset=0),
                              alt.GradientStop(color=colors["series"], offset=1)],
                       x1=1, x2=1, y1=1, y2=0),
                   opacity=0.25, interpolate="monotone")
        .encode(x=alt.X("label:N", sort=data["label"].tolist(), axis=None),
                y=alt.Y("conversations:Q", axis=None))
        .properties(height=height)
        .configure_view(strokeWidth=0, fill=colors["surface"])
    )


def lead_funnel_chart(data: pd.DataFrame, mode: str | None = None,
                      height: int | None = None) -> alt.Chart:
    """Leads reaching each canonical step, with step-to-step conversion.

    One hue: the funnel's order is carried by bar position and direct labels,
    and bar length already encodes the count.
    """
    mode = mode or active_mode()
    colors = palette(mode)
    if data.empty or data["leads"].sum() == 0:
        return _empty("No pipeline imported yet", mode)

    order = data.sort_values("rank")["label"].tolist()
    frame = data.copy()
    frame["caption"] = frame.apply(
        lambda r: f"{int(r['leads']):,}   {r['conversion']:.0%}", axis=1)
    height = height or max(220, 34 * len(frame) + 30)

    bars = alt.Chart(frame).mark_bar(
        color=colors["series"], cornerRadiusEnd=4,
    ).encode(
        y=alt.Y("label:N", sort=order, title=None,
                scale=alt.Scale(paddingInner=0.34, paddingOuter=0.16),
                axis=alt.Axis(labelLimit=150)),
        x=alt.X("leads:Q", title="Leads reaching this step",
                axis=alt.Axis(grid=True, tickCount=5, format="d")),
        tooltip=[alt.Tooltip("label:N", title="Step"),
                 alt.Tooltip("leads:Q", title="Leads", format=","),
                 alt.Tooltip("conversion:Q", title="From previous step", format=".0%"),
                 alt.Tooltip("share:Q", title="Of all outreach", format=".0%"),
                 alt.Tooltip("rule:N", title="Counted as")],
    )
    labels = alt.Chart(frame).mark_text(
        align="left", dx=6, font=FONT, fontSize=11, color=colors["secondary"],
    ).encode(y=alt.Y("label:N", sort=order), x=alt.X("leads:Q"), text="caption:N")
    return _style((bars + labels).properties(height=height), mode)
