import pytest

from agentbar.config import DEFAULT_TEXT_COLORS, load
from agentbar.model import AgentState


def test_text_colors_override_and_keep_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[layout.text_colors]\nworking = "#FFFFFF"\n')
    cfg = load(path)
    assert cfg.layout.text_colors[AgentState.WORKING] == "#FFFFFF"
    assert cfg.layout.text_colors[AgentState.IDLE] == DEFAULT_TEXT_COLORS[AgentState.IDLE]


def test_text_colors_must_be_hex(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[layout.text_colors]\nidle = "grey"\n')
    with pytest.raises(ValueError, match="text_colors"):
        load(path)


def test_shimmer_can_be_turned_off(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[layout]\nshimmer = false\n[timing]\nshimmer_period_s = 4.0\n")
    cfg = load(path)
    assert cfg.layout.shimmer is False and cfg.timing.shimmer_period_s == 4.0
