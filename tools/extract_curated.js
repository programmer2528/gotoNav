/**
 * 工具：把页面内置的人工精选库导出为独立 JSON，供数据管线去重使用
 * ------------------------------------------------------------------
 * 为什么要这一步：index.html 里的 SITES 数组是「人工核验的黄金种子」，
 * 必须始终优先于 Wikidata 自动数据（同一站点冲突时以人工为准、排在最前）。
 * 导出成 data/sites-curated.json 后，管线用它做去重与置顶。
 *
 * 用法：node tools/extract_curated.js [目标html，默认 ../index.html]
 */
const fs = require("fs");
const path = require("path");

const target = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(__dirname, "..", "index.html");

const html = fs.readFileSync(target, "utf8");
const block = (html.match(/const SITES=\[([\s\S]*?)\n\];/) || [])[1];
if (!block) {
  console.error("未在页面中定位到 SITES 数组，请确认文件格式未变");
  process.exit(1);
}

const rows = [...block.matchAll(/\["([^"]+)","([^"]+)","([^"]+)","([^"]*)"\]/g)].map((m) => ({
  n: m[1],
  d: m[2],
  c: m[3],
  k: m[4] || "",
}));

const out = path.join(__dirname, "..", "data", "sites-curated.json");
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(
  out,
  JSON.stringify(
    { updated: new Date().toISOString().slice(0, 10), source: path.basename(target), count: rows.length, sites: rows },
    null,
    2
  ),
  "utf8"
);

console.log(`已导出 ${rows.length} 条精选库 → ${path.relative(process.cwd(), out)}`);
