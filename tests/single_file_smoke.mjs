/* 单文件产物冒烟测试：把 dist/中继台速查.html 里的 script 按文档顺序在 node 里跑一遍。
 * 这一步专门用来抓“数据脚本位置/依赖顺序”这类打包错误。
 * 运行：node tests/single_file_smoke.mjs
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const html = readFileSync('dist/中继台速查.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗', m); } };

ok(scripts.length === 2, `内联脚本段数 = 2（实际 ${scripts.length}）`);
ok(!textHas(html, 'src="app.js"') && !textHas(html, 'href="style.css"'), '无外部 css/js 引用');
ok(!textHas(scripts[1], 'await fetch("data/repeaters.json"'), 'app 逻辑不再走 fetch（数据已内联）');

function textHas(s, needle) { return s.indexOf(needle) !== -1; }

const listeners = new Map();
function makeEl(id) {
  return {
    id, _html: '', _text: '', dataset: {},
    classList: { toggle() {}, add() {}, remove() {} },
    style: {},
    addEventListener: (t, f) => listeners.set(`${id}:${t}`, f),
    querySelectorAll: () => [],
    closest: () => null,
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; },
    appendChild() {}, remove() {}, click() {},
  };
}
const els = {};
const ctx = {
  console,
  document: {
    querySelector: (s) => (els[s] ??= makeEl(s)),
    querySelectorAll: () => [],
    createElement: () => makeEl('tmp'),
    body: { appendChild() {} },
  },
  navigator: {},
  localStorage: { _m: new Map(), getItem(k) { return this._m.get(k) ?? null; }, setItem(k, v) { this._m.set(k, v); } },
  setTimeout, URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  Blob: class {},
  alert: (m) => { throw new Error('unexpected alert: ' + m); },
  fetch: () => { throw new Error('单文件模式不应发起网络请求'); },
};
ctx.window = ctx;
vm.createContext(ctx);

let threw = null;
try {
  for (const s of scripts) vm.runInContext(s, ctx);
} catch (e) { threw = e; }
ok(threw === null, `按文档顺序执行无异常${threw ? '：' + threw.message : ''}`);

await new Promise((r) => setTimeout(r, 60));

const listHtml = els['#list']?.innerHTML || '';
ok(listHtml.includes('class="card'), '列表渲染出卡片');
ok(els['#cnt']?.textContent !== '', `计数已渲染 (${els['#cnt']?.textContent})`);
ok(listHtml.includes('BR'), '卡片里含呼号');

// 交互：模拟输入关键词
try {
  vm.runInContext("state.q='深圳'; render();", ctx);
  const n = vm.runInContext('window.__rows.length', ctx);
  ok(n > 0 && n < 31, `搜索 '深圳' 命中 ${n} 条`);
  vm.runInContext("state.pos={lat:22.5431,lon:114.0579,acc:20}; render();", ctx);
  const near = vm.runInContext('window.__rows[0]', ctx);
  ok(near._d < 60, `在深圳定位后最近中继 ${near._d?.toFixed(1)} km（应为同城）`);
} catch (e) { ok(false, '交互测试异常: ' + e.message); }

console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
