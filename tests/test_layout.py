import pytest
from busylib.types import DisplayElements

from agentbar.config import LayoutConfig
from agentbar.layout import (
    OFF,
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
    assert on["101"]["x"] == 16 and on["201"]["x"] == 35
    needs = cfg.colors[AgentState.NEEDS_INPUT]
    assert on["101"]["text"] == "a---" and on["201"]["color"] == needs
    assert off["201"]["color"] == dim(needs, cfg.dim_factor)
    assert off["101"] == on["101"]  # only the NEEDS_INPUT tile blinks
    assert blinking(ss, cfg)


def test_idle_label_brighter_than_bar():
    cfg = LayoutConfig()
    out = render([s("a", "/a", AgentState.IDLE)], cfg)
    assert out["100"]["fill_colors"] == [cfg.colors[AgentState.IDLE]] * 2
    assert out["101"]["color"] == cfg.text_colors[AgentState.IDLE] != cfg.colors[AgentState.IDLE]


def test_hide_idle():
    ss = [s("a", "/a", AgentState.IDLE)]
    assert render(ss, LayoutConfig(show_idle=False)) == {}
    with_agents(ss[0], AgentState.WORKING)  # an idle session with a working agent stays visible
    assert "101" in render(ss, LayoutConfig(show_idle=False))


def with_agents(sess, *states):
    for i, state in enumerate(states):
        sess.agents[f"a{i}"] = Agent(f"a{i}", first_seen=float(i), state=state)
    return sess


def test_agent_squares_sit_on_the_bar():
    cfg = LayoutConfig()
    out = render([with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING, AgentState.WORKING)], cfg)
    squares = [out["110"], out["111"]]
    assert [(e["x"], e["y"], e["width"], e["height"]) for e in squares] == [(16, 12, 2, 2), (19, 12, 2, 2)]
    assert out["100"]["y"] == 14  # squares end where the bar starts
    assert "112" not in out


def test_bar_is_session_label_is_most_active():
    cfg = LayoutConfig()
    out = render([with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING)], cfg)
    assert out["100"]["fill_colors"] == [cfg.colors[AgentState.DONE]] * 2
    assert out["101"]["color"] == cfg.colors[AgentState.WORKING]
    out = render([with_agents(s("a", "/a", AgentState.WORKING), AgentState.NEEDS_INPUT)], cfg)
    assert out["102"]["fill_colors"] == [cfg.colors[AgentState.WORKING]]  # end cap of the working bar
    assert out["101"]["color"] == cfg.colors[AgentState.NEEDS_INPUT]
    assert out["110"]["fill_colors"] == [cfg.colors[AgentState.NEEDS_INPUT]]


def test_each_element_blinks_on_its_own_state():
    cfg = LayoutConfig()
    ss = [with_agents(s("a", "/a", AgentState.WORKING), AgentState.WORKING, AgentState.NEEDS_INPUT)]
    on, off = render(ss, cfg, blink_on=True), render(ss, cfg, blink_on=False)
    assert blinking(ss, cfg)
    assert off["100"] == on["100"] and off["110"] == on["110"]
    assert off["111"]["fill_colors"] == [dim(cfg.colors[AgentState.NEEDS_INPUT], cfg.dim_factor)]
    assert off["101"]["color"] == dim(cfg.colors[AgentState.NEEDS_INPUT], cfg.dim_factor)


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


def test_working_bar_bounces_between_end_caps():
    cfg = LayoutConfig()
    working = cfg.colors[AgentState.WORKING]
    ss = [s("a", "/a", AgentState.WORKING)]
    frames = [render(ss, cfg, shimmer_phase=p) for p in range(7)]
    for f in frames:
        assert f["100"]["fill"] == "gradient_h" and f["100"]["fill_colors"] == [OFF, OFF]
        assert (f["102"]["x"], f["103"]["x"], f["102"]["width"]) == (16, 33, 1)  # caps on the outer columns
        assert f["102"]["fill_colors"] == f["104"]["fill_colors"] == [working]
    # Segment: four stops, bouncing 1-2-3-4-3-2, then wraps; it touches a cap at either end.
    assert [f["104"]["x"] - 16 for f in frames] == [1, 5, 8, 12, 8, 5, 1]  # steps 4-3-4, symmetric
    assert frames[3]["104"]["x"] + cfg.shimmer_width == frames[3]["103"]["x"]
    assert frames[0]["104"]["width"] == cfg.shimmer_width
    assert shimmering(ss, cfg)


def test_working_agent_pixel_steps_clockwise():
    cfg = LayoutConfig()
    working = cfg.colors[AgentState.WORKING]
    ss = [with_agents(s("a", "/a", AgentState.DONE), AgentState.WORKING)]
    frames = [render(ss, cfg, shimmer_phase=p) for p in range(4)]
    assert {tuple(f["110"]["fill_colors"]) for f in frames} == {(dim(working, cfg.shimmer_factor),)}
    corner = [(f["120"]["x"] - 16, f["120"]["y"] - 12) for f in frames]
    assert corner == [(0, 0), (1, 0), (1, 1), (0, 1)]  # top left, top right, bottom right, bottom left
    assert all(f["120"]["fill_colors"] == [working] and f["120"]["width"] == 1 for f in frames)
    assert shimmering(ss, cfg)  # the agent works even though the session is done


def test_only_working_elements_move():
    cfg = LayoutConfig()
    ss = [
        s("a", "/a", AgentState.DONE, 1),
        with_agents(s("b", "/b", AgentState.NEEDS_INPUT, 2), AgentState.NEEDS_INPUT),
        s("c", "/c", AgentState.IDLE, 3),
    ]
    out = render(ss, cfg, shimmer_phase=1)
    for i in ("100", "200", "300"):  # bars are always gradients, one colour unless WORKING
        assert out[i]["fill"] == "gradient_h" and len(set(out[i]["fill_colors"])) == 1
    assert not {"102", "104", "202", "204", "220"} & out.keys()
    assert out["210"]["fill_colors"] == [cfg.colors[AgentState.NEEDS_INPUT]]
    assert not shimmering(ss, cfg)


def test_shimmer_off_gives_one_colour_bars():
    cfg = LayoutConfig(shimmer=False)
    ss = [s("a", "/a", AgentState.WORKING)]
    assert render(ss, cfg, shimmer_phase=1)["100"]["fill_colors"] == [cfg.colors[AgentState.WORKING]] * 2
    assert not shimmering(ss, cfg)


def test_shimmer_validates_against_busylib():
    ss = [with_agents(s("a", "/a", AgentState.WORKING), AgentState.WORKING)]
    elements = render(ss, LayoutConfig(), shimmer_phase=1)
    DisplayElements.model_validate({"application_name": "agentbar", "elements": list(elements.values())})


def test_bar_after_shimmer_overwrites_the_gradient():
    # The firmware updates a re-posted rectangle in place, and its solid fill keeps the
    # old gradient; a done bar must therefore be sent as a one-colour gradient.
    cfg = LayoutConfig()
    sess = s("a", "/a", AgentState.WORKING)
    assert "104" in render([sess], cfg)  # bouncing segment while working
    sess.state = AgentState.DONE
    out = render([sess], cfg)
    assert out["100"]["fill"] == "gradient_h" and out["100"]["fill_colors"] == [cfg.colors[AgentState.DONE]] * 2
    assert not {"102", "103", "104"} & out.keys()  # caps and segment are removed
