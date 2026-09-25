// 基于 index.html 生成三个「仅主标题字体不同」的对照版本
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..');
const base = fs.readFileSync(path.join(dir, 'index.html'), 'utf8');

const VARIANTS = [
  {
    file: 'index-v1-source-han-sans.html',
    name: '思源黑体 Source Han Sans SC VF',
    head:
      '<!-- 版本1：思源黑体 Source Han Sans SC（可变字体，cn-font-split 中文子集，jsDelivr） -->\n' +
      '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>\n' +
      '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/source-han-sans-sc-vf@0.0.1/assets/result.css">\n',
    font: '"Source Han Sans SC VF","Source Han Sans SC","Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif'
  },
  {
    file: 'index-v2-misans.html',
    name: 'MiSans 小米 · Semibold',
    head:
      '<!-- 版本2：小米 MiSans Semibold（cn-font-split 中文子集，jsDelivr） -->\n' +
      '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>\n' +
      '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans-webfont@4.3.1/misans/misans-semibold/result.css">\n',
    font: '"MiSans Semibold","MiSans","PingFang SC","Microsoft YaHei",sans-serif'
  },
  {
    file: 'index-v3-noto-sans-sc.html',
    name: 'Noto Sans SC（Google Fonts，与思源同源）',
    head:
      '<!-- 版本3：Noto Sans SC SemiBold 600（Google Fonts 在线引入） -->\n' +
      '<link rel="preconnect" href="https://fonts.googleapis.com">\n' +
      '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n' +
      '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@600&display=swap">\n',
    font: '"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif'
  }
];

if (!/--art:[^;]*;/.test(base)) { console.error('未找到 --art 变量'); process.exit(1); }
if (!base.includes('</head>')) { console.error('未找到 </head>'); process.exit(1); }

const outDir = path.join(dir, 'variants');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir);

for (const v of VARIANTS) {
  let html = base
    .replace(/--art:[^;]*;/, '--art:' + v.font + ';')
    .replace('</head>', v.head + '</head>');
  // 主标题统一 SemiBold 600
  html = html.replace(/\.hero h1\{[^}]*\}/, m =>
    m.replace(/font-weight:\s*\d+/, 'font-weight:600'));
  fs.writeFileSync(path.join(outDir, v.file), html);
  console.log('已生成', v.file, '—', v.name);
}
