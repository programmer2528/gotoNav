/* index.html 自检脚本：node tools/verify.js
   检查内容：CSS 括号配平、JS 语法、数据条数与分类分布、重复域名、
            拼贴卡片站点是否已被收录（未收录会导致点击无反应）、分类是否都已定义 */
const fs = require("fs");
const path = require("path");

/* 用法：node tools/verify.js [文件路径]，默认校验 ../index.html */
const file = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(__dirname, "..", "index.html");
const html = fs.readFileSync(file, "utf8");

const css = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1] || "";
const js = (html.match(/<script>([\s\S]*?)<\/script>/) || [])[1] || "";

let bad = 0;
const fail = m => { bad++; console.log("  [FAIL] " + m); };
const ok = m => console.log("  [OK] " + m);

console.log("== 语法 ==");
const o = (css.match(/{/g) || []).length, c = (css.match(/}/g) || []).length;
o === c ? ok(`CSS 括号配平 ${o}/${c}`) : fail(`CSS 括号不匹配 ${o}/${c}`);
try { new Function(js.replace(/document|window|localStorage|fetch|console/g, "U")); ok("JS 语法通过"); }
catch (e) { fail("JS 语法错误: " + e.message); }

console.log("== 数据 ==");
const block = (html.match(/const SITES=\[([\s\S]*?)\n\];/) || [])[1] || "";
const rows = [...block.matchAll(/\["([^"]+)","([^"]+)","([^"]+)","([^"]*)"\]/g)];
rows.length ? ok(`收录 ${rows.length} 条`) : fail("未解析到数据行（格式可能变了）");

const byCat = {}, seen = {}, dups = [];
for (const r of rows) {
  byCat[r[3]] = (byCat[r[3]] || 0) + 1;
  if (seen[r[2]]) dups.push(`${seen[r[2]]} <-> ${r[1]} (${r[2]})`);
  seen[r[2]] = r[1];
}
console.log("  分类分布:", JSON.stringify(byCat));
dups.length ? fail("重复域名: " + dups.join("; ")) : ok("无重复域名");

console.log("== 分类定义 ==");
const catIds = new Set([...html.matchAll(/\{id:"([\w-]+)",label:/g)].map(m => m[1]));
const used = [...new Set(rows.map(r => r[3]))];
const undef = used.filter(x => !catIds.has(x));
undef.length ? fail("数据引用了未定义分类: " + undef.join(", ")) : ok(`全部 ${used.length} 个分类均已定义`);

console.log("== 首屏卡片 ==");
const deckBlock = (js.match(/const COLLAGE=\[([\s\S]*?)\];/) || [])[1] || "";
const deck = [...deckBlock.matchAll(/"(https?:[^"]+)"/g)].map(m => m[1]);
deck.length ? ok(`卡片 ${deck.length} 张`) : fail("未找到卡片配置");
const missing = deck.filter(d => !seen[d]);
missing.length ? fail("卡片站点未收录（点击会失效）: " + missing.join(", "))
               : ok("卡片站点全部已收录，可正常直达");

console.log(bad ? `\n共 ${bad} 项需要修复` : "\n全部检查通过");
process.exit(bad ? 1 : 0);
