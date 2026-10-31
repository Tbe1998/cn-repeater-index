/* 中继台速查 —— 前端逻辑（无框架、无依赖） */
const state = {
  data: null,
  pos: null,            // {lat, lon, acc}
  q: '',
  band: 'all',
  mode: 'all',
};

const $ = (s) => document.querySelector(s);

/* ---------- 几何 ---------- */
const R = 6371.0088;
const rad = (d) => (d * Math.PI) / 180;

function distKm(a, b) {
  const dp = rad(b.lat - a.lat), dl = rad(b.lon - a.lon);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
function bearing(a, b) {
  const p1 = rad(a.lat), p2 = rad(b.lat), dl = rad(b.lon - a.lon);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}
const CARD = ['北', '东北', '东', '东南', '南', '西南', '西', '西北'];
const cardinal = (d) => CARD[Math.round(((d % 360) / 45)) % 8];

/* ---------- 加载 ---------- */
async function load() {
  const res = await fetch('data/repeaters.json', { cache: 'no-cache' });
  state.data = await res.json();
  const saved = localStorage.getItem('lastPos');
  if (saved) { try { state.pos = JSON.parse(saved); } catch (e) {} }
  renderMeta();
  render();
}

function renderMeta() {
  const d = state.data;
  $('#disclaimer').textContent = d.disclaimer || '';
  const box = $('#sources');
  box.innerHTML = (d.sources || []).map((s) => `
    <div class="src">
      <a href="${s.url}" target="_blank" rel="noopener">${s.name}</a><br>
      发布：${s.publisher || ''} · 页面日期 ${s.page_date || '未标注'} · 抓取 ${(s.fetched_at || '').slice(0, 10)} · ${s.record_count} 条<br>
      <span style="color:#ffb454">${s.freshness_warning || ''}</span>
    </div>`).join('') +
    `<div class="src" style="margin-top:10px">构建时间 ${d.generated_at} · 坐标 ${d.coordinate_crs || ''}</div>`;
}

/* ---------- 过滤与渲染 ---------- */
function filtered() {
  const q = state.q.trim().toLowerCase();
  return state.data.repeaters.filter((r) => {
    if (state.band !== 'all' && r.band !== state.band) return false;
    if (state.mode !== 'all' && r.mode_class !== state.mode) return false;
    if (!q) return true;
    const hay = [r.call, r.province, r.city, r.district, r.mode_raw,
      String(r.downlink_mhz), String(r.uplink_mhz), String(r.ctcss_hz || '')].join(' ').toLowerCase();
    return hay.includes(q);
  });
}

function sortRows(rows) {
  const p = state.pos;
  const out = rows.map((r) => {
    if (p && r.lat != null) {
      const d = distKm(p, r);
      return { ...r, _d: d, _b: bearing(p, r) };
    }
    return { ...r, _d: null, _b: null };
  });
  out.sort((a, b) => {
    if (a._d != null && b._d != null) return a._d - b._d;
    if (a._d != null) return -1;
    if (b._d != null) return 1;
    return (a.province || '').localeCompare(b.province || '', 'zh') || (a.call || '').localeCompare(b.call || '');
  });
  return out;
}

const MODE_TXT = { analog: '模拟', digital: '数字', mixed: '数模', unknown: '未知' };
const MODE_CLS = { analog: 'a', digital: 'd', mixed: 'm', unknown: '' };

function fmt(f) { return (f == null) ? '—' : String(+f.toFixed(5)).replace(/(\.\d{3})\d+$/, '$1'); }

function card(r) {
  const off = (r.offset_mhz > 0 ? '+' : '') + (r.offset_mhz != null ? r.offset_mhz.toFixed(3) : '—');
  const tone = r.ctcss_hz ? `亚音 ${r.ctcss_hz}Hz` : (r.dcs ? `DCS ${r.dcs}` : '无亚音');
  const distTxt = r._d == null ? '' :
    `<span class="dist">${r._d < 1 ? (r._d * 1000).toFixed(0) + ' m' : r._d.toFixed(1) + ' km'} · ${cardinal(r._b)}</span>`;
  const susp = r.status === 'suspended' ? '<span class="badge s">暂停/维护中</span>' : '';
  const also = (r.also_sources || []).map((s) => `${s.source}(${s.date || '—'})`).join('、');
  return `<article class="card ${r.status === 'suspended' ? 'susp' : ''}" data-id="${r.id}">
    <div class="hd">
      <span class="call">${r.call}</span>
      <span class="freq">${fmt(r.downlink_mhz)} <span style="color:#93a4c0;font-size:12px">↓收</span>
        / ${fmt(r.uplink_mhz)} <span style="color:#93a4c0;font-size:12px">↑发</span></span>
      <span class="badge ${MODE_CLS[r.mode_class] || ''}">${MODE_TXT[r.mode_class] || ''}${r.submode ? ' ' + r.submode : ''}</span>
      ${susp}
    </div>
    <div class="sub">
      <span>${[r.province, r.city, r.district].filter(Boolean).join(' · ') || '地区未标注'}</span>
      <span>${tone}</span>
      ${distTxt}
    </div>
    <div class="det">
      <span>上行(中继输入) <b>${fmt(r.uplink_mhz)} MHz</b> · 下行(中继输出) <b>${fmt(r.downlink_mhz)} MHz</b> · 偏移 <b>${off} MHz</b></span>
      <span>模式原文：<b>${r.mode_raw || '—'}</b></span>
      ${r.color_code != null ? `<span>彩色码 <b>${r.color_code}</b> · 时隙 <b>${r.timeslot || '—'}</b></span>` : ''}
      <span>坐标精度：<b>${r.geo_accuracy}</b>${r.geo_path ? '（' + r.geo_path + '）' : ''}，按行政区中心点计</span>
      <span>来源：<b>${r.source_name}</b>${r.source_date ? '（' + r.source_date + '）' : ''}${also ? '；另见 ' + also : ''}</span>
      <span>抓取 ${(r.fetched_at || '').slice(0, 10)} · 库内编号 #${r.id}</span>
    </div>
  </article>`;
}

function render() {
  const rows = sortRows(filtered());
  $('#cnt').textContent = `${rows.length}/${state.data.repeaters.length}`;
  const list = $('#list');
  list.innerHTML = rows.length ? rows.map(card).join('') : '<div class="empty">没有匹配的中继台</div>';
  list.querySelectorAll('.card').forEach((el) =>
    el.addEventListener('click', () => el.classList.toggle('open')));
  window.__rows = rows;
}

/* ---------- 定位 ---------- */
function setGeoText() {
  const p = state.pos;
  $('#geo').textContent = p
    ? `已定位 ${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}${p.acc ? ' ±' + Math.round(p.acc) + 'm' : ''}`
    : '未定位：按地区排序（点「定位」用手机 GPS）';
}

function locate() {
  if (!navigator.geolocation) { $('#geo').textContent = '此浏览器不支持定位'; return; }
  $('#geo').textContent = '正在定位…';
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      state.pos = { lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy };
      localStorage.setItem('lastPos', JSON.stringify(state.pos));
      setGeoText(); render();
    },
    (err) => { $('#geo').textContent = '定位失败：' + err.message + '（可手动搜索城市）'; },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
  );
}

/* ---------- CHIRP 导出（与后台 chirp_row 同一套规则） ---------- */
function chirpCsv(rows) {
  const head = ['Location', 'Name', 'Frequency', 'Duplex', 'Offset', 'Tone',
    'rToneFreq', 'cToneFreq', 'DtcsCode', 'DtcsPolarity', 'Mode', 'TStep', 'Skip', 'Comment'];
  const esc = (v) => /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v);
  const lines = [head.join(',')];
  rows.forEach((r, i) => {
    const off = +(r.uplink_mhz - r.downlink_mhz).toFixed(4);
    const duplex = off > 0 ? '+' : (off < 0 ? '-' : '');
    const tone = r.ctcss_hz ? 'Tone' : (r.dcs ? 'DTCS' : 'OFF');
    const rtf = r.ctcss_hz ? r.ctcss_hz.toFixed(1) : '88.5';
    const name = `${r.call} ${r.city || r.district || ''}`.trim().slice(0, 16);
    lines.push([i + 1, name, r.downlink_mhz, duplex, Math.abs(off), tone, rtf, rtf,
      r.dcs || '023', 'NN', 'FM', '5.00', '', (r.mode_raw || '').slice(0, 40)].map(esc).join(','));
  });
  return lines.join('\n');
}

function download(name, text) {
  const blob = new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
}

/* ---------- 事件 ---------- */
$('#loc').addEventListener('click', locate);
$('#q').addEventListener('input', (e) => { state.q = e.target.value; render(); });
$('#export').addEventListener('click', () => {
  const rows = (window.__rows || []).filter((r) => r.uplink_mhz && r.downlink_mhz);
  if (!rows.length) return alert('当前没有可导出的条目');
  download(`repeaters-${new Date().toISOString().slice(0, 10)}.csv`, chirpCsv(rows));
});
$('#filters').addEventListener('click', (e) => {
  const b = e.target.closest('.chip');
  if (!b) return;
  const f = b.dataset.f, v = b.dataset.v;
  document.querySelectorAll(`.chip[data-f="${f}"]`).forEach((c) => c.classList.toggle('on', c === b));
  state[f === 'band' ? 'band' : 'mode'] = v;
  render();
});

setGeoText();
load().catch((e) => {
  $('#list').innerHTML = `<div class="empty">数据加载失败：${e.message}<br>请先运行 python3 scripts/build.py</div>`;
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
