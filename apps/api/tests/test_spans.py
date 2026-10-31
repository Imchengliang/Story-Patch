import pytest

from canonguard.corpus.spans import cp_to_utf16, make_span, utf16_len, utf16_to_cp


def test_utf16_offsets_with_rare_character() -> None:
    text = "a𠮷b"

    assert utf16_len(text) == 4
    assert cp_to_utf16(text, 2) == 3
    assert utf16_to_cp(text, 3) == 2
    assert utf16_to_cp(text, 4) == 3


def test_make_span_keeps_both_offset_systems() -> None:
    span = make_span("红楼梦", 1, 3)

    assert span.text == "楼梦"
    assert span.start_cp == 1
    assert span.end_cp == 3
    assert span.start_utf16 == 1
    assert span.end_utf16 == 3
    assert len(span.text_hash) == 64


def test_make_span_rejects_invalid_range() -> None:
    with pytest.raises(ValueError):
        make_span("红楼梦", 2, 1)
