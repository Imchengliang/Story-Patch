from opencc import OpenCC

_T2S = OpenCC("t2s")
_MATCH_STRIP = set("，。、；：？！“”‘’（）《》〈〉【】—…·「」『』,.;:?!'\"()[]<>-–—")


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def to_simplified(text: str) -> str:
    return _T2S.convert(text)


def normalize_for_match(text: str) -> str:
    simplified = to_simplified(text)
    return "".join(char for char in simplified if not char.isspace() and char not in _MATCH_STRIP)
