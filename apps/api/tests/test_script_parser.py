from pathlib import Path

from canonguard.plot.script_parser import parse_script

FIXTURE = Path(__file__).parent / "fixtures" / "sample_screenplay.txt"


def test_parse_bilingual_screenplay() -> None:
    scenes = parse_script(FIXTURE.read_text(encoding="utf-8"))

    assert len(scenes) == 2
    assert scenes[0].heading == "INT. KITCHEN - DAY"
    assert scenes[1].heading == "场景一 内景 书房 夜"


def test_parse_dialogue_elements() -> None:
    scenes = parse_script(FIXTURE.read_text(encoding="utf-8"))

    english_speakers = [
        element.speaker for element in scenes[0].elements if element.kind == "dialogue"
    ]
    chinese_speakers = [
        element.speaker for element in scenes[1].elements if element.kind == "dialogue"
    ]

    assert english_speakers == ["ALICE", "BOB", "ALICE"]
    assert chinese_speakers == ["宝玉", "黛玉", "宝玉"]


def test_parse_action_lines() -> None:
    scenes = parse_script(FIXTURE.read_text(encoding="utf-8"))

    actions = [element.text for element in scenes[1].elements if element.kind == "action"]

    assert actions[0].startswith("宝玉坐在灯下")
