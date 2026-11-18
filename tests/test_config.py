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
    path.write_text("[layout]\nshimmer = false\n[timing]\nshimmer_step_s = 4.0\n")
    cfg = load(path)
    assert cfg.layout.shimmer is False and cfg.timing.shimmer_step_s == 4.0


ICON = """
...####...
..#    #..
.#.#..#.#.
"""


def test_project_icons_parse_and_expand_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/me")
    path = tmp_path / "config.toml"
    path.write_text(f'[projects."~/src/agentbar"]\nicon = """{ICON}"""\n')
    icons = load(path).layout.icons
    assert icons == {"/home/me/src/agentbar": ("...####...", "..#....#..", ".#.#..#.#.")}


@pytest.mark.parametrize(
    ("icon", "message"),
    [
        ("#" * 19, "the most is 18x8"),
        ("\n".join(["#"] * 9), "the most is 18x8"),
        ("..x..", "may only use"),
        ("....\n....", "no lit pixels"),
        ("", "no lit pixels"),
    ],
)
def test_bad_icons_are_rejected(tmp_path, icon, message):
    path = tmp_path / "config.toml"
    path.write_text(f'[projects."/w/p"]\nicon = """{icon}"""\n')
    with pytest.raises(ValueError, match=message):
        load(path)


def test_ragged_icon_rows_are_padded(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[projects."/w/p"]\nicon = """\n#\n###\n"""\n')
    assert load(path).layout.icons["/w/p"] == ("#..", "###")
