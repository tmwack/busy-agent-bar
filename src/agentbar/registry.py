"""Session registry: applies events, decays DONE -> IDLE, drops dead sessions."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from .model import Agent, AgentEvent, AgentState, EventKind, Session

log = logging.getLogger(__name__)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Registry:
    def __init__(
        self,
        done_decay_s: float,
        session_ttl_s: float,
        is_alive: Callable[[int], bool] = pid_alive,
    ) -> None:
        self.done_decay_s = done_decay_s
        self.session_ttl_s = session_ttl_s
        self._is_alive = is_alive
        self._sessions: dict[tuple[str, str], Session] = {}

    def apply(self, ev: AgentEvent) -> bool:
        """Apply one event. Returns True if anything visible changed."""
        key = (ev.source, ev.session_id)
        if ev.kind is EventKind.END and ev.agent_id is None:
            gone = self._sessions.pop(key, None) is not None
            if gone:
                log.info("session end %s", ev.session_id)
            return gone

        session = self._sessions.get(key)
        changed = session is None
        if session is None:
            session = Session(
                source=ev.source,
                session_id=ev.session_id,
                first_seen=ev.ts,
                last_event=ev.ts,
                state_since=ev.ts,
            )
            self._sessions[key] = session
            log.info("session start %s cwd=%s", ev.session_id, ev.cwd)

        session.last_event = max(session.last_event, ev.ts)
        if ev.cwd and ev.cwd != session.cwd:
            session.cwd = ev.cwd
            changed = True
        if ev.title and ev.title != session.title:
            session.title = ev.title
            changed = True
        if ev.pid:
            session.pid = ev.pid
        if ev.agent_id is not None:
            return self._apply_agent(session, ev) or changed
        if ev.agents_idle and session.agents:
            log.info("session %s: nothing in flight, clearing %d agent(s)", ev.session_id, len(session.agents))
            session.agents.clear()
            changed = True

        # Hooks for parallel tool calls can arrive slightly out of order;
        # never let an older state event overwrite a newer one.
        if ev.kind is EventKind.STATE and ev.state is not None and ev.ts >= session.last_state_ts:
            session.last_state_ts = ev.ts
            session.detail = ev.detail
            if ev.state != session.state:
                log.info("session %s %s -> %s", ev.session_id, session.state.name, ev.state.name)
                session.state = ev.state
                session.state_since = ev.ts
                changed = True
        return changed

    def _apply_agent(self, session: Session, ev: AgentEvent) -> bool:
        """Events from a subagent change that agent, never the session's own state."""
        if ev.kind is EventKind.END:
            gone = session.agents.pop(ev.agent_id, None) is not None
            if gone:
                log.info("session %s agent %s end", session.session_id, ev.agent_id)
            return gone
        if ev.kind is not EventKind.STATE or ev.state is None:
            return False
        agent = session.agents.get(ev.agent_id)
        if agent is None:
            # Usually SubagentStart; also covers a missed start or a daemon restart.
            agent = Agent(ev.agent_id, first_seen=ev.ts, state=ev.state, last_state_ts=ev.ts, agent_type=ev.agent_type)
            session.agents[ev.agent_id] = agent
            log.info("session %s agent %s (%s) %s", session.session_id, ev.agent_id, ev.agent_type, ev.state.name)
            return True
        if ev.ts < agent.last_state_ts:
            return False
        agent.last_state_ts = ev.ts
        if ev.state is agent.state:
            return False
        log.info("session %s agent %s %s -> %s", session.session_id, ev.agent_id, agent.state.name, ev.state.name)
        agent.state = ev.state
        return True

    def tick(self, now: float) -> bool:
        """Time-based transitions. Returns True if anything visible changed."""
        changed = False
        for key, s in list(self._sessions.items()):
            dead = (s.pid is not None and not self._is_alive(s.pid)) or (
                s.pid is None and now - s.last_event > self.session_ttl_s
            )
            if dead:
                log.info("session expired %s", s.session_id)
                del self._sessions[key]
                changed = True
                continue
            if s.state is AgentState.DONE and now - s.state_since >= self.done_decay_s:
                s.state = AgentState.IDLE
                s.state_since = now
                changed = True
        return changed

    def sessions(self) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.first_seen)
