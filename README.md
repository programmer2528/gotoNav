# 直达 GoToNav

> 输入品牌名，一步抵达官方网站。没有广告，没有 SEO 垃圾结果。

输入中文 / 拼音 / 拼音首字母（如 `zsyh` → 招商银行），直接跳转**已核验的官网**，绕开搜索引擎的广告与采集站。

## 特性

- **零依赖静态站**：单个 `index.html`，双击即用，离线可用
- **本地毫秒搜索**：拼音全拼 / 首字母 / 别名 / 容错匹配，构建期拼音化，浏览器只做字符串匹配
- **三级质量分级**：A = 人工精选核验（置顶）· B = 域名自洽或权威后缀（.gov.cn / .edu）· C = 长尾
- **数据可持续生长**：Wikidata P856（全球社区人工维护的官网白名单）月度自动扩容
- **零广告 / 零追踪**：无 Cookie、无埋点、无第三方分析

## 本地预览

```bash
python -m http.server 8000
# 打开 http://localhost:8000
```

（双击 index.html 也能用，仅扩展库需要 HTTP 服务）

## 数据管线（每月自动运行）

| Stage | 脚本 | 作用 |
|---|---|---|
| 0 | `tools/extract_curated.js` | 导出页面内置的人工精选库 |
| 1 | `pipeline/fetch_wikidata.py` | 拉取 Wikidata P856 官网白名单 |
| 2 | `pipeline/check_links.py` | 并发健康校验（精选库始终全量） |
| 3 | `pipeline/build_index.py` | 合并去重 → 拼音化 → 分级 → 分片索引 |

由 GitHub Actions 每月 1 日自动执行，也可手动 Run workflow 触发。

## 部署

任意静态托管即可：Cloudflare Pages / GitHub Pages / Vercel。构建命令留空，输出目录填仓库根目录。

## 免责声明

商标与品牌归各自所有者。本站仅在联想列表中展示文字域名用于指示性合理使用，直达跳转由用户自主点击完成，对第三方官网内容不承担责任。

## License

代码 MIT；数据（`data/`）遵循各自来源（人工精选 + [Wikidata CC0](https://www.wikidata.org/wiki/Wikidata:Licensing)）。
