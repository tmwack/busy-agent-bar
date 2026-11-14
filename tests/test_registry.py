from agentbar.model import AgentEvent, AgentState, EventKind
from agentbar.registry import Registry


def st(state, ts, sid="s1", pid=None):
    return AgentEvent("cc", sid, EventKind.STATE, ts, state=state, cwd="/w/p", pid=pid)


def test_lifecycle_and_end():
    r = Registry(done_decay_s=300, session_ttl_s=7200)
    assert r.apply(st(AgentState.WORKING, 1))
    assert not r.apply(st(AgentState.WORKING, 2))
    assert r.apply(st(AgentState.DONE, 3))
    assert r.apply(AgentEvent("cc", "s1", EventKind.END, 4))
    assert r.sessions() == []


def test_title_kept_when_later_events_omit_it():
    r = Registry(300, 7200)
    r.apply(AgentEvent("cc", "s1", EventKind.STATE, 1, state=AgentState.WORKING, title="Fix auth bug"))
    r.apply(st(AgentState.DONE, 2))
    assert r.sessions()[0].title == "Fix auth bug"


def test_out_of_order_state_ignored():
    r = Registry(300, 7200)
    r.apply(st(AgentState.NEEDS_INPUT, 10))
    r.apply(st(AgentState.WORKING, 9))
    assert r.sessions()[0].state is AgentState.NEEDS_INPUT


def test_done_decays_to_idle():
    r = Registry(done_decay_s=300, session_ttl_s=7200)
    r.apply(st(AgentState.DONE, 100))
    assert not r.tick(399)
    assert r.tick(400)
    assert r.sessions()[0].state is AgentState.IDLE


def test_dead_pid_removed_and_ttl():
    alive = {42: True}
    r = Registry(300, session_ttl_s=100, is_alive=lambda p: alive.get(p, False))
    r.apply(st(AgentState.WORKING, 1, sid="a", pid=42))
    r.apply(st(AgentState.WORKING, 1, sid="b"))
    r.tick(50)
    assert len(r.sessions()) == 2
    alive[42] = False
    r.tick(150)  # a: pid dead; b: no pid, past ttl
    assert r.sessions() == []


def test_long_working_with_pid_not_expired():
    r = Registry(300, session_ttl_s=100, is_alive=lambda p: True)
    r.apply(st(AgentState.WORKING, 1, pid=7))
    r.tick(10_000)
    assert r.sessions()[0].state is AgentState.WORKING


def ag(state, ts, agent_id="a1", kind=EventKind.STATE):
    return AgentEvent("cc", "s1", kind, ts, state=state, agent_id=agent_id, agent_type="Explore")


def test_agent_events_leave_session_state_alone():
    r = Registry(300, 7200)
    r.apply(st(AgentState.DONE, 1))
    assert r.apply(ag(AgentState.WORKING, 2))  # SubagentStart / background tool call
    s = r.sessions()[0]
    assert s.state is AgentState.DONE
    assert s.agents["a1"].state is AgentState.WORKING and s.agents["a1"].agent_type == "Explore"
    assert s.top_state is AgentState.WORKING


def test_agent_lifecycle_and_unknown_stop():
    r = Registry(300, 7200)
    r.apply(st(AgentState.WORKING, 1))
    r.apply(ag(AgentState.WORKING, 2))
    assert not r.apply(ag(AgentState.WORKING, 3))
    assert r.apply(ag(AgentState.NEEDS_INPUT, 4))
    assert r.apply(ag(None, 5, kind=EventKind.END))
    assert not r.apply(ag(None, 6, agent_id="internal", kind=EventKind.END))
    s = r.sessions()[0]  # an agent END never ends the session
    assert s.agents == {} and s.state is AgentState.WORKING


def test_agent_out_of_order_state_ignored():
    r = Registry(300, 7200)
    r.apply(ag(AgentState.NEEDS_INPUT, 10))
    assert not r.apply(ag(AgentState.WORKING, 9))
    assert r.sessions()[0].agents["a1"].state is AgentState.NEEDS_INPUT


def test_stop_with_nothing_in_flight_clears_agents():
    r = Registry(300, 7200)
    r.apply(ag(AgentState.WORKING, 1))
    r.apply(st(AgentState.DONE, 2))
    assert r.sessions()[0].agents  # Stop without background info keeps them
    assert r.apply(AgentEvent("cc", "s1", EventKind.STATE, 3, state=AgentState.DONE, agents_idle=True))
    assert r.sessions()[0].agents == {}
