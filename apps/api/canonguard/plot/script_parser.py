import re
from dataclasses import dataclass
from typing import Literal

EN_HEADING = re.compile(
    r"^\s*(?:INT|EXT|I/E|INT\./EXT\.)[\.\s].+",
    re.IGNORECASE,
)
CN_HEADING = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百零〇\d]+场|场景[一二三四五六七八九十百零〇\d]+|[内外]景).{0,40}$"
)
INLINE_SPEAKER = re.compile(r"^\s*([A-Z][A-Z0-9 .'\-]{1,30}|[\u4e00-\u9fa5]{2,8})[：:]\s*(.+)$")
CUE_LINE = re.compile(r"^\s*([A-Z][A-Z0-9 .'\-]{1,30})\s*$")


@dataclass(frozen=True)
class ScriptElement:
    kind: Literal["action", "dialogue"]
    text: str
    speaker: str | None = None


@dataclass(frozen=True)
class ParsedScene:
    order: int
    heading: str
    elements: tuple[ScriptElement, ...]
    text: str


def is_scene_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return bool(EN_HEADING.match(stripped) or CN_HEADING.match(stripped))


def parse_script(text: str) -> list[ParsedScene]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = [line.rstrip() for line in normalized.split("\n")]

    scenes: list[ParsedScene] = []
    current_heading = "SCENE 1"
    elements: list[ScriptElement] = []
    body_lines: list[str] = []
    pending_speaker: str | None = None

    def flush() -> None:
        nonlocal elements, body_lines, pending_speaker
        if not elements and not body_lines:
            return
        scenes.append(
            ParsedScene(
                order=len(scenes) + 1,
                heading=current_heading,
                elements=tuple(elements),
                text="\n".join(body_lines).strip(),
            )
        )
        elements = []
        body_lines = []
        pending_speaker = None

    for line in raw_lines:
        stripped = line.strip()
        if is_scene_heading(stripped):
            flush()
            current_heading = stripped
            continue
        if not stripped:
            body_lines.append("")
            continue

        body_lines.append(stripped)
        inline = INLINE_SPEAKER.match(stripped)
        if inline:
            elements.append(
                ScriptElement(
                    kind="dialogue",
                    speaker=inline.group(1).strip(),
                    text=inline.group(2).strip(),
                )
            )
            pending_speaker = None
            continue

        cue = CUE_LINE.match(stripped)
        if cue:
            pending_speaker = cue.group(1).strip()
            continue

        if pending_speaker:
            elements.append(
                ScriptElement(
                    kind="dialogue",
                    speaker=pending_speaker,
                    text=stripped,
                )
            )
            pending_speaker = None
            continue

        elements.append(ScriptElement(kind="action", text=stripped))

    flush()
    return scenes
