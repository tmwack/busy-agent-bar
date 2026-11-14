import pytest
from busylib.types import DisplayElements

from agentbar.config import LayoutConfig
from agentbar.layout import (
    blinking,
    dim,
    initials,
    labels,
    max_agents,
    region_x,
    render,
    select,
    shimmering,
    shown_agents,
)
from agentbar.model import Agent, AgentState, Session


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


def test_initials_default_length():
    n = LayoutConfig().name_chars
    assert [initials(x, n) for x in ("busy-agent-bar", "mcpTenancy", "agentbar", "a-b-c-d-e")] == [
        "bab-",
        "mt--",
        "a---",
        "abcd",
    ]


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
    needs = cfg.colors[AgentState.NEEDS_INPUT]
    assert on["11"]["text"] == "a---" and on["21"]["color"] == needs
    assert off["21"]["color"] == dim(needs, cfg.dim_factor)
    assert off["11"] == on["11"]  # only the NEEDS_INPUT tile blinks
    assert blinking(ss, cfg)


def test_idle_label_brighter_than_bar():
    cfg = LayoutConfig()
    out = render([s("a", "/a", AgentState.IDLE)], cfg)
    assert out["10"]["fill_colors"] == [cfg.colors[AgentState.IDLE]] * 2
    assert out["11"]["color"] == cfg.text_colors[AgentState.IDLE] != cfg.colors[AgentState.IDLE]


def test_hide_idle():
    ss = [s("a", "/a", AgentState.IDLE)]
    assert render(ss, LayoutConfig(show_idle=False)) == {}
    with_agents(ss[0], AgentState.WORKING)  # an idle session with a working agent stays visible
    assert "11" in render(ss, LayoutConfig(show_idle=False))


def with_agents(sess, *states):
    for i, state in enumerate(states):
        sess.agents[f"a{i}"] = Agent(f"a{i}", first_seen=float(i), state=state)
    return sess


def test_agent_squares_sit_on_the_bar():
    cfg = LayoutConfig()
    out = render([with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING, AgentState.WORKING)], cfg)
    squares = [out["12"], out["13"]]
    assert [(e["x"], e["y"], e["width"], e["height"]) for e in squares] == [(16, 12, 2, 2), (19, 12, 2, 2)]
    assert out["10"]["y"] == 14  # squares end where the bar starts
    assert "14" not in out


def test_bar_is_session_label_is_most_active():
    cfg = LayoutConfig()
    out = render([with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING)], cfg)
    assert out["10"]["fill_colors"] == [cfg.colors[AgentState.DONE]] * 2
    assert out["11"]["color"] == cfg.colors[AgentState.WORKING]
    out = render([with_agents(s("a", "/a", AgentState.WORKING), AgentState.NEEDS_INPUT)], cfg)
    assert out["10"]["fill_colors"][0] == cfg.colors[AgentState.WORKING]  # shimmer, bright end first
    assert out["11"]["color"] == cfg.colors[AgentState.NEEDS_INPUT]
    assert out["12"]["fill_colors"] == [cfg.colors[AgentState.NEEDS_INPUT]]


def test_each_element_blinks_on_its_own_state():
    cfg = LayoutConfig()
    ss = [with_agents(s("a", "/a", AgentState.WORKING), AgentState.WORKING, AgentState.NEEDS_INPUT)]
    on, off = render(ss, cfg, blink_on=True), render(ss, cfg, blink_on=False)
    assert blinking(ss, cfg)
    assert off["10"] == on["10"] and off["12"] == on["12"]
    assert off["13"]["fill_colors"] == [dim(cfg.colors[AgentState.NEEDS_INPUT], cfg.dim_factor)]
    assert off["11"]["color"] == dim(cfg.colors[AgentState.NEEDS_INPUT], cfg.dim_factor)


def test_too_many_agents_keeps_most_active_in_order():
    cfg = LayoutConfig()
    assert max_agents(cfg) == 6
    states = [AgentState.WORKING] * 6 + [AgentState.NEEDS_INPUT]
    shown = shown_agents(with_agents(s("a", "/a"), *states), cfg)
    assert [a.agent_id for a in shown] == ["a0", "a1", "a2", "a3", "a4", "a6"]  # a5 is the newest WORKING one


def test_overflow_ranks_by_most_active_state():
    ss = [
        s("a", "/a", AgentState.WORKING, 1),
        with_agents(s("b", "/b", AgentState.DONE, 2), AgentState.NEEDS_INPUT),
        s("c", "/c", AgentState.WORKING, 3),
    ]
    assert [x.session_id for x in select(ss, LayoutConfig(max_tiles=2))] == ["a", "b"]


def test_agent_squares_validate_against_busylib():
    elements = render([with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING)], LayoutConfig())
    DisplayElements.model_validate({"application_name": "agentbar", "elements": list(elements.values())})


def test_working_bar_shimmers():
    cfg = LayoutConfig()
    working = cfg.colors[AgentState.WORKING]
    faded = dim(working, cfg.shimmer_factor)
    ss = [s("a", "/a", AgentState.WORKING)]
    a, b = render(ss, cfg, shimmer_phase=0)["10"], render(ss, cfg, shimmer_phase=1)["10"]
    assert a["fill"] == b["fill"] == "gradient_h"
    assert a["fill_colors"] == [working, faded] and b["fill_colors"] == [faded, working]
    assert shimmering(ss, cfg)


def test_only_working_bars_shimmer():
    cfg = LayoutConfig()
    ss = [
        s("a", "/a", AgentState.DONE, 1),
        s("b", "/b", AgentState.NEEDS_INPUT, 2),
        with_agents(s("c", "/c", AgentState.IDLE, 3), AgentState.WORKING),
    ]
    out = render(ss, cfg, shimmer_phase=1)
    for i in ("10", "20", "30"):  # bars are always gradients, one colour unless WORKING
        assert out[i]["fill"] == "gradient_h" and len(set(out[i]["fill_colors"])) == 1
    assert out["32"]["fill"] == "solid"  # agent squares never shimmer
    assert not shimmering(ss, cfg)


def test_shimmer_off_gives_one_colour_bars():
    cfg = LayoutConfig(shimmer=False)
    ss = [s("a", "/a", AgentState.WORKING)]
    assert render(ss, cfg, shimmer_phase=1)["10"]["fill_colors"] == [cfg.colors[AgentState.WORKING]] * 2
    assert not shimmering(ss, cfg)


def test_shimmer_validates_against_busylib():
    elements = render([s("a", "/a", AgentState.WORKING)], LayoutConfig(), shimmer_phase=1)
    DisplayElements.model_validate({"application_name": "agentbar", "elements": list(elements.values())})


def test_bar_after_shimmer_overwrites_the_gradient():
    # The firmware updates a re-posted rectangle in place, and its solid fill keeps the
    # old gradient; a done bar must therefore be sent as a one-colour gradient.
    cfg = LayoutConfig()
    sess = s("a", "/a", AgentState.WORKING)
    assert len(set(render([sess], cfg)["10"]["fill_colors"])) == 2
    sess.state = AgentState.DONE
    bar = render([sess], cfg)["10"]
    assert bar["fill"] == "gradient_h" and bar["fill_colors"] == [cfg.colors[AgentState.DONE]] * 2
