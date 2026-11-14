import pytest

from agentbar.daemon import FRAME_SLACK_S, next_boundary


@pytest.mark.parametrize(
    ("mono", "period", "wait"),
    [(10.2, 0.5, 0.3), (10.0, 1.0, 1.0), (10.99, 1.0, 0.01), (3.75, 0.5, 0.25)],
)
def test_next_boundary_wakes_just_after_the_frame(mono, period, wait):
    assert next_boundary(mono, period) == pytest.approx(wait + FRAME_SLACK_S)


def test_boundaries_of_different_animations_coincide():
    # Blink (0.5 s) and bounce (1 s) share one clock origin, so every bounce frame is
    # also a blink frame and both changes go out in one draw.
    mono = 41.37
    bounce_frame = mono + next_boundary(mono, 1.0) - FRAME_SLACK_S
    assert (bounce_frame / 0.5) == pytest.approx(round(bounce_frame / 0.5))
