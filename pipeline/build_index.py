# -*- coding: utf-8 -*-
"""
「直达」数据管线 · Stage 2：合并 → 拼音化 → 分级 → 分片索引
============================================================
输入
    data/sites-curated.json   人工精选库（node tools/extract_curated.js 导出）
    data/raw/wikidata.jsonl   Stage 1 产出
    data/health.json          可选，Stage 3 产出（用于剔除失效/被墙/降级的链接）

核心设计（为什么这样我才敢说"数万条也能秒出"）
    1. 拼音在构建期算好，不在浏览器里算 —— 运行时只需字符串匹配，不做汉字转拼音
    2. 分片 + 清单：浏览器先加载 ~/.几百 KB 的核心区，长尾区用到才加载
    3. 三级质量分级：
       A = 人工精选（永远置顶）
       B = 域名与品牌名自洽（如 cmbchina.com ↔ 招商银行/CMB）或权威顶级域（.gov.cn/.edu 等）
       C = 其余长尾
       搜索命中同级时按知名度排序，长尾永远不会压过已核验结果

产出
    data/manifest.json    {"updated":..., "total":N, "core":k, "shard":2000, "tiers":{...}, "shards":[...]}
    data/shards/s000.json {"n":[...],"d":[...],"k":[" 全拼 首字母 别名 ..."],"t":[1,2,3]}

用法
    pip install -r pipeline/requirements.txt     # 需要 pypinyin（首次）
    python pipeline/build_index.py               # 默认核心区预算 700KB
    python pipeline/build_index.py --core-kb 1200
"""
import json
import re
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw" / "wikidata.jsonl"
CURATED = DATA / "sites-curated.json"
HEALTH = DATA / "health.json"
OUT_DIR = DATA / "shards"
MANIFEST = DATA / "manifest.json"
SHARD = 2000

# 权威域名后缀：命中即可信度高（政府/高校/国际组织/军队）
AUTHORITATIVE = (
    ".gov.cn", ".edu.cn", ".mil.cn", ".org.cn", ".ac.cn",
    ".gov", ".edu", ".mil", ".int", ".gouv.fr", ".gov.uk", ".edu.au", ".edu.hk", ".gov.hk",
)

# 中国大陆二级后缀（用于"注册级域名"判定：csg.cn <-> 南方电网 应同一主体）
MULTI = ("com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn", "co.jp", "com.hk",
         "co.uk", "com.au", "org.uk", "ac.uk", "com.br", "co.kr", "com.tw")


def registrable(host):
    """取注册级域名：www.cmbchina.com -> cmbchina.com；news.sgcc.com.cn -> sgcc.com.cn"""
    host = host.lower().strip().lstrip(".")
    parts = host.split(":")[0].split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    tail2 = ".".join(parts[-2:])                    # 例：com.cn / co.uk
    if tail2 in MULTI and len(parts) >= 3:
        return ".".join(parts[-3:])                 # news.sgcc.com.cn -> sgcc.com.cn
    return tail2                                    # www.cmbchina.com -> cmbchina.com


# ------------------------------------------------------------------ 拼音支持
try:
    from pypinyin import lazy_pinyin, Style
    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False


def name_keys(name, en=""):
    """为一个词条生成全部检索关键词（小写、空格分隔）。"""
    keys, seen = [], set()

    def add(x):
        x = (x or "").strip().lower()
        if x and x not in seen:
            seen.add(x)
            keys.append(x)

    add(name.replace("（", "(").replace("）", ")"))
    add(re.sub(r"[^a-z0-9]", "", name.lower()))
    if en:
        add(en)
        add(re.sub(r"[^a-z0-9]", "", en.lower()))

    if HAS_PINYIN and re.search(r"[\u4e00-\u9fff]", name):
        try:
            full = "".join(lazy_pinyin(name))                              # zhaoshangyinhang
            init = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER))    # zsyh
            add(full)
            add(init)
        except Exception:
            pass
    return keys


def dedupe_keys(*parts):
    """接受任意多个 list/str，合并去重并保持顺序（小写化）。"""
    out, seen = [], set()
    for p in parts:
        items = p if isinstance(p, (list, tuple, set)) else str(p or "").split()
        for x in items:
            x = str(x).strip().lower()
            if x and x not in seen:
                seen.add(x)
                out.append(x)
    return out


def host_keys(host):
    """域名本身产生的关键词列表：www.cmbchina.com -> ["cmbchina","cmbchina.com","cmbchinacom"]"""
    base = registrable(host)
    main = base.split(".")[0]
    return [main, base, base.replace(".", "")]


def is_authoritative(host):
    return any(host.endswith(s) or registrable(host).endswith(s) for s in AUTHORITATIVE)


def branded_match(name, en, host):
    """品牌名与域名是否自洽（人工核验的弱代理指标）。"""
    main = registrable(host).split(".")[0]
    latin = re.sub(r"[^a-z0-9]", "", (en or "").lower())
    if latin and len(latin) >= 3 and (latin.startswith(main[:max(3, len(main))]) or main.startswith(latin[:max(3, len(latin))])):
        return True
    if HAS_PINYIN and re.search(r"[\u4e00-\u9fff]", name):
        try:
            full = "".join(lazy_pinyin(name))
            init = "".join(lazy_pinyin(name, style=Style.FIRST_LETTER))
            if len(init) >= 2 and init in main:
                return True
            if len(full) >= 4 and (full.startswith(main) or main.startswith(full[:4])):
                return True
        except Exception:
            pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-kb", type=int, default=700, help="核心区大小预算（KB）")
    args = ap.parse_args()

    if not HAS_PINYIN:
        print("⚠ 未安装 pypinyin：将缺少拼音检索能力（zsyh 这类缩写搜不到）")
        print("  安装：pip install -r pipeline/requirements.txt\n")

    # ---------- 1. 人工精选库（A 级） ----------
    curated = []
    if CURATED.exists():
        for row in json.loads(CURATED.read_text(encoding="utf-8"))["sites"]:
            curated.append({"n": row["n"], "d": row["d"], "c": row["c"],
                            "k": row.get("k", ""), "links": 999, "tier": 1})
    print(f"A 级 · 人工精选：{len(curated)} 条")

    # ---------- 2. Wikidata（B/C 级） ----------
    health = {}
    if HEALTH.exists():
        health = json.loads(HEALTH.read_text(encoding="utf-8")).get("results", {})
        print(f"载入健康数据：{len(health)} 个域名的校验结果")

    auto, seen = [], set()
    if RAW.exists():
        for line in RAW.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            name = r.get("zh") or r.get("en") or ""
            host = (r.get("host") or "").lower()
            if not name or not host:
                continue
            reg = registrable(host)
            if reg in seen:
                continue
            seen.add(reg)

            # 健康数据过滤：明确失效的直接剔除
            st = health.get(reg) or health.get(host)
            if st and st.get("t") == "dead":
                continue

            downgraded = bool(st and st.get("t") == "redirect")
            auto.append({
                "n": name,
                "en": r.get("en", ""),
                "d": r.get("url", ""),
                "c": "more",
                "host": host,
                "links": r.get("links", 0),
                "tier": 2 if (is_authoritative(host) or branded_match(name, r.get("en", ""), host)) else 3,
                "downgraded": downgraded,
            })
    auto = [x for x in auto if x["tier"] == 2] + [x for x in auto if x["tier"] == 3]
    cur_hosts = {registrable(re.sub(r"^https?://", "", c["d"]).split("/")[0]) for c in curated}
    auto = [x for x in auto if registrable(x["host"]) not in cur_hosts]
    b_count = sum(1 for x in auto if x["tier"] == 2)
    print(f"B 级 · 域名自洽/权威后缀：{b_count} 条")
    print(f"C 级 · 长尾：{len(auto)-b_count} 条")

    # ---------- 3. 合并、生成关键词、排序 ----------
    print("\n▶ 生成检索关键词 ...", flush=True)
    all_sites = []
    for c in curated:                      # A 级：人工精选，连同人工写的别名一起进索引
        host = re.sub(r"^https?://", "", c["d"]).split("/")[0]
        all_sites.append({"n": c["n"], "d": c["d"], "c": c["c"], "t": 1,
                          "k": " ".join(dedupe_keys(name_keys(c["n"]), host_keys(host), c.get("k", "")))})
    for x in auto:                         # B/C 级：自动生成
        all_sites.append({"n": x["n"], "d": x["d"], "c": "more",
                          "t": 3 if x.get("downgraded") else x["tier"],
                          "k": " ".join(dedupe_keys(name_keys(x["n"], x.get("en", "")), host_keys(x["host"])))})

    all_sites.sort(key=lambda s: (s["t"], s["k"].count(" ")))
    print(f"  合计参与索引：{len(all_sites)} 条")

    # ---------- 4. 分片输出 ----------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("s*.json"):
        old.unlink()

    shards, budget = [], args.core_kb * 1024
    total_bytes = 0
    for i in range(0, len(all_sites), SHARD):
        chunk = all_sites[i:i + SHARD]
        payload = {
            "n": [s["n"] for s in chunk],
            "d": [s["d"] for s in chunk],
            "k": [s["k"] for s in chunk],
            "t": [s["t"] for s in chunk],
        }
        name = f"s{len(shards):03d}.json"
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (OUT_DIR / name).write_bytes(raw)
        gzip_hint = int(len(raw) * 0.3)          # CDN 通常 gzip/br，按经验估算
        total_bytes += len(raw)
        shards.append({"f": name, "c": len(chunk), "raw": len(raw), "gz": gzip_hint})

    # 核心区：从第一片开始累加，直到接近预算（分片已按 tier 排序）
    used, core = 0, 0
    for s in shards:
        if used + s["gz"] > budget:
            break
        used += s["gz"]
        core += 1
    core = max(core, 1)

    manifest = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(all_sites),
        "shard": SHARD,
        "core": core,
        "core_kb": round(used / 1024),
        "est_total_kb": round(total_bytes / 1024),
        "tiers": {"A": len(curated), "B": b_count, "C": len(auto) - b_count},
        "pinyin": HAS_PINYIN,
        "shards": shards,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"索引构建完成：{manifest['total']} 条 / {len(shards)} 个分片")
    print(f"  核心区 {core} 片 ≈ {manifest['core_kb']} KB（首屏后台加载）")
    print(f"  全量 ≈ {manifest['est_total_kb']} KB（gzip 约 {round(total_bytes*0.3/1024)} KB，命中不到时才加载）")
    print(f"  分级 A={len(curated)} / B={b_count} / C={len(auto)-b_count}")
    print(f"  清单：{MANIFEST.relative_to(ROOT)}")
    print("下一步：python -m http.server 8000，访问 http://localhost:8000 验证")
    print("=" * 60)


if __name__ == "__main__":
    main()
