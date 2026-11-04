import pytest

from agentbar.config import LayoutConfig
from agentbar.layout import blinking, dim, initials, labels, region_x, render, select
from agentbar.model import AgentState, Session


def s(sid, cwd, state=AgentState.WORKING, first=0.0):
    return Session("cc", sid, first_seen=first, last_event=first, state=state, cwd=cwd)


def test_region_right_aligned_by_default():
    assert region_x(LayoutConfig()) == 72 - (3 * 18 + 2)


def test_region_must_fit():
    with pytest.raises(ValueError):
        region_x(LayoutConfig(max_tiles=4, tile_width=20))


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("istari-rfc-equivalency", "ire"),
        ("busy-agent-bar", "bab"),
        ("mcpTenancy", "mt-"),
        ("agentbar", "a--"),
        ("snake_case_name", "scn"),
        ("Fix auth bug", "fab"),
        ("HTTPServer", "hs-"),
        ("getHTTPResponse", "ghr"),
        ("one-two-three-four", "ott"),
        ("API", "a--"),
    ],
)
def test_initials(name, label):
    assert initials(name, 3) == label


def test_labels_prefer_title_and_dedupe():
    named = s("a", "/w/agentbar")
    named.title = "Fix auth bug"
    ss = [named, s("b", "/w/busy-agent-bar"), s("c", "/x/busy-agent-bar")]
    assert labels(ss, 3) == ["fab", "ba1", "ba2"]


def test_overflow_prefers_higher_priority_keeps_order():
    ss = [
        s("a", "/a", AgentState.IDLE, 1),
        s("b", "/b", AgentState.NEEDS_INPUT, 2),
        s("c", "/c", AgentState.WORKING, 3),
    ]
    assert [x.session_id for x in select(ss, LayoutConfig(max_tiles=2))] == ["b", "c"]


def test_render_positions_and_blink():
    cfg = LayoutConfig()
    ss = [s("a", "/w/api", AgentState.WORKING, 1), s("b", "/w/web", AgentState.NEEDS_INPUT, 2)]
    on = render(ss, cfg, blink_on=True)
    off = render(ss, cfg, blink_on=False)
    assert on["11"]["x"] == 16 and on["21"]["x"] == 35
    assert on["11"]["text"] == "a--" and on["21"]["color"] == "#FF1E1E"
    assert off["21"]["color"] == dim("#FF1E1E", cfg.dim_factor)
    assert off["11"] == on["11"]  # only the NEEDS_INPUT tile blinks
    assert blinking(ss, cfg)


def test_hide_idle():
    ss = [s("a", "/a", AgentState.IDLE)]
    assert render(ss, LayoutConfig(show_idle=False)) == {}
