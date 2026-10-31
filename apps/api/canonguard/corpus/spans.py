import hashlib
from dataclasses import dataclass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def cp_to_utf16(text: str, cp_offset: int) -> int:
    bounded = max(0, min(cp_offset, len(text)))
    return utf16_len(text[:bounded])


def utf16_to_cp(text: str, utf16_offset: int) -> int:
    if utf16_offset <= 0:
        return 0
    units = 0
    for index, char in enumerate(text):
        units += 2 if ord(char) > 0xFFFF else 1
        if units > utf16_offset:
            return index
        if units == utf16_offset:
            return index + 1
    return len(text)


@dataclass(frozen=True)
class TextSpan:
    start_cp: int
    end_cp: int
    start_utf16: int
    end_utf16: int
    text: str
    text_hash: str


def make_span(text: str, start_cp: int, end_cp: int) -> TextSpan:
    if start_cp < 0 or end_cp < start_cp or end_cp > len(text):
        raise ValueError(f"invalid span [{start_cp}, {end_cp}) for text length {len(text)}")
    segment = text[start_cp:end_cp]
    return TextSpan(
        start_cp=start_cp,
        end_cp=end_cp,
        start_utf16=cp_to_utf16(text, start_cp),
        end_utf16=cp_to_utf16(text, end_cp),
        text=segment,
        text_hash=sha256_text(segment),
    )
