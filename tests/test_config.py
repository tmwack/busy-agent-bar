import pytest

from agentbar.config import load
from agentbar.model import AgentState


def test_text_colors_override_and_keep_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[layout.text_colors]\nworking = "#FFFFFF"\n')
    cfg = load(path)
    assert cfg.layout.text_colors[AgentState.WORKING] == "#FFFFFF"
    assert cfg.layout.text_colors[AgentState.IDLE] == "#808080"


def test_text_colors_must_be_hex(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[layout.text_colors]\nidle = "grey"\n')
    with pytest.raises(ValueError, match="text_colors"):
        load(path)
