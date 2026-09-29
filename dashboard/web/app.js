/* =============================================================================
   java-workspace 项目工作台 —— 前端逻辑
   -----------------------------------------------------------------------------
   没有框架、没有构建步骤：浏览器直接跑这个文件。理由和 server.py 一样 ——
   工作台的卖点是「删掉目录就等于没来过」，多一个 npm 依赖就多一处回滚残留。

   数据流：
     GET /api/projects  →  渲染卡片（含实时端口状态）
     POST /api/projects/<id>/start|stop  →  后台任务，前端轮询 /api/projects 看进度
     GET /api/projects/<id>/job  →  启动过程的逐步日志（抽屉里实时显示）
   ============================================================================= */

'use strict';

// ------------------------------------------------------------------ 状态 --
const S = {
  projects: [],
  cfg: {},
  sys: null,
  q: '',
  filters: { state: null, category: null, origin: null, tag: null },
  view: 'grid',
  timer: null,
  pending: new Set(),   // 正在发请求的项目 id，避免连点
  drawerId: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const STATE_LABEL = {
  running: '运行中', stopped: '已停止', starting: '启动中',
  stopping: '停止中', failed: '启动失败', partial: '部分运行',
};

const UI_STATE_FILTERS = [
  { id: null,           label: '全部' },
  { id: 'running',      label: '运行中' },
  { id: 'partial',      label: '部分运行' },
  { id: 'busy',         label: '启动中' },
  { id: 'stopped',      label: '已停止' },
  { id: 'failed',       label: '启动失败' },
  { id: 'needs-build',  label: '未构建' },
  { id: 'planned',      label: '计划中' },
];

// ------------------------------------------------------------------ 工具 --
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function uiState(p) {
  if (p.state === 'starting' || p.state === 'stopping') return 'busy';
  if (p.state === 'running') return 'running';
  if (p.state === 'partial') return 'partial';
  if (p.state === 'failed') return 'failed';
  if (p.declared === 'planned') return 'planned';
  if (p.declared === 'needs-build') return 'needs-build';
  return 'stopped';
}

function stateText(p) {
  if (p.state === 'starting' || p.state === 'stopping') return STATE_LABEL[p.state];
  if (p.state === 'running') return '运行中';
  if (p.state === 'partial') return '部分运行';
  if (p.state === 'failed') return '启动失败';
  if (p.declared === 'planned') return '计划中';
  if (p.declared === 'needs-build') return '未构建';
  return '已停止';
}

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts));
  let body = null;
  try { body = await r.json(); } catch (_) { /* 非 JSON */ }
  if (!r.ok) throw new Error((body && body.error) || `${r.status} ${r.statusText}`);
  return body;
}

let toastTimer = null;
function toast(msg, kind) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast' + (kind ? ' is-' + kind : '');
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, kind === 'bad' ? 7000 : 4200);
}

function relTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return '刚刚';
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return d.toLocaleDateString('zh-CN');
}

// ------------------------------------------------------------------ 加载 --
async function loadConfig() {
  S.cfg = await api('/api/config');
  $('#page-title').textContent = S.cfg.dashboard.title || '项目工作台';
  $('#page-sub').textContent = S.cfg.dashboard.subtitle || '';
  $('#foot-ws').textContent = S.cfg.workspace;
  $('#foot-cfg').textContent = S.cfg.configPath;
  document.title = S.cfg.dashboard.title || '项目工作台';
}

async function loadProjects() {
  const r = await api('/api/projects');
  S.projects = r.projects || [];
  render();
  renderMiddlewareSummary();
  if (S.drawerId) refreshDrawerLive();
}

async function loadSystem() {
  try {
    S.sys = await api('/api/system');
    renderMiddleware();
  } catch (e) {
    $('#mw-summary').textContent = '读取失败：' + e.message;
  }
}

// --------------------------------------------------------------- 渲染：筛选
function tagCounts() {
  const m = new Map();
  for (const p of S.projects) for (const t of (p.tags || [])) m.set(t, (m.get(t) || 0) + 1);
  return m;
}

function renderFilters() {
  // 状态
  const counts = {};
  for (const p of S.projects) {
    const s = uiState(p);
    counts[s] = (counts[s] || 0) + 1;
  }
  $('#chips-state').innerHTML = UI_STATE_FILTERS.map(f => {
    const n = f.id === null ? S.projects.length : (counts[f.id] || 0);
    return `<button class="chip${S.filters.state === f.id ? ' is-on' : ''}" data-f="state" data-v="${f.id ?? ''}">
      ${esc(f.label)}<span class="chip-n">${n}</span></button>`;
  }).join('');

  // 类别
  $('#chips-category').innerHTML =
    `<button class="chip${S.filters.category === null ? ' is-on' : ''}" data-f="category" data-v="">全部</button>` +
    (S.cfg.categories || []).map(c => {
      const n = S.projects.filter(p => p.category === c.id).length;
      if (!n) return '';
      return `<button class="chip${S.filters.category === c.id ? ' is-on' : ''}" data-f="category" data-v="${esc(c.id)}"
        title="${esc(c.desc || '')}">${esc(c.label)}<span class="chip-n">${n}</span></button>`;
    }).join('');

  // 来源（原创 / 克隆 / 计划中）—— 这一栏是刻意做显眼的
  const ocount = {};
  for (const p of S.projects) ocount[p.origin.kind] = (ocount[p.origin.kind] || 0) + 1;
  $('#chips-origin').innerHTML =
    `<button class="chip${S.filters.origin === null ? ' is-on' : ''}" data-f="origin" data-v="">全部</button>` +
    (S.cfg.origins || []).map(o => {
      const n = ocount[o.id] || 0;
      if (!n) return '';
      return `<button class="chip${S.filters.origin === o.id ? ' is-on' : ''}" data-f="origin" data-v="${esc(o.id)}"
        title="${esc(o.label)}">${esc(o.short)}<span class="chip-n">${n}</span></button>`;
    }).join('');

  // 标签（按出现次数取前 16 个，避免把筛选区撑爆）
  const tc = Array.from(tagCounts().entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const top = tc.slice(0, 16);
  $('#chips-tag').innerHTML =
    `<button class="chip${S.filters.tag === null ? ' is-on' : ''}" data-f="tag" data-v="">全部</button>` +
    top.map(([t, n]) => `<button class="chip${S.filters.tag === t ? ' is-on' : ''}" data-f="tag" data-v="${esc(t)}">${esc(t)}<span class="chip-n">${n}</span></button>`).join('') +
    (tc.length > top.length ? `<span class="chip" style="cursor:default;opacity:.65">还有 ${tc.length - top.length} 个标签（用搜索框找）</span>` : '');
}

function filtered() {
  const kw = S.q.trim().toLowerCase();
  return S.projects.filter(p => {
    if (S.filters.state && uiState(p) !== S.filters.state) return false;
    if (S.filters.category && p.category !== S.filters.category) return false;
    if (S.filters.origin && p.origin.kind !== S.filters.origin) return false;
    if (S.filters.tag && !(p.tags || []).includes(S.filters.tag)) return false;
    if (kw) {
      const hay = [p.stage, p.name, p.title, p.summary, p.categoryLabel,
                   (p.stack || []).join(' '), (p.tags || []).join(' '),
                   p.origin.short, p.path].join(' ').toLowerCase();
      if (!hay.includes(kw)) return false;
    }
    return true;
  });
}

// ------------------------------------------------------------- 渲染：卡片
// 卡片上只放得下 6 个标签。但如果你正在按某个标签筛选，
// 那个标签必须出现在卡片上 —— 否则筛出来的卡片上找不到匹配项，会让人怀疑筛选是错的。
function visibleTags(p) {
  const all = p.tags || [];
  const active = S.filters.tag;
  if (active && all.includes(active)) {
    return [active, ...all.filter(t => t !== active)].slice(0, 6);
  }
  return all.slice(0, 6);
}

function cardHTML(p) {
  const st = uiState(p);
  const ports = p.ports || [];
  const main = ports[0];
  const morePorts = ports.length - 1;
  const shownTags = visibleTags(p);
  const hiddenTags = (p.tags || []).length - shownTags.length;

  const badges = [
    `<span class="badge badge-stage">${esc(p.stage)}</span>`,
    `<span class="badge badge-${esc(p.origin.kind)}">${esc(p.origin.short)}</span>`,
    `<span class="badge badge-cat">${esc(p.categoryLabel)}</span>`,
  ].join('');

  const portChips = main
    ? `<span class="port${main.listening ? ' is-on' : ''}" title="${esc(main.label || '')}">:${main.port}</span>` +
      (morePorts > 0 ? `<span class="port" title="共 ${ports.length} 个端口，详情里看">+${morePorts}</span>` : '')
    : '<span class="port">无端口</span>';

  const busy = st === 'busy';
  const running = st === 'running';

  let actions = '';
  if (p.launch.canStart) {
    if (busy) {
      actions += `<button class="btn" disabled>${esc(stateText(p))}…</button>`;
    } else if (running) {
      if (p.openUrl) actions += `<button class="btn btn-primary" data-act="open" data-id="${esc(p.id)}">打开</button>`;
      actions += `<button class="btn btn-danger" data-act="stop" data-id="${esc(p.id)}">停止</button>`;
    } else {
      actions += `<button class="btn btn-primary" data-act="start" data-id="${esc(p.id)}"
        ${p.declared === 'needs-build' ? 'title="构建产物不存在，启动会失败"' : ''}>启动</button>`;
    }
  }
  actions += `<button class="btn btn-ghost" data-act="detail" data-id="${esc(p.id)}">详情</button>`;

  const progress = busy
    ? `<div class="progress"><span>${esc(p.phase || stateText(p))}</span><span class="bar"></span></div>`
    : '';

  const errLine = (st === 'failed' && p.error)
    ? `<div class="card-warn"><span>⚠</span><span>${esc(p.error)}</span></div>` : '';

  const hijackLine = p.warning
    ? `<div class="card-warn"><span>⚠</span><span>${esc(p.warning)}</span></div>` : '';

  const partialLine = (p.downOptional || []).length
    ? `<div class="card-warn"><span>⚠</span><span>有模块没起来：${p.downOptional.map(d =>
        `<code>${d.port}</code> ${esc(d.label || '')}${d.why ? '（' + esc(d.why) + '）' : ''}`).join('；')}</span></div>` : '';

  const plannedLine = (p.declared === 'planned' && p.launch.reason)
    ? `<div class="card-warn" style="background:var(--plan-soft);color:var(--plan);border-color:color-mix(in srgb, var(--plan) 30%, transparent)">
         <span>◦</span><span>${esc(p.launch.reason)}</span></div>` : '';

  const pathLine = p.pathExists ? '' :
    `<div class="card-warn"><span>⚠</span><span>目录 ${esc(p.path)} 不存在</span></div>`;

  return `
  <article class="card" data-state="${esc(st)}" data-id="${esc(p.id)}">
    <div class="card-head">${badges}</div>
    <div class="card-title">
      <h3>${esc(p.name)}</h3>
      <span class="sub">${esc(p.title)}</span>
    </div>
    <p class="card-summary">${esc(p.summary)}</p>
    <div class="chips-row">${(p.stack || []).slice(0, 6).map(s => `<span class="tech">${esc(s)}</span>`).join('')}</div>
    <div class="chips-row">${shownTags.map(t =>
      `<span class="tag${t === S.filters.tag ? ' is-hit' : ''}">${esc(t)}</span>`).join('')}${
      hiddenTags > 0 ? `<span class="tag tag-more" title="还有 ${hiddenTags} 个标签，详情里看全部">+${hiddenTags}</span>` : ''}</div>
    ${hijackLine}${errLine}${partialLine}${plannedLine}${pathLine}
    ${progress}
    <div class="card-foot">
      <div class="card-meta">
        <span class="status" data-s="${esc(st)}"><span class="dot"></span>${esc(stateText(p))}</span>
        ${portChips}
      </div>
      <div class="card-actions">${actions}</div>
    </div>
  </article>`;
}

function render() {
  renderFilters();
  const list = filtered();
  const grid = $('#grid');
  grid.className = 'grid' + (S.view === 'list' ? ' is-list' : '');
  grid.innerHTML = list.map(cardHTML).join('');
  $('#empty').hidden = list.length > 0;

  const runningN = S.projects.filter(p => uiState(p) === 'running').length;
  $('#result-line').innerHTML = list.length === S.projects.length
    ? `共 <strong>${S.projects.length}</strong> 个项目，<strong>${runningN}</strong> 个在运行`
    : `筛出 <strong>${list.length}</strong> / ${S.projects.length} 个项目`;

  // 详情抽屉开着的话，同步刷新
  if (S.drawerId) refreshDrawerLive();
}

// ------------------------------------------------------------- 渲染：中间件
function renderMiddlewareSummary() {
  if (!S.sys) return;
  const mw = S.sys.middleware || [];
  const on = mw.filter(m => m.running).length;
  const bad = mw.filter(m => m.ownerStatus === 'wrong-process').length;
  $('#mw-summary').textContent =
    `${mw.length} 个 · ${on} 个在运行` + (bad ? ` · ⚠ ${bad} 个端口被别的程序占用` : '');
}

function renderMiddleware() {
  const mw = S.sys.middleware || [];
  const on = mw.filter(m => m.running).length;
  const bad = mw.filter(m => m.ownerStatus === 'wrong-process').length;
  $('#mw-summary').textContent =
    `${mw.length} 个 · ${on} 个在运行` + (bad ? ` · ⚠ ${bad} 个端口被别的程序占用` : '');

  $('#mw-grid').innerHTML = mw.map(m => {
    const hijack = m.ownerStatus === 'wrong-process';
    const cls = 'mw-item' + (m.running ? ' is-on' : '') + (hijack ? ' is-hijack' : '');
    const pill = m.running
      ? '<span class="mw-pill on">运行中</span>'
      : hijack ? '<span class="mw-pill warn">端口被占用</span>'
               : '<span class="mw-pill">已停止</span>';

    const ownerLine = m.pid
      ? `<div class="mw-owner">PID ${m.pid}${m.owner ? ' · ' + esc(m.owner) : ''}${hijack ? ' ← 不是这个服务' : ''}</div>`
      : '';

    let acts = '';
    if (m.managed) {
      acts = m.running
        ? `<button class="btn btn-sm btn-ghost" data-mw="stop" data-id="${esc(m.id)}">停止</button>`
        : `<button class="btn btn-sm" data-mw="start" data-id="${esc(m.id)}">启动</button>`;
    } else {
      acts = `<span class="mw-owner">工作台起不了，需手动启动</span>`;
    }

    const extra = Object.keys(m.extraPorts || {}).length
      ? `<span class="mw-owner">附加端口 ${Object.entries(m.extraPorts).map(([k, v]) => `${k}${v ? '✓' : '✗'}`).join(' ')}</span>`
      : '';

    return `<div class="${cls}">
      <div class="mw-row1">
        <span class="mw-name">${esc(m.name)}</span>
        <span class="mw-ver">${esc(m.version || '')}</span>
        <span class="mw-port"><span class="port${m.running ? ' is-on' : ''}">:${m.port}</span></span>
      </div>
      <div class="mw-row1">${pill}${ownerLine ? '' : ''}</div>
      ${ownerLine}
      <div class="mw-note">${esc(m.note || '')}</div>
      ${extra}
      <div class="mw-actions">${acts}</div>
    </div>`;
  }).join('');
}

// --------------------------------------------------------------- 渲染：抽屉
function refreshDrawerLive() {
  if (!S.drawerId) return;
  const p = S.projects.find(x => x.id === S.drawerId);
  if (!p) return;
  // 只更新会变的几个块，避免整块重绘把滚动位置和展开状态弄丢
  const live = $('#drawer-body [data-live]');
  if (live) live.innerHTML = drawerLiveHTML(p);
}

function drawerLiveHTML(p) {
  const ports = p.ports || [];
  return `
    <div class="sec">
      <h3>运行状态</h3>
      <dl class="kv">
        <dt>状态</dt><dd><span class="status" data-s="${esc(uiState(p))}"><span class="dot"></span>${esc(stateText(p))}</span>
          ${p.phase && uiState(p) === 'busy' ? ` · ${esc(p.phase)}` : ''}</dd>
        ${ports.length ? `<dt>端口</dt><dd>${ports.map(x =>
            `<span class="port${x.listening ? ' is-on' : ''}">:${x.port}</span> ${esc(x.label || '')}` +
            (x.ownerStatus === 'wrong-process' ? ` <span style="color:var(--warn)">← 被 ${esc(x.owner || '别的进程')} 占用</span>` : '')
          ).join('<br>')}</dd>` : ''}
        ${p.trackedPid ? `<dt>工作台启动的 PID</dt><dd><code>${p.trackedPid}</code></dd>` : ''}
        ${p.startedAt ? `<dt>本次启动于</dt><dd>${esc(relTime(p.startedAt))}</dd>` : ''}
      </dl>
      ${p.error ? `<div class="card-warn" style="margin-top:10px"><span>⚠</span><span>${esc(p.error)}</span></div>` : ''}
      ${p.warning ? `<div class="card-warn" style="margin-top:10px"><span>⚠</span><span>${esc(p.warning)}</span></div>` : ''}
      ${(p.downOptional || []).length ? `<div class="card-warn" style="margin-top:10px"><span>⚠</span><span>这些模块没起来：${
          p.downOptional.map(d => `<code>${d.port}</code> ${esc(d.label || '')}${d.why ? '（' + esc(d.why) + '）' : ''}`).join('；')
        }</span></div>` : ''}
    </div>

    <div class="sec">
      <h3>启动过程</h3>
      <div class="job-log" id="job-log">加载中…</div>
    </div>`;
}

function drawerHTML(p) {
  const origin = p.origin || {};
  const docs = Object.entries(p.docs || {});
  const mw = p.middleware || [];

  const build = p.build
    ? `<dt>构建产物</dt><dd>${p.build.exists ? '✅' : '❌ 不存在'} <code>${esc(p.build.artifact)}</code></dd>` : '';

  const cmd = p.launch.command
    ? `<div class="sec">
         <h3>启动命令</h3>
         <div class="code-head"><span>工作台执行的就是这段</span>
           <button class="btn btn-sm btn-ghost" data-copy="${esc(p.launch.command)}">复制</button></div>
         <pre class="code">${esc(p.launch.command)}</pre>
       </div>`
    : `<div class="sec"><h3>启动命令</h3>
         <div class="card-warn" style="background:var(--plan-soft);color:var(--plan);border-color:color-mix(in srgb, var(--plan) 30%, transparent)">
           <span>◦</span><span>${esc(p.launch.reason || '这个项目不支持一键启动')}</span></div></div>`;

  return `
    <p style="font-size:13.6px;color:var(--text-soft);line-height:1.7;margin-bottom:18px">${esc(p.summary)}</p>

    <div data-live>${drawerLiveHTML(p)}</div>

    <div class="sec">
      <h3>来源</h3>
      <dl class="kv">
        <dt>性质</dt><dd><span class="badge badge-${esc(origin.kind)}">${esc(origin.short || '')}</span> ${esc(origin.label || '')}</dd>
        ${origin.repo ? `<dt>仓库</dt><dd><a href="${esc(origin.repo)}" target="_blank" rel="noopener">${esc(origin.repo)}</a></dd>` : ''}
        ${origin.note ? `<dt>说明</dt><dd>${esc(origin.note)}</dd>` : ''}
      </dl>
    </div>

    <div class="sec">
      <h3>基本信息</h3>
      <dl class="kv">
        <dt>阶段</dt><dd>${esc(p.stage)}</dd>
        <dt>类别</dt><dd>${esc(p.categoryLabel)}</dd>
        <dt>目录</dt><dd><code>${esc(p.path)}</code> ${p.pathExists ? '' : '<span style="color:var(--warn)">（不存在）</span>'}</dd>
        <dt>绝对路径</dt><dd><code>${esc(p.absPath)}</code></dd>
        ${build}
        <dt>前置中间件</dt><dd>${mw.length ? mw.map(m =>
            `<span class="port${m.running ? ' is-on' : ''}">${esc(m.name)}${m.port ? ' :' + m.port : ''}</span>`).join(' ')
            : '无'}</dd>
      </dl>
    </div>

    <div class="sec">
      <h3>技术栈</h3>
      <div class="chips-row">${(p.stack || []).map(s => `<span class="tech">${esc(s)}</span>`).join('')}</div>
    </div>

    <div class="sec">
      <h3>标签</h3>
      <div class="chips-row">${(p.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    </div>

    ${cmd}

    ${docs.length ? `<div class="sec">
      <h3>相关文档</h3>
      <dl class="kv">${docs.map(([k, v]) =>
        `<dt>${esc(k)}</dt><dd>${/^https?:/.test(v)
          ? `<a href="${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a>`
          : `<code>${esc(v)}</code>`}</dd>`).join('')}</dl>
    </div>` : ''}

    <div class="sec">
      <h3>应用日志${p.logFile ? ` <span style="text-transform:none;font-weight:400">（${esc(p.logFile)}）</span>` : ''}</h3>
      ${p.logFile
        ? `<div class="code-head"><span>进程 stdout / stderr</span>
             <button class="btn btn-sm btn-ghost" data-log="${esc(p.id)}">刷新</button></div>
           <div class="log-view" id="app-log">点「刷新」加载</div>`
        : '<p style="font-size:13px;color:var(--text-mute)">这个项目没有日志文件。</p>'}
    </div>`;
}

function openDrawer(id) {
  const p = S.projects.find(x => x.id === id);
  if (!p) return;
  S.drawerId = id;
  $('#drawer-title').textContent = `${p.stage} · ${p.name}`;
  $('#drawer-sub').textContent = p.title;
  $('#drawer-body').innerHTML = drawerHTML(p);
  $('#drawer').hidden = false;
  loadJobLog(id);
  if (p.logFile) loadAppLog(id);
}

function closeDrawer() {
  S.drawerId = null;
  $('#drawer').hidden = true;
  $('#modal').hidden = true;
}

async function loadJobLog(id) {
  const box = $('#job-log');
  if (!box) return;
  try {
    const r = await api(`/api/projects/${id}/job`);
    const lines = r.jobLog || [];
    box.innerHTML = lines.length
      ? lines.map(l => {
          const cls = /❌|⚠/.test(l.text) ? 'err' : (/✅/.test(l.text) ? 'ok' : '');
          return `<span class="l ${cls}"><span class="t">${esc(l.t)}</span>${esc(l.text)}</span>`;
        }).join('')
      : '<span style="color:var(--text-mute)">本次会话还没有操作记录。点「启动」后这里会实时显示每一步。</span>';
    box.scrollTop = box.scrollHeight;
  } catch (e) {
    box.textContent = '读取失败：' + e.message;
  }
}

async function loadAppLog(id) {
  const box = $('#app-log');
  if (!box) return;
  box.textContent = '加载中…';
  try {
    const r = await api(`/api/projects/${id}/log?lines=200`);
    box.textContent = r.exists ? (r.lines.join('\n') || '（文件是空的）') : '（日志文件还没生成 —— 说明这个项目还没被启动过）';
    box.scrollTop = box.scrollHeight;
  } catch (e) {
    box.textContent = '读取失败：' + e.message;
  }
}

// ------------------------------------------------------------------ 操作 --
async function act(id, action) {
  if (S.pending.has(id)) return;
  const p = S.projects.find(x => x.id === id);
  if (!p) return;

  if (action === 'open') {
    if (!p.openUrl) return toast('这个项目没有配置打开地址', 'warn');
    window.open(p.openUrl, '_blank', 'noopener');
    return;
  }

  if (action === 'detail') return openDrawer(id);

  S.pending.add(id);
  try {
    await api(`/api/projects/${id}/${action}`, { method: 'POST', body: '{}' });
    // 立刻把本地状态推成「启动中」，让按钮马上变成不可点，不用等下一次轮询
    p.state = action === 'start' ? 'starting' : 'stopping';
    p.phase = action === 'start' ? '已提交，准备中…' : '正在停止…';
    render();
    if (S.drawerId === id) refreshDrawerLive();
    tick(1200);
  } catch (e) {
    toast(`操作失败：${e.message}`, 'bad');
  } finally {
    S.pending.delete(id);
  }
}

async function actMiddleware(id, action) {
  toast(`正在${action === 'start' ? '启动' : '停止'}…`, 'warn');
  try {
    const r = await api(`/api/middleware/${id}/${action}`, { method: 'POST', body: '{}' });
    toast(r.ok ? '命令已执行完成' : '命令返回非零退出码，看输出', r.ok ? 'ok' : 'bad');
    await loadSystem();
  } catch (e) {
    toast('失败：' + e.message, 'bad');
  }
}

async function reloadConfig() {
  try {
    const r = await api('/api/reload', { method: 'POST', body: '{}' });
    await loadConfig();
    await loadProjects();
    toast(`已重新读取 projects.json（${r.count} 个项目）`, 'ok');
  } catch (e) {
    toast('重载失败：' + e.message, 'bad');
  }
}

async function showTemplate() {
  try {
    const r = await api('/api/template');
    $('#modal-steps').innerHTML = (r.howto || []).map(s => `<li>${esc(s)}</li>`).join('');
    $('#modal-code').textContent = JSON.stringify(r.template, null, 2);
    $('#modal').hidden = false;
  } catch (e) {
    toast('读取模板失败：' + e.message, 'bad');
  }
}

async function copyText(t) {
  try {
    await navigator.clipboard.writeText(t);
    toast('已复制到剪贴板', 'ok');
  } catch (_) {
    toast('浏览器不允许自动复制，请手动选中', 'warn');
  }
}

// ------------------------------------------------------------------ 轮询 --
function tick(delay) {
  clearTimeout(S.timer);
  const busy = S.projects.some(p => p.state === 'starting' || p.state === 'stopping');
  const d = delay != null ? delay : (busy ? 1500 : 8000);
  S.timer = setTimeout(async () => {
    if (document.hidden) return tick(4000);
    try {
      await loadProjects();
      if (busy) await loadSystem();
      if (S.drawerId) loadJobLog(S.drawerId);
    } catch (e) {
      // 服务挂了就别刷屏，慢下来重试
      $('#result-line').innerHTML = `<span style="color:var(--bad)">连不上工作台服务：${esc(e.message)}</span>`;
    }
    tick();
  }, d);
}

// ------------------------------------------------------------------ 主题 --
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem('ws-theme', t); } catch (_) { /* 隐私模式 */ }
}

// ------------------------------------------------------------------ 事件 --
function bind() {
  // 筛选 chips（事件委托，chips 是动态渲染的）
  $('#filters').addEventListener('click', e => {
    const chip = e.target.closest('.chip[data-f]');
    if (!chip) return;
    const f = chip.dataset.f;
    const v = chip.dataset.v || null;
    S.filters[f] = (S.filters[f] === v) ? null : v;
    render();
  });

  // 卡片上的动作
  $('#grid').addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    act(btn.dataset.id, btn.dataset.act);
  });

  // 中间件面板
  $('#mw-grid').addEventListener('click', e => {
    const btn = e.target.closest('button[data-mw]');
    if (!btn) return;
    actMiddleware(btn.dataset.id, btn.dataset.mw);
  });

  $('#mw-toggle').addEventListener('click', () => {
    const head = $('#mw-toggle'), body = $('#mw-body');
    const open = head.getAttribute('aria-expanded') === 'true';
    head.setAttribute('aria-expanded', String(!open));
    body.hidden = open;
    if (!open && !S.sys) loadSystem();
  });

  // 搜索（防抖，输入时即时过滤）
  let sTimer = null;
  $('#search').addEventListener('input', e => {
    const v = e.target.value;
    $('#search-clear').hidden = !v;
    clearTimeout(sTimer);
    sTimer = setTimeout(() => { S.q = v; render(); }, 90);
  });
  $('#search-clear').addEventListener('click', () => {
    $('#search').value = ''; S.q = ''; $('#search-clear').hidden = true; render();
  });

  // 视图切换
  $$('.view-toggle .btn').forEach(b => b.addEventListener('click', () => {
    S.view = b.dataset.view;
    $$('.view-toggle .btn').forEach(x => x.classList.toggle('is-on', x === b));
    render();
  }));

  $('#btn-reset-filter').addEventListener('click', () => {
    S.filters = { state: null, category: null, origin: null, tag: null };
    S.q = ''; $('#search').value = ''; $('#search-clear').hidden = true;
    render();
  });

  $('#btn-refresh').addEventListener('click', reloadConfig);
  $('#btn-add').addEventListener('click', showTemplate);
  $('#btn-theme').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme;
    applyTheme(cur === 'dark' ? 'light' : 'dark');
  });

  // 抽屉 / 弹窗：关闭 + 内部按钮
  document.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) return closeDrawer();
    const copyBtn = e.target.closest('[data-copy]');
    if (copyBtn) return copyText(copyBtn.dataset.copy);
    const logBtn = e.target.closest('[data-log]');
    if (logBtn) return loadAppLog(logBtn.dataset.log);
  });
  $('#btn-copy-tpl').addEventListener('click', () => copyText($('#modal-code').textContent));

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeDrawer();
    // 「/」快速聚焦搜索框（输入框里按不算）
    if (e.key === '/' && !/^(INPUT|TEXTAREA)$/.test(document.activeElement.tagName)) {
      e.preventDefault(); $('#search').focus();
    }
  });
}

// ------------------------------------------------------------------ 启动 --
(async function boot() {
  try { applyTheme(localStorage.getItem('ws-theme') || 'auto'); } catch (_) { /* ignore */ }
  bind();
  try {
    await loadConfig();
    await loadProjects();
    await loadSystem();
  } catch (e) {
    toast('初始化失败：' + e.message, 'bad');
  }
  tick();
})();
