/* 从分片化中文字体 CSS 中，精确定位覆盖指定字符的 @font-face 分片 */
const fs = require("fs");
const path = require("path");

const CHARS = [..."直达官网"].map(c => c.codePointAt(0));

function pickShards(cssFile, label) {
  const css = fs.readFileSync(cssFile, "utf8");
  const blocks = css.split("@font-face").slice(1);
  const hits = [];
  for (const b of blocks) {
    const urMatch = b.match(/unicode-range:\s*([^;]+);/);
    const urlMatch = b.match(/url\(([^)]+)\)/);
    if (!urMatch || !urlMatch) continue;
    const ur = urMatch[1];
    const url = urlMatch[1].replace(/["']/g, "").trim();
    const need = CHARS.some(c => {
      for (const part of ur.split(",")) {
        const t = part.trim();
        const range = t.match(/U\+([0-9a-fA-F]+)-([0-9a-fA-F]+)/);
        if (range) {
          const lo = parseInt(range[1], 16), hi = parseInt(range[2], 16);
          if (c >= lo && c <= hi) return true;
        } else {
          const single = t.match(/U\+([0-9a-fA-F]+)/);
          if (single && parseInt(single[1], 16) === c) return true;
        }
      }
      return false;
    });
    if (need) hits.push(url);
  }
  console.log(`${label}: 覆盖「直达官网」的分片 ${hits.length} 个`);
  hits.forEach((u, i) => console.log(`  ${i + 1}. ${u.split("/").pop()}`));
  return hits;
}

const DIR = path.join(__dirname, "..", ".fontcache");
const misans = pickShards(path.join(DIR, "misans.css"), "MiSans");
const shs = pickShards(path.join(DIR, "shs.css"), "Source Han Sans VF");

fs.writeFileSync(path.join(DIR, "hits.json"), JSON.stringify({ misans, shs }, null, 2));
