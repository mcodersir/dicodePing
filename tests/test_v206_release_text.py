from pathlib import Path

from tools.normalize_release_text import iter_text_files, normalized_bytes

ROOT = Path(__file__).resolve().parents[1]


def test_release_text_has_stable_line_endings_and_no_trailing_whitespace() -> None:
    dirty = [
        path.relative_to(ROOT).as_posix()
        for path in iter_text_files(ROOT)
        if path.read_bytes() != normalized_bytes(path)
    ]
    assert not dirty, "Release text normalization required: " + ", ".join(dirty[:20])
