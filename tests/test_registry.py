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
