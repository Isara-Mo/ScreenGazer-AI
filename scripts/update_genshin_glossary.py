"""Manually refresh the offline Genshin glossary from a documented public JSON.

Run ``python scripts/update_genshin_glossary.py`` from any working directory.
Only JSON is downloaded; no upstream code, notes, HTML, or variants are executed
or retained. Application startup never invokes this script or uses the network.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request


SOURCE_URL = "https://dataset.genshin-dictionary.com/words.json"
TERMS_URL = "https://genshin-dictionary.com/en/opendata"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "src" / "data" / "genshin_terms.json"
MAX_BYTES = 12 * 1024 * 1024
_REGION_TAGS = frozenset("mondstadt dragonspine liyue inazuma sumeru fontaine natlan nodkrai snezhnaya khaenriah fatui".split())
_NAME_TAGS = frozenset("""
character-main character-sub title enemy enemy-boss enemy-legend location domain
event object living-being organization facility quest-archon quest-world
quest-random quest-story quest-daily quest-tribal quest-selenic item specialty
drop drop-boss gemstone talent-material weapon-material food artifact
artifact-piece element sereniteapot weapon sword claymore polearm bow catalyst
""".split())
# Reviewed lore concepts without upstream tags; generic UI words stay excluded.
_UNTAGGED_IDS = frozenset("""
mora original-resin wind-glider vision gnosis delusion archon-war ley-line
dark-calamity the-calamity-of-darkness descenders
""".split())
_QUOTE_PAIRS = (("\"", "\""), ("“", "”"), ("「", "」"), ("『", "』"))


def _clean(value: str) -> str:
    value = " ".join(value.split())
    for left, right in _QUOTE_PAIRS:
        if len(value) > 2 and value.startswith(left) and value.endswith(right):
            value = value[len(left):-len(right)].strip()
            break
    return value.translate(str.maketrans({c: "'" for c in "’‘ʼ＇"}))


def _valid(value: object) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and len(value) <= 240
        and not any(ord(char) < 32 or char in "<>\x7f" for char in value)
    )


def build_dataset(raw: bytes, retrieved_at: str | None = None) -> dict:
    if len(raw) > MAX_BYTES:
        raise ValueError("Upstream JSON exceeds the download size limit")
    upstream = json.loads(raw)
    if not isinstance(upstream, list) or not 1000 <= len(upstream) <= 50000:
        raise ValueError("Unexpected upstream schema or count; refusing to replace glossary")
    stats: Counter = Counter()
    candidates: dict[str, list[dict]] = {}
    for row in upstream:
        if not isinstance(row, dict):
            raise ValueError("Upstream entries must be JSON objects")
        en, zh, entry_id = row.get("en"), row.get("zhCN"), row.get("id")
        tags = row.get("tags", [])
        if not _valid(en) or not _valid(zh) or not _valid(entry_id):
            stats["invalid_or_empty_rows"] += 1
            continue
        if not isinstance(tags, list) or not all(isinstance(tag, str) and re.fullmatch(r"[a-z0-9-]{1,50}", tag) for tag in tags):
            raise ValueError("Unexpected upstream tags schema")
        if "/" in zh:
            stats["ambiguous_chinese_rows"] += 1
            continue
        tagset = set(tags)
        if not tagset.intersection(_NAME_TAGS) and not (tagset and tagset <= _REGION_TAGS) and entry_id not in _UNTAGGED_IDS:
            stats["generic_or_unclassified_rows"] += 1
            continue
        # English aliases in the main en field share ONE Chinese mapping. The
        # variants field is deliberately never read: it includes unofficial names
        # and known typos. Chinese multi-translation rows above are never split.
        aliases = en.split(" / ")
        if any("/" in alias for alias in aliases):
            stats["ambiguous_english_rows"] += 1
            continue
        for alias in aliases:
            english, chinese = _clean(alias), _clean(zh)
            if len(english) < 2 or not re.search(r"[A-Z]", english) or not re.search(r"[\u3400-\u9fff]", chinese):
                stats["generic_or_invalid_aliases"] += 1
                continue
            item = {"id": entry_id, "en": english, "zhCN": chinese, "tags": tags}
            candidates.setdefault(english, []).append(item)
        if len(aliases) > 1:
            stats["split_english_alias_rows"] += 1
    terms = []
    for english, entries in candidates.items():
        if len({entry["zhCN"] for entry in entries}) > 1:
            stats["conflicting_english_terms"] += 1
            continue
        terms.append(entries[0])
        stats["duplicate_identical_terms"] += len(entries) - 1
    terms.sort(key=lambda entry: (entry["en"].casefold(), entry["id"]))
    if len(terms) < 1000:
        raise ValueError("Too few usable terms; refusing to replace glossary")
    pairs = {row["en"]: row["zhCN"] for row in terms}
    if pairs.get("Pacal") != "帕加尔" or pairs.get("Children of Echoes") != "回声之子":
        raise ValueError("Known glossary anchors changed; manual review is required")
    return {
        "schema_version": 1,
        "game": "genshin",
        "source": {
            "name": "Genshin Dictionary (community-maintained)",
            "url": SOURCE_URL,
            "terms_url": TERMS_URL,
            "retrieved_at_utc": retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "upstream_sha256": hashlib.sha256(raw).hexdigest(),
            "upstream_entry_count": len(upstream),
            "entry_count": len(terms),
        },
        "filter_counts": dict(sorted(stats.items())),
        "terms": terms,
    }


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or parsed.netloc != "dataset.genshin-dictionary.com":
            raise ValueError("Refusing a redirect outside the documented HTTPS data host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; ScreenGazer-GlossaryUpdater/1.0)",
        "Accept": "application/json", "Referer": TERMS_URL,
    })
    with urllib.request.build_opener(_SafeRedirect()).open(request, timeout=45) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Downloaded glossary exceeds the size limit")
    return data


def source_markdown(dataset: dict) -> str:
    source = dataset["source"]
    counts = "\n".join(f"- `{key}`: {value}" for key, value in dataset["filter_counts"].items())
    return f"""# 原神中英术语数据来源

本文件由 `scripts/update_genshin_glossary.py` 生成。

- 来源：[Genshin Dictionary 开放数据]({TERMS_URL})，社区维护，**不是官方术语库**。
- 原始 JSON：[words.json]({SOURCE_URL})。
- 获取时间（UTC）：`{source['retrieved_at_utc']}`。
- 上游原始文件 SHA-256：`{source['upstream_sha256']}`。
- 上游条目数：{source['upstream_entry_count']}；本地去重后英中对应数：{source['entry_count']}。
- [使用条款]({TERMS_URL}#terms-of-use)（网页标示 2024-11-21 更新）：允许修改和再分发数据；保留上游权利、撤销条件及无担保约定。使用和分发前请查看该页面的完整条款。
- 版权声明：Copyright © 2021-present Xicri & the Genshin Dictionary contributors。Genshin Impact 商标属于 miHoYo、COGNOSPHERE 及关联主体。

## 保留与筛选规则

只保留 `id`、`en`、`zhCN`、`tags`；不保留 HTML、注释、例句或 `variants`（上游明确说明其含错别字和非官方昵称）。保留有分类的角色、NPC、地名、组织、任务、物品等，以及少量明确列出的未分类世界观概念；普通通用用语不默认收录。

中文含 `/` 的多义/多译行整行排除，不猜选其一；仅当中文唯一时，英语主字段的 ` / ` 正规名称分别对应同一中文。其他英语斜杠形式排除。大小写不同的英文不合并；同一英文有不同中文时，整个冲突词排除。去除配对外围引号，统一排版撇号，折叠空白；不做近似匹配。

{counts}

## 使用与更新

应用离线加载该文件，只将当前原文命中的词条作为中文翻译提示，不改写原英文。匹配区分大小写，因此普通 `amber` / `will` 不触发 `Amber` / `Will` 角色名。`Will`、`Amber`、`Vision` 等普通词同形专名明确标记为需语境判断；模型应保留普通含义，不能盲目替换。词表和模型仍可能存在错误、缺漏或新版本滞后，可通过设置中的英文到中文覆盖修正。

手动更新：`python scripts/update_genshin_glossary.py`。也可用 `--input <本地上游 JSON>` 做离线重建。更新前校验大小、结构、条目数量、已知关键映射；校验成功后以临时文件原子替换 JSON，失败保留已有 JSON。程序运行时不会自动联网拉取术语。
"""


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Use a previously downloaded upstream JSON (offline)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json":
        parser.error("--output must be a .json file")
    if args.input:
        with args.input.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    else:
        raw = download()
    dataset = build_dataset(raw)
    atomic_write(args.output, (json.dumps(dataset, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    atomic_write(args.output.with_suffix(".SOURCES.md"), source_markdown(dataset).encode("utf-8"))
    print(f"Saved {dataset['source']['entry_count']} terms to {args.output}")


if __name__ == "__main__":
    main()
