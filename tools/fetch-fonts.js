/* 下载覆盖「直达官网」四字的字体分片到本地，并生成本地 @font-face CSS。
   目的：页面不依赖任何外部 CDN，离线双击打开也能显示指定字体。 */
const fs = require("fs");
const path = require("path");
const https = require("https");
const { execFileSync } = require("child_process");

const ROOT = path.join(__dirname, "..");
const CACHE = path.join(ROOT, ".fontcache");
const OUT = path.join(ROOT, "fonts");

fs.mkdirSync(OUT, { recursive: true });

/* 用 curl 下载（沙箱代理下更稳定） */
function download(url, dest) {
  execFileSync("curl", ["-sk", "-m", "60", "-A", "Mozilla/5.0", url, "-o", dest]);
  const size = fs.existsSync(dest) ? fs.statSync(dest).size : 0;
  if (size < 500) throw new Error(`下载失败或文件过小: ${url} (${size}B)`);
  return size;
}

/* 提取原始 CSS 中包含指定 url 的 @font-face 块 */
function extractFaces(cssFile, urls) {
  const css = fs.readFileSync(cssFile, "utf8");
  const blocks = css.split("@font-face").slice(1);
  const out = [];
  for (const raw of blocks) {
    const urlMatch = raw.match(/url\(([^)]+)\)/);
    if (!urlMatch) continue;
    const u = urlMatch[1].replace(/["']/g, "").trim();
    const idx = urls.indexOf(u);
    if (idx === -1) continue;
    out.push({ block: "@font-face" + raw.slice(0, raw.indexOf("}") + 1), url: u });
  }
  return out;
}

function build(label, cssFile, urls, dirName) {
  const dir = path.join(OUT, dirName);
  fs.mkdirSync(dir, { recursive: true });
  const faces = extractFaces(cssFile, urls);
  let css = `/* ${label} — 仅含「直达官网」四字的本地子集，离线可用 */\n`;
  let total = 0;
  faces.forEach((f, i) => {
    const file = path.basename(f.url).split("?")[0];
    const dest = path.join(dir, file);
    let size;
    try {
      size = download(f.url, dest);
    } catch (e) {
      console.log(`  [跳过] ${file}: ${e.message}`);
      return;
    }
    total += size;
    let block = f.block.replace(/url\(([^)]+)\)/, `url("./${dirName}/${file}")`);
    css += block + "\n";
  });
  fs.writeFileSync(path.join(OUT, `${dirName}.css`), css);
  console.log(`${label}: ${faces.length} 个分片，共 ${(total / 1024).toFixed(1)}KB → fonts/${dirName}.css`);
}

const hits = JSON.parse(fs.readFileSync(path.join(CACHE, "hits.json"), "utf8"));

build("MiSans Semibold", path.join(CACHE, "misans.css"), hits.misans, "misans");
build("Source Han Sans SC VF", path.join(CACHE, "shs.css"), hits.shs, "source-han-sans");

/* Noto Sans SC：Google Fonts 的四字子集（1.4KB），CSS 手工写 */
const notoDest = path.join(OUT, "noto-sans-sc-600-4chars.woff2");
const src = path.join(CACHE, "noto-sans-sc-600-4chars.woff2");
if (fs.existsSync(src)) {
  fs.copyFileSync(src, notoDest);
  const css = `/* Noto Sans SC SemiBold 600 — 仅含「直达官网」四字的本地子集，离线可用 */
@font-face{font-family:"Noto Sans SC";font-style:normal;font-weight:600;font-display:swap;
  src:url("./noto-sans-sc-600-4chars.woff2") format("woff2");
  unicode-range:U+5b98,U+76f4,U+7f51,U+8fbe}
`;
  fs.writeFileSync(path.join(OUT, "noto-sans-sc.css"), css);
  console.log(`Noto Sans SC: 1 个文件，${(fs.statSync(notoDest).size / 1024).toFixed(1)}KB → fonts/noto-sans-sc.css`);
}

console.log("\n完成。本地字体目录: gotonav/fonts/");
