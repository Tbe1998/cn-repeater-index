/* 无浏览器下的前端冒烟测试：用最小 DOM 桩在 node 里真跑 web/app.js。
 * 目的：验证过滤/排序/距离方位/CHIRP 导出/渲染这些真实逻辑，而不是只做语法检查。
 * 运行：node tests/app_smoke.mjs   （在工程根目录）
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const data = JSON.parse(readFileSync('web/data/repeaters.json', 'utf8'));
const appSrc = readFileSync('web/app.js', 'utf8');

const listeners = new Map();
function makeEl(id) {
  const el = {
    id, _html: '', _text: '', dataset: {}, classList: { _s: new Set(), toggle() {}, add() {}, remove() {} },
    style: {},
    addEventListener: (t, f) => listeners.set(`${id}:${t}`, f),
    querySelectorAll: () => [],
    closest: () => null,
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    set textContent(v) { this._text = v; },
    get textContent() { return this._text; },
    appendChild() {}, remove() {}, click() {},
  };
  return el;
}
const els = {};
const ids = ['#cnt', '#loc', '#q', '#filters', '#geo', '#export', '#list', '#sources', '#disclaimer'];

const ctx = {
  console,
  document: {
    querySelector: (s) => (els[s] ??= makeEl(s)),
    querySelectorAll: () => [],
    createElement: () => makeEl('tmp'),
    body: { appendChild() {} },
  },
  window: {},
  navigator: {},
  localStorage: {
    _m: new Map(),
    getItem(k) { return this._m.get(k) ?? null; },
    setItem(k, v) { this._m.set(k, v); },
  },
  fetch: async () => ({ json: async () => data }),
  setTimeout, URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  Blob: class { constructor() {} },
  alert: (m) => { throw new Error('unexpected alert: ' + m); },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(appSrc, ctx, { filename: 'app.js' });

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; console.log('  ✓', msg); } else { fail++; console.log('  ✗', msg); } };

// 等待 load() 完成
await new Promise((r) => setTimeout(r, 50));

console.log('数据与渲染');
const cnt = els['#cnt'].textContent;
ok(/^\d+\/\d+$/.test(cnt), `计数已渲染 (${cnt})`);
ok(els['#list'].innerHTML.includes('class="card'), '列表已渲染卡片');
ok(data.repeaters.length === 31, `数据条数 ${data.repeaters.length}`);

console.log('过滤');
vm.runInContext("state.band='70cm'; render();", ctx);
const n70 = vm.runInContext('window.__rows.length', ctx);
ok(n70 > 0 && n70 < data.repeaters.length, `70cm 过滤生效 (${n70} ≤ ${data.repeaters.length})`);
vm.runInContext("state.band='all'; state.mode='digital'; render();", ctx);
const nd = vm.runInContext('window.__rows.length', ctx);
ok(nd > 0 && vm.runInContext('window.__rows.every(r=>r.mode_class==="digital")', ctx), `数字化过滤生效 (${nd})`);
vm.runInContext("state.mode='all'; state.q='温州'; render();", ctx);
const nwz = vm.runInContext('window.__rows.length', ctx);
ok(nwz === 4, `关键词 '温州' 命中 ${nwz} 条（应为 4）`);
vm.runInContext("state.q=''; render();", ctx);

console.log('定位、距离与方位');
vm.runInContext("state.pos={lat:30.2741,lon:120.1551,acc:30}; render();", ctx);
const top = vm.runInContext('window.__rows[0]', ctx);
ok(Number.isFinite(top._d), `最近条目距离为数字 (${top._d?.toFixed(1)} km)`);
ok(vm.runInContext('window.__rows.every((r,i,a)=>i===0||a[i-1]._d<=r._d)', ctx), '按距离升序');
ok(['北', '东北', '东', '东南', '南', '西南', '西', '西北'].includes(top._b != null ? vm.runInContext('cardinal(window.__rows[0]._b)', ctx) : ''), '方位角能折算成中文方向');
const hz = vm.runInContext('window.__rows.filter(r=>r.province==="浙江")', ctx);
ok(hz.length === 4 && hz.every((r) => r._d > 200), `温州距杭州 ${hz[0]?._d?.toFixed(0)} km（合理范围 >200km）`);

console.log('CHIRP 导出');
const csv = vm.runInContext('chirpCsv(window.__rows.slice(0,3))', ctx);
const lines = csv.trim().split('\n');
ok(lines.length === 4, `CSV 行数 = 1 表头 + 3 数据（实际 ${lines.length}）`);
ok(lines[0].startsWith('Location,Name,Frequency,Duplex,Offset,Tone'), 'CSV 表头符合 CHIRP');
const cols = lines[1].split(',');
ok(/^\d+(\.\d+)?$/.test(cols[2]), `Frequency 列为数值 (${cols[2]})`);
ok(['+', '-', ''].includes(cols[3]), `Duplex 列合法 (${cols[3]})`);

console.log('数据源与免责');
ok(els['#sources'].innerHTML.includes('crac') || els['#sources'].innerHTML.includes('CRAC'), '数据源已渲染');
ok(els['#disclaimer'].textContent.length > 10, '免责声明已渲染');

console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
