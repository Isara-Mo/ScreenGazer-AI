# 原神中英术语数据来源

本文件由 `scripts/update_genshin_glossary.py` 生成。

- 来源：[Genshin Dictionary 开放数据](https://genshin-dictionary.com/en/opendata)，社区维护，**不是官方术语库**。
- 原始 JSON：[words.json](https://dataset.genshin-dictionary.com/words.json)。
- 获取时间（UTC）：`2026-09-19T04:33:51+00:00`。
- 上游原始文件 SHA-256：`f3cf0a710c59fdb2a7ed4247ad9a63e6c3264e111b12e9b9e7a011affad92798`。
- 上游条目数：6673；本地去重后英中对应数：6454。
- [使用条款](https://genshin-dictionary.com/en/opendata#terms-of-use)（网页标示 2024-11-21 更新）：允许修改和再分发数据；保留上游权利、撤销条件及无担保约定。使用和分发前请查看该页面的完整条款。
- 版权声明：Copyright © 2021-present Xicri & the Genshin Dictionary contributors。Genshin Impact 商标属于 miHoYo、COGNOSPHERE 及关联主体。

## 保留与筛选规则

只保留 `id`、`en`、`zhCN`、`tags`；不保留 HTML、注释、例句或 `variants`（上游明确说明其含错别字和非官方昵称）。保留有分类的角色、NPC、地名、组织、任务、物品等，以及少量明确列出的未分类世界观概念；普通通用用语不默认收录。

中文含 `/` 的多义/多译行整行排除，不猜选其一；仅当中文唯一时，英语主字段的 ` / ` 正规名称分别对应同一中文。其他英语斜杠形式排除。大小写不同的英文不合并；同一英文有不同中文时，整个冲突词排除。去除配对外围引号，统一排版撇号，折叠空白；不做近似匹配。

- `ambiguous_chinese_rows`: 23
- `duplicate_identical_terms`: 0
- `generic_or_invalid_aliases`: 43
- `generic_or_unclassified_rows`: 170
- `invalid_or_empty_rows`: 1
- `split_english_alias_rows`: 18

## 使用与更新

应用离线加载该文件，只将当前原文命中的词条作为中文翻译提示，不改写原英文。匹配区分大小写，因此普通 `amber` / `will` 不触发 `Amber` / `Will` 角色名。`Will`、`Amber`、`Vision` 等普通词同形专名明确标记为需语境判断；模型应保留普通含义，不能盲目替换。词表和模型仍可能存在错误、缺漏或新版本滞后，可通过设置中的英文到中文覆盖修正。

手动更新：`python scripts/update_genshin_glossary.py`。也可用 `--input <本地上游 JSON>` 做离线重建。更新前校验大小、结构、条目数量、已知关键映射；校验成功后以临时文件原子替换 JSON，失败保留已有 JSON。程序运行时不会自动联网拉取术语。
