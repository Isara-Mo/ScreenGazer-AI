"""
单词本管理模块
Handles favorited words storage and retrieval
"""

import os
from pathlib import Path

def get_vocab_path() -> Path:
    root = Path(__file__).parent.parent.parent
    return root / "vocab.txt"

def add_word(word: str) -> None:
    """添加单词到收藏本（追加模式）"""
    if not word.strip():
        return
    path = get_vocab_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{word.strip()}\n")

def get_all_words() -> list[str]:
    """获取所有收藏的单词"""
    path = get_vocab_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def clear_vocab() -> None:
    """清空单词本"""
    path = get_vocab_path()
    if path.exists():
        path.unlink()
