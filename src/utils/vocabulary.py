"""Favorites stored as one UTF-8 word or phrase per line."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from threading import RLock


_lock = RLock()


def get_vocab_path() -> Path:
    return Path(__file__).parent.parent.parent / "vocab.txt"


def _clean_word(word: str) -> str:
    # A selected phrase can contain line breaks; it must remain one entry.
    return " ".join(word.split())


def get_all_words() -> list[str]:
    """Read existing entries without rewriting or discarding user content."""
    with _lock:
        path = get_vocab_path()
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8-sig") as stream:
            return [line.strip() for line in stream if line.strip()]


def is_favorite(word: str) -> bool:
    key = _clean_word(word).casefold()
    return bool(key) and any(_clean_word(entry).casefold() == key for entry in get_all_words())


def add_word(word: str) -> None:
    """Append a favorite once, also handling an existing unterminated last line."""
    word = _clean_word(word)
    if not word:
        return
    with _lock:
        if is_favorite(word):
            return
        path = get_vocab_path()
        needs_newline = False
        if path.exists() and path.stat().st_size:
            with path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                needs_newline = stream.read(1) not in (b"\n", b"\r")
        with path.open("ab") as stream:
            if needs_newline:
                stream.write(b"\n")
            stream.write(f"{word}\n".encode("utf-8"))


def remove_word(word: str) -> bool:
    """Remove only this favorite (including old duplicates), atomically.

    Other entries, blank lines, line endings and an optional UTF-8 BOM are kept.
    """
    key = _clean_word(word).casefold()
    if not key:
        return False
    with _lock:
        path = get_vocab_path()
        if not path.exists():
            return False
        original = path.read_bytes()
        has_bom = original.startswith(b"\xef\xbb\xbf")
        lines = original.decode("utf-8-sig").splitlines(keepends=True)
        kept = [line for line in lines if _clean_word(line).casefold() != key]
        if len(kept) == len(lines):
            return False
        replacement = "".join(kept).encode("utf-8")
        if has_bom:
            replacement = b"\xef\xbb\xbf" + replacement
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".vocab-", delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(replacement)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return True


def toggle_word(word: str) -> bool:
    """Toggle a favorite and return its resulting saved state."""
    with _lock:
        if is_favorite(word):
            remove_word(word)
            return False
        add_word(word)
        return bool(_clean_word(word))


def clear_vocab() -> None:
    with _lock:
        get_vocab_path().unlink(missing_ok=True)
