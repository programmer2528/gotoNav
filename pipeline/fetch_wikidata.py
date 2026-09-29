# -*- coding: utf-8 -*-
"""
「直达」数据管线 · Stage 1：Wikidata 官网白名单拉取
====================================================
原理
    Wikidata 的 P856 属性 = "官方网站"，由全球社区人工维护。
    它不是网页爬虫结果，而是「结构化的官网白名单」——
    这正是本项目区别于搜索引擎的地方：不需要爬网页、不需要过滤广告。

本版相比初版的四项改进
    1. 分页（LIMIT/OFFSET）——Wikidata 单次查询 60 秒超时，25000 条一次性拉必然失败
    2. 实体类型过滤——只取企业/组织/学校/软件/网站等，剔除寺庙、县市、纪念馆等噪声
    3. 热度门槛（wikibase:sitelinks）——只收具有一定知名度的实体，源头降噪
    4. 重试 + 退避 + 域名黑名单——429/5xx 自动重试；剔除社交媒体、建站平台等非官网链接

产出
    data/raw/wikidata.jsonl  每行一条 JSON：
    {"qid":"Q123","zh":"招商银行","en":"China Merchants Bank",
     "url":"https://www.cmbchina.com/","host":"cmbchina.com","links":42,"group":"company"}

用法
    python pipeline/fetch_wikidata.py                      # 默认目标 60000 条
    python pipeline/fetch_wikidata.py --max 30000          # 指定上限
    python pipeline/fetch_wikidata.py --min-links 5        # 提高热度门槛（更干净）
    python pipeline/fetch_wikidata.py --max Visible 0      # 不限行数（跑到拉空为止）
"""
import json
import re
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "GoToNav/0.3 (https://zhida.cn data pipeline; contact: admin@zhida.cn)"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "wikidata.jsonl"
PAGE = 1000          # 单页行数（国内网络建议 ≤1000，大查询易被重置连接）
MAX_TRIES = 6        # 每页最大重试次数
SLEEP = 8            # 页间隔（礼貌抓取，避免被限流；国内网络建议 ≥5）

# ---------------------------------------------------------------- 实体类型分组
# 说明：QID 写错只会少收一些，不会出错；拿不准的类型交给最后的「通用兜底查询」
# （按知名度门槛抓取全部有官网的实体）补回来。
TYPE_GROUPS = {
    "company": ["Q783794", "Q4830453", "Q891723", "Q43229", "Q6881511", "Q18388277"],
    #          公司         商业         上市公司       组织          企业           科技公司
    "university": ["Q3918", "Q15902", "Q875538"],
    #              大学       高等教育机构   私立大学
    "finance": ["Q22687", "Q262166", "Q2431196"],
    #            银行        跨国银行      投资银行
    "software": ["Q36161", "Q7889", "Q7397"],
    #             软件        电子游戏     软件公司
    "institution": ["Q955824", "Q15265344", "Q4118488"],
    #                研究机构     非营利组织    高等教育机构?
}

# ---------------------------------------------------------------- 域名黑名单
# 这些平台的链接不是「品牌官网」，而是该品牌在某个平台的账号页 / 托管页
BLACKLIST_SUFFIX = (
    "facebook.com", "twitter.com", "instagram.com", "linkedin.com", "youtube.com",
    "weibo.com", "wechat.com", "tiktok.com", "douyin.com", "xiaohongshu.com",
    "medium.com", "substack.com", "blogspot.com", "wordpress.com", "wixsite.com",
    "myshopify.com", "squarespace.com", "tumblr.com", "medium.jp",
    "wikipedia.org", "wikidata.org", "wikimedia.org", "wikimediafoundation.org",
    "play.google.com", "itunes.apple.com", "apps.apple.com", "f-droid.org",
    "appstore.io", "github.io", "gitlab.io", "gitbook.io", "notion.site",
    "firebaseapp.com", "web.app", "netlify.app", "pages.dev", "vercel.app",
    "linktr.ee", "t.me", "discord.gg", "archive.org", "scribd.com",
    "crunchbase.com", "owler.com", "zoominfo.com", "ilanacareer.com",
)
URL_RE = re.compile(r"^https?://[^\s\"'<>]+$", re.I)


def _sparql(query, quiet=False):
    """带重试的 SPARQL 查询。返回 bindings 列表。"""
    delay = 6
    last = None
    for i in range(MAX_TRIES):
        try:
            url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "json"})
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"}
            )
            with urllib.request.urlopen(req, timeout=180) as r:
                body = json.loads(r.read().decode("utf-8"))
            return body["results"]["bindings"]
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code == 429 or 500 <= e.code < 600:
                wait = delay * (i + 1)
                if not quiet:
                    print(f"    {last}，{wait}s 后重试（{i+1}/{MAX_TRIES}）", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:                       # 超时 / SSL / 网络抖动
            last = repr(e)[:60]
            wait = delay * (i + 1)
            if not quiet:
                print(f"    网络异常 {last}，{wait}s 后重试（{i+1}/{MAX_TRIES}）", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"SPARQL 连续 {MAX_TRIES} 次失败：{last}")


def _query_typed(types, limit, offset, ordering):
    values = " ".join(f"wd:{t}" for t in types)
    order = "ORDER BY DESC(?links)" if ordering else ""
    tpl = """
SELECT ?item ?zh ?en ?site ?links WHERE {
  VALUES ?type { __VALUES__ }
  ?item wdt:P31/wdt:P279* ?type .
  ?item wdt:P856 ?site .
  ?item wikibase:sitelinks ?links .
  OPTIONAL { ?item rdfs:label ?zh . FILTER(LANG(?zh) IN ("zh","zh-hans","zh-cn")) }
  OPTIONAL { ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }
  FILTER(?links >= __MINLINKS__)
}
__ORDER__ LIMIT __LIMIT__ OFFSET __OFFSET__
"""
    return (tpl.replace("__VALUES__", values)
               .replace("__MINLINKS__", str(MIN_LINKS))
               .replace("__ORDER__", order)
               .replace("__LIMIT__", str(limit))
               .replace("__OFFSET__", str(offset)))


def _query_generic(limit, offset, ordering):
    order = "ORDER BY DESC(?links)" if ordering else ""
    tpl = """
SELECT ?item ?zh ?en ?site ?links WHERE {
  ?item wdt:P856 ?site .
  ?item wikibase:sitelinks ?links .
  OPTIONAL { ?item rdfs:label ?zh . FILTER(LANG(?zh) IN ("zh","zh-hans","zh-cn")) }
  OPTIONAL { ?item rdfs:label ?en . FILTER(LANG(?en) = "en") }
  FILTER(?links >= __MINLINKS2__)
}
__ORDER__ LIMIT __LIMIT__ OFFSET __OFFSET__
"""
    return (tpl.replace("__MINLINKS2__", str(max(MIN_LINKS, 8)))
               .replace("__ORDER__", order)
               .replace("__LIMIT__", str(limit))
               .replace("__OFFSET__", str(offset)))


def _host_of(url):
    m = re.match(r"^https?://([^/?#]+)", url, re.I)
    if not m:
        return None
    return m.group(1).lower().lstrip(".")


def _clean(url):
    """规范化 URL：去掉多余路径（保留首页级），剔除非官网域名。返回 None 表示丢弃。"""
    u = url.strip()
    if not URL_RE.match(u):
        return None
    try:
        scheme = "https" if u.lower().startswith("https") else "http"
        host = _host_of(u)
        if not host or "." not in host:
            return None
        host = host.split(":")[0]
        base = host[4:] if host.startswith("www.") else host
        if any(base == b or base.endswith("." + b) for b in BLACKLIST_SUFFIX):
            return None
        # 只保留首页级链接，避免收录到深层路径（易失效、非官网入口）
        return f"{scheme}://{host}/"
    except Exception:
        return None


def _paged(fetch_rows, max_rows, label):
    """通用分页循环：按 QID 去重，直到拉空或达到上限。"""
    got, seen, offset, ordering = [], set(), 0, True
    while len(got) < max_rows or max_rows == 0:
        rows = fetch_rows(PAGE, offset, ordering)
        if not rows:
            break
        for r in rows:
            qid = (r.get("item", {}).get("value", "") or "").rsplit("/", 1)[-1]
            if not qid or qid in seen:
                continue
            seen.add(qid)
            got.append(r)
        print(f"    [{label}] 累计去重后 {len(got)} 条（offset={offset}）", flush=True)
        if len(rows) < PAGE:
            break
        offset += PAGE
        if len(got) >= max_rows and max_rows > 0:
            break
        time.sleep(SLEEP)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=60000, help="目标行数上限（0 = 不限）")
    ap.add_argument("--min-links", type=int, default=3, help="最小站点数（知名度门槛）")
    ap.add_argument("--generic-only", action="store_true", help="只跑通用兜底查询（更快）")
    args = ap.parse_args()

    global MIN_LINKS
    MIN_LINKS = args.min_links

    print("=" * 60)
    print("Stage 1 · 从 Wikidata 拉取官网白名单（P856）")
    print(f"  目标：{args.max if args.max else '不限'} 条 | 热度门槛：sitelinks ≥ {MIN_LINKS}")
    print("=" * 60, flush=True)

    all_rows = []
    if not args.generic_only:
        for group, types in TYPE_GROUPS.items():
            print(f"\n▶ 实体分组：{group}（{len(types)} 个类型）", flush=True)
            rows = _paged(lambda l, o, ob, _t=types: _sparql(_query_typed(_t, l, o, ob)),
                          max(0, int(args.max * 0.6)) if args.max else 0, group)
            all_rows += rows

    print("\n▶ 通用兜底：全部有官网且知名的实体", flush=True)
    all_rows += _paged(lambda l, o, ob: _sparql(_query_generic(l, o, ob)),
                       args.max, "generic")

    # ---------- 清洗 + 去重 ----------
    print("\n▶ 清洗与域名去重 ...", flush=True)
    seen_host, out = set(), []
    for r in all_rows:
        zh = (r.get("zh") or {}).get("value", "").strip()
        en = (r.get("en") or {}).get("value", "").strip()
        if not (zh or en):
            continue
        url = _clean((r.get("site") or {}).get("value", ""))
        if not url:
            continue
        host = _host_of(url).split(":")[0]
        base = host[4:] if host.startswith("www.") else host
        if base in seen_host:
            continue
        seen_host.add(base)
        qid = (r.get("item", {}).get("value", "") or "").rsplit("/", 1)[-1]
        try:
            links = int(float((r.get("links") or {}).get("value", 0)))
        except Exception:
            links = 0
        out.append({"qid": qid, "zh": zh, "en": en, "url": url,
                    "host": host, "links": links, "group": "generic"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for row in out:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60)
    print(f"完成：{len(out)} 条 → {OUT.relative_to(ROOT)}")
    print("下一步：python pipeline/build_index.py")
    print("=" * 60)


if __name__ == "__main__":
    MIN_LINKS = 3
    main()
