/**
 * 「直达」扩展收录加载器 · extended-search.js
 * ============================================================
 * 解决的问题：数万条官网不能一次性塞进首屏，否则首屏要下载好几 MB。
 *
 * 策略
 *   1. 先读 data/manifest.json（几百字节）拿到分片清单
 *   2. 浏览器空闲时后台加载「核心区」分片（人工精选 + 域名自洽的高可信 B 级）
 *   3. 长尾分片不主动加载；只有当搜索命中太少时才继续按需加载（渐进）
 *   4. 所有条目进入独立数组，通过包装全局 search() 参与匹配，
 *      既不改动页面原有逻辑，也不会在分类区渲染几万张卡片拖垮 DOM
 *   5. file:// 直开（fetch 被浏览器禁止）时静默降级——只用内置精选库，不报错
 *
 * 依赖的页面全局（都已在 index.html 中定义）：norm / score / search / idx
 * 对外暴露：window.GoToNavExt = { total, loaded, ready(), loadAll() }
 */
(function () {
  "use strict";
  if (typeof document === "undefined") return;

  var BASE = (document.currentScript && document.currentScript.getAttribute("data-base")) || "";
  var EXT = [];               // 扩展条目 { n, d, c, t(级别), keys }
  var loadedShards = {};
  var manifest = null;
  var coreDone = false, allDone = false, failed = false;
  var inflight = null;

  function url(p) { return BASE + p; }

  function toEntry(n, d, k, t) {
    return { n: n, d: d, c: "more", t: t || 3, keys: (k || "").split(/\s+/).filter(Boolean) };
  }

  function pushShard(j) {
    var n = j.n || [], d = j.d || [], k = j.k || [], t = j.t || [];
    for (var i = 0; i < n.length; i++) EXT.push(toEntry(n[i], d[i], k[i], t[i]));
  }

  function loadShard(f) {
    if (loadedShards[f]) return Promise.resolve();
    loadedShards[f] = 1;
    return fetch(url("data/shards/" + f)).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (j) {
      if (j) pushShard(j);
    }).catch(function () { });
  }

  function ensureCore() {
    if (!manifest || coreDone) return Promise.resolve();
    coreDone = true;
    var list = manifest.shards.slice(0, manifest.core || 1).map(function (s) { return s.f; });
    var p = Promise.resolve();
    list.forEach(function (f) { p = p.then(function () { return loadShard(f); }); });
    return p.then(function () {
      attach();
      console.log("[直达] 核心收录已就绪：" + EXT.length + " / " + manifest.total + " 条");
    });
  }

  /** 长尾全量加载（搜索没结果时才触发） */
  function loadAll() {
    if (!manifest || allDone) return Promise.resolve();
    if (inflight) return inflight;
    var rest = manifest.shards.slice(manifest.core || 1).map(function (s) { return s.f; });
    var chain = Promise.resolve();
    rest.forEach(function (f) { chain = chain.then(function () { return loadShard(f); }); });
    inflight = chain.then(function () {
      allDone = true;
      attach();
      console.log("[直达] 全量收录已就绪：" + EXT.length + " 条");
      if (typeof showPanel === "function") showPanel();   // 刷新正在展开的下拉
    });
    return inflight;
  }

  /* ---------------- 包装搜索：把扩展库并入现有匹配与排序 ---------------- */
  var attached = false;
  function attach() {
    if (attached || typeof window.search !== "function" || typeof idx === "undefined") return;
    attached = true;
    var orig = window.search;
    window.search = function (q) {
      var base = orig(q);
      if (!EXT.length) return base;
      var seen = {};
      base.forEach(function (s) { seen[s.d] = 1; });
      var scored = [];
      for (var i = 0; i < EXT.length; i++) {
        var s = EXT[i];
        if (seen[s.d]) continue;
        var sc = (typeof score === "function") ? score(s, q) : 0;
        if (sc > 0) scored.push({ s: s, sc: sc });
      }
      if (!scored.length && !base.length && manifest && !allDone) {
        // 内置库没命中：才值得去拉长尾分片（渐进付费，绝大多数用户不触发）
        loadAll();
      }
      if (!scored.length) return base;
      scored.sort(function (a, b) { return (b.sc - a.sc) || ((a.s.t | 0) - (b.s.t | 0)); });
      var room = 8 - base.length;
      if (room <= 0) return base;
      return base.concat(scored.slice(0, room).map(function (x) { return x.s; }));
    };
  }

  /* ---------------- 启动：优先 manifest 分片，兼容旧单文件格式 ---------------- */
  function boot() {
    if (location.protocol === "file:") {
      console.log("[直达] file:// 模式：扩展库不可用，仅使用内置精选库");
      return;
    }
    fetch(url("data/manifest.json"))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (m) {
        if (m && m.shards) {
          manifest = m;
          return ensureCore();
        }
        // 兼容：旧版单文件 data/sites-full.json
        return fetch(url("data/sites-full.json")).then(function (r) {
          return r.ok ? r.json() : null;
        }).then(function (old) {
          if (!old || !old.sites) { failed = true; return; }
          (old.sites || []).forEach(function (e) { EXT.push(toEntry(e.n, e.d, e.k, 3)); });
          manifest = { total: EXT.length, core: 0, shards: [] };
          attach();
          console.log("[直达] 已加载旧版扩展库 " + EXT.length + " 条（建议跑 pipeline 生成分片索引）");
        });
      })
      .catch(function () { failed = true; });
  }

  /* 首次输入时若核心区还没加载完，立刻提权抢占加载（不等 idle） */
  document.addEventListener("input", function (e) {
    if (e.target && e.target.id === "q" && !coreDone) ensureCore();
  });

  window.GoToNavExt = {
    get total() { return manifest ? manifest.total : EXT.length; },
    get loaded() { return EXT.length; },
    ready: function () { return EXT.length > 0; },
    loadAll: loadAll,
    reload: function () { EXT.length = 0; loadedShards = {}; coreDone = allDone = false; inflight = null; boot(); }
  };

  if ("requestIdleCallback" in window) requestIdleCallback(boot, { timeout: 2000 });
  else setTimeout(boot, 300);
})();
