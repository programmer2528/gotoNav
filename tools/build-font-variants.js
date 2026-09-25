/* 基于基准 index.html（git 7c27b1f，用户指定的视觉版本）生成三个只差主标题字体的变体。
   字体全部本地化（fonts/ 目录），离线双击也能正确显示。 */
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..");
const CACHE = path.join(ROOT, ".fontcache");
const VDIR = path.join(ROOT, "variants");
fs.mkdirSync(VDIR, { recursive: true });

const CHARS = [..."直达官网"].map(c => c.codePointAt(0));
const base = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

/* ---------- 1. 从分片 CSS 提取命中的 @font-face，改写为本地路径 ---------- */
function buildLocalFontCss(cssFile, cdnBase, outName, weightOverride) {
  const css = fs.readFileSync(cssFile, "utf8");
  const blocks = css.split("@font-face").slice(1);
  let out = `/* ${outName} — 仅含「直达官网」四字的本地子集，离线可用 */\n`;
  let n = 0;
  for (const raw of blocks) {
    if (!CHARS.some(c => new RegExp(`U\\+${c.toString(16).toUpperCase()}(?!\\d)|U\\+${c.toString(16)}(,|\\s|$)`, "i").test(raw))) {
      // 宽松匹配失败时再做一次范围判断
      const urM = raw.match(/unicode-range:[\s\S]*?(?=})/);
      if (!urM || !CHARS.some(c => urM[0].toLowerCase().includes(c.toString(16)))) continue;
    }
    const urlM = raw.match(/url\(([^)]+)\)/);
    if (!urlM) continue;
    const file = urlM[1].replace(/["']|\.\//g, "").trim();
    let block = raw.slice(0, raw.indexOf("}") + 1)
      .replace(/url\(([^)]+)\)/, `url("./${outName}/${file}")`);
    if (weightOverride) block = block.replace(/font-weight:\s*[^;}]+/, `font-weight: ${weightOverride}`);
    out += "@font-face" + block + "\n";
    n++;
  }
  const dest = path.join(ROOT, "fonts", `${outName}.css`);
  fs.writeFileSync(dest, out);
  console.log(`fonts/${outName}.css: ${n} 个分片`);
  return n;
}

buildLocalFontCss(path.join(CACHE, "misans.css"),
  "https://cdn.jsdelivr.net/npm/misans-webfont@4.3.1/misans/misans-semibold/",
  "misans", 600); // 家族本身是 Semibold，把声明权重改成 600 与标题匹配
buildLocalFontCss(path.join(CACHE, "shs.css"),
  "https://cdn.jsdelivr.net/npm/source-han-sans-sc-vf@0.0.1/assets/",
  "source-han-sans"); // VF 保留 250-900 权重范围

/* ---------- 2. 三个变体 ---------- */
const VARIANTS = [
  {
    name: "index-v1-source-han-sans.html",
    label: "版本1：思源黑体 Source Han Sans SC SemiBold 600（本地 VF 子集）",
    css: "fonts/source-han-sans.css",
    art: `"Source Han Sans SC VF","Source Han Sans SC","Noto Sans SC","Microsoft YaHei","PingFang SC",sans-serif`,
  },
  {
    name: "index-v2-misans.html",
    label: "版本2：MiSans 小米 SemiBold 600（本地子集）",
    css: "fonts/misans.css",
    art: `"MiSans Semibold","MiSans","Microsoft YaHei","PingFang SC",sans-serif`,
  },
  {
    name: "index-v3-noto-sans-sc.html",
    label: "版本3：Noto Sans SC SemiBold 600（本地四字子集，与思源同源）",
    css: "fonts/noto-sans-sc.css",
    art: `"Noto Sans SC","Source Han Sans SC VF","Microsoft YaHei","PingFang SC",sans-serif`,
  },
];

for (const v of VARIANTS) {
  let html = base
    .replace(/<style>/, `<!-- ${v.label}（与基准版仅字体不同） -->\n<link rel="stylesheet" href="${v.css}">\n<style>`)
    .replace(/--art:[^;]+;/, `--art:${v.art};`);
  if (!html.includes(v.css)) throw new Error("注入失败: " + v.name);
  fs.writeFileSync(path.join(VDIR, v.name), html);
  console.log(`variants/${v.name} ✓`);
}

/* ---------- 3. 自检：变体与基准只差字体行 ---------- */
console.log("\n=== 与基准差异（应只有字体注入行与 --art 行）===");
for (const v of VARIANTS) {
  const a = base.split("\n"), b = fs.readFileSync(path.join(VDIR, v.name), "utf8").split("\n");
  const diffs = [];
  for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) diffs.push(i + 1);
  console.log(`${v.name}: 差异行 [${diffs.join(",")}]`);
}
