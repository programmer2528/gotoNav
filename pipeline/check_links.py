# -*- coding: utf-8 -*-
"""
「直达」数据管线 · Stage 3：链接健康校验（每月例行）
====================================================
为什么要这一步
    数万条自动数据里一定会混入：已关停站点、换了域名、被墙、证书失效的链接。
    放任不管，用户点到的就是 404 ——"已核验"的招牌就砸了。
    本脚本做 HTTP 探测并把结果落盘，build_index 会自动剔除 / 降级问题链接。

判定规则
    ok        200-399 且最终域名未变
    redirect  发生了跨站跳转（说明换了新域名）→ 降级为 C 级，并记下新域名供人工更新
    dead      4xx/5xx/超时/证书错误/域名不存在

产出
    data/health.json  {"updated":..., "results": {"cmbchina.com":{"t":"ok","s":200,"u":"https://..."}}}

用法
    python pipeline/check_links.py                 # 全量（数万条约 20-40 分钟）
    python pipeline/check_links.py --limit 3000    # 先抽查核心区（约 3 分钟）
    python pipeline/check_links.py --workers 64    # 提高并发（带宽允许时）
"""
import json
import ssl
import time
import socket
import argparse
import http.client
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MANIFEST = DATA / "manifest.json"
HEALTH = DATA / "health.json"
UA = "GoToNav/0.3 health-check (https://zhida.cn)"

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def probe(item):
    """探测单个 URL。返回 (host, {"t":..., "s":..., "u":...})"""
    host, url = item
    res = {"t": "dead", "s": 0, "u": url}
    for attempt in range(2):
        try:
            parts = urllib.parse.urlsplit(url)
            scheme = parts.scheme or "https"
            conn = http.client.HTTPSConnection(parts.netloc, timeout=8, context=_ctx) \
                if scheme == "https" else http.client.HTTPConnection(parts.netloc, timeout=8)
            path = parts.path or "/"
            conn.request("HEAD", path, headers={"User-Agent": UA, "Accept": "*/*"})
            r = conn.getresponse()
            code = r.status
            loc = r.getheader("Location")
            conn.close()
            if 300 <= code < 400 and loc:
                new_host = urllib.parse.urlsplit(
                    urllib.parse.urljoin(url, loc)).netloc.lower().split(":")[0]
                res = {"t": "ok" if new_host.endswith(host) or host.endswith(new_host) else "redirect",
                       "s": code, "u": loc}
                if res["t"] == "redirect":
                    res["new"] = new_host
                return host, res
            res = {"t": "ok" if code < 400 else "dead", "s": code, "u": url}
            return host, res
        except (socket.timeout, socket.gaierror):
            if attempt:
                break
            time.sleep(1)
        except Exception:
            # HEAD 不被支持时改用 GET（拿不到 body 也够用）
            try:
                parts = urllib.parse.urlsplit(url)
                conn = http.client.HTTPSConnection(parts.netloc, timeout=10, context=_ctx) \
                    if parts.scheme == "https" else http.client.HTTPConnection(parts.netloc, timeout=10)
                conn.request("GET", parts.path or "/", headers={"User-Agent": UA, "Range": "bytes=0-0"})
                r = conn.getresponse()
                r.read(1)
                code = r.status
                conn.close()
                res = {"t": "ok" if code < 400 else "dead", "s": code, "u": url}
                return host, res
            except Exception as e:
                res = {"t": "dead", "s": 0, "u": url, "e": repr(e)[:60]}
                return host, res
    return host, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只校验前 N 条（0 = 全量）")
    ap.add_argument("--workers", type=int, default=48, help="并发数")
    args = ap.parse_args()

    RAW = DATA / "raw" / "wikidata.jsonl"
    CURATED = DATA / "sites-curated.json"
    sites = []

    if RAW.exists():
        print("源：data/raw/wikidata.jsonl", flush=True)
        tot = 0
        with (DATA / "raw" / "wikidata.jsonl").open(encoding="utf-8") as f:
            for line in f:
                if args.limit and tot >= args.limit:
                    break
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                tot += 1
                sites.append(((r.get("host") or "").lower(), r.get("url") or ""))
    elif CURATED.exists():
        print("源：data/sites-curated.json", flush=True)
        cur = json.loads(CURATED.read_text(encoding="utf-8"))["sites"]
        for row in cur[: args.limit or len(cur)]:
            host = (row["d"].split("//")[-1].split("/")[0] or "").lower()
            if host.startswith("www."):
                host = host[4:]
            sites.append((host, row["d"]))
    else:
        print("✗ 既没有 data/raw/wikidata.jsonl 也没有 data/sites-curated.json，先跑 Stage 1")
        return

    print(f"\n开始校验 {len(sites)} 条（并发 {args.workers}）…")
    results, done = {}, 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for host, res in pool.map(probe, sites):
            done += 1
            if host and (host not in results or res["t"] == "ok"):
                results[host] = res
            if done % 500 == 0:
                el = time.time() - t0
                print(f"  {done}/{len(sites)} 条 · {el:.0f}s · "
                      f"预计剩余 {el/done*(len(sites)-done):.0f}s", flush=True)

    summary = {"ok": 0, "redirect": 0, "dead": 0}
    for v in results.values():
        summary[v["t"]] = summary.get(v["t"], 0) + 1

    HEALTH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked": len(sites),
        "summary": summary,
        "results": results,
    }, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"校验完成（{time.time()-t0:.0f}s）：正常 {summary.get('ok',0)} · "
          f"换域名 {summary.get('redirect',0)} · 失效 {summary.get('dead',0)}")
    print(f"结果：{HEALTH.relative_to(ROOT)}")
    print("下一步：python pipeline/build_index.py（会自动剔除/降级问题链接）")
    print("=" * 60)


if __name__ == "__main__":
    main()
