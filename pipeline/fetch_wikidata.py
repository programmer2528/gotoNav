# -*- coding: utf-8 -*-
"""
「直达」数据管线 · 第一级：Wikidata 官网属性拉取
------------------------------------------------
原理：Wikidata 的 P856 属性 = "官方网站"，由全球社区人工维护，
是现成的结构化官网白名单（无需爬网页、无需广告过滤）。

产出：gotonav/data/sites-full.json —— 扩展收录库
  { "updated": ISO时间, "count": N, "sites": [ {n: 中文名, d: 官网URL} ] }

用法：python fetch_wikidata.py [MAX_ROWS]
去重与合并由 index.html 前端加载时完成（与内置人工精选库按域名去重）。
后续可挂到 GitHub Actions 每月定时跑，即"自动健康扩容"。
"""
import json, re, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
UA = "GoToNav/0.2 (zhida.cn data pipeline; contact: admin@zhida.cn)"
OUT = Path(__file__).resolve().parent.parent / "data" / "sites-full.json"

MAX_ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 25000

# 带中文标签、且声明了官方网站（P856）的实体
# PS: /wiki/Special:EntityData 可拿到实体类型，这里用 label 即可
QUERY = f"""
SELECT ?itemLabel ?site WHERE {{
  ?item wdt:P856 ?site .
  ?item rdfs:label ?itemLabel .
  FILTER(LANG(?itemLabel) = "zh")
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh,en". }}
}}
LIMIT {MAX_ROWS}
"""

def fetch():
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
    print("请求 Wikidata SPARQL ...", flush=True)
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    rows = data["results"]["bindings"]
    print(f"原始行数：{len(rows)}", flush=True)
    return rows

URL_RE = re.compile(r"^https?://[^\s]+$")
def clean_site(u):
    u = u.strip()
    if not URL_RE.match(u):
        return None
    # 剔除明显的非官网辅助路径（保留首页级链接）
    return u

def main():
    rows = fetch()
    seen_domains, sites = set(), []
    for row in rows:
        name = row.get("itemLabel", {}).get("value", "").strip()
        site = clean_site(row.get("site", {}).get("value", ""))
        if not name or not site:
            continue
        # 域名去重：一个域名只保留一条（保留最短名称）
        try:
            host = re.sub(r"^https?://", "", site).split("/")[0].lower()
        except Exception:
            continue
        if not host or host in seen_domains:
            continue
        seen_domains.add(host)
        sites.append({"n": name, "d": site})
    sites.sort(key=lambda x: x["n"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Wikidata P856 (official website property)",
        "count": len(sites),
        "sites": sites,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"完成：去重后 {len(sites)} 条 → {OUT}")

if __name__ == "__main__":
    main()
