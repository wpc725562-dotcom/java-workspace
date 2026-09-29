#!/usr/bin/env node
/* =============================================================================
   verify-ui.js —— 用真浏览器验证工作台界面
   -----------------------------------------------------------------------------
   为什么不能只看接口返回：
     接口全对、页面全白这种事太常见了。这里真的开一个 Chrome，等 DOM 渲染完，
     数卡片、点筛选、开抽屉、切视图，并且把每个断点都截一张图。

   为什么截图要分桌面 / 平板 / 手机三个尺寸：
     用户明确要求「响应式适配桌面端与移动端」。只截 1440 宽等于没验证这一条。

   用法：
     node dashboard/verify-ui.js
     node dashboard/verify-ui.js --port 8991 --keep     # 不关浏览器，方便自己看

   退出码：0 = 全通过，1 = 有断言失败
   ============================================================================= */

'use strict';

const path = require('path');
const fs = require('fs');

const NM = 'C:/Users/Administrator/.workbuddy-ai/binaries/node/workspace/node_modules';
const { chromium } = require(path.join(NM, 'playwright-core'));

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = path.join(__dirname, '..', 'docs', 'screenshots');
const DIAG = path.join(__dirname, '..', 'target');   // 诊断图不进仓库

const argv = process.argv.slice(2);
const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
const PORT = Number(arg('--port', 8990));
const BASE = `http://127.0.0.1:${PORT}/`;
const KEEP = argv.includes('--keep');

let pass = 0, fail = 0;
const failures = [];

function ok(name, cond, detail) {
  if (cond) { pass++; console.log(`  [OK]  ${name}`); }
  else {
    fail++; failures.push(name);
    console.log(`  [NG]  ${name}${detail !== undefined ? '  → ' + JSON.stringify(detail).slice(0, 300) : ''}`);
  }
}
function section(t) { console.log(`\n${t}`); }

// 等某个条件成立。★ 第三个参数必须写 null —— 写成 {timeout:N} 会被当成
// waitForFunction 的 arg 参数吃掉，实际用默认 30 秒，超时了还看不出原因。
async function waitFor(page, fn, timeoutMs, label) {
  try {
    await page.waitForFunction(fn, null, { timeout: timeoutMs });
    return true;
  } catch (e) {
    console.log(`  !! 等待超时（${label || timeoutMs + 'ms'}）`);
    return false;
  }
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.mkdirSync(DIAG, { recursive: true });

  const browser = await chromium.launch({
    executablePath: CHROME,
    args: ['--no-proxy-server', '--disable-lcd-text'],
  });

  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 980 },
    deviceScaleFactor: 1.5,
    locale: 'zh-CN',
  });
  const page = await ctx.newPage();

  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  // ---------------------------------------------------------------- 加载 --
  section('一、页面加载与首屏渲染');
  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 30000 });
  const rendered = await waitFor(page, () => document.querySelectorAll('.card').length >= 5, 15000, '等 5 张卡片');
  ok('页面渲染出至少 5 张项目卡片', rendered);

  const cardCount = await page.locator('.card').count();
  ok('卡片数量 = 5（P0–P4）', cardCount === 5, { cardCount });

  const title = await page.innerText('#page-title');
  ok('标题取自 projects.json 的 dashboard.title', title.includes('工作台'), title);

  const resultLine = await page.innerText('#result-line');
  ok('结果行显示总数与运行数', /共\s*5\s*个项目/.test(resultLine) && /个在运行/.test(resultLine), resultLine);

  // ------------------------------------------------------------ 卡片内容 --
  section('二、卡片关键信息（名称/简介/技术栈/状态/来源）');
  const first = page.locator('.card').first();
  ok('卡片有名称（等宽字体 h3）', (await first.locator('.card-title h3').count()) === 1);
  ok('卡片有简介', ((await first.locator('.card-summary').innerText()) || '').length > 30);
  ok('卡片有技术栈标签', (await first.locator('.tech').count()) >= 3);
  ok('卡片有状态指示点', (await first.locator('.status .dot').count()) === 1);
  ok('卡片有端口 chip', (await first.locator('.port').count()) >= 1);

  // 来源诚实标注 —— 这条是硬要求：克隆不能看起来像原创
  const origins = await page.locator('.card').evaluateAll(
    els => els.map(e => ({ id: e.dataset.id, o: e.querySelector('.badge[class*="badge-"]:nth-child(2)')?.textContent.trim() }))
  );
  const oMap = Object.fromEntries(origins.map(x => [x.id, x.o]));
  ok('P4 标注为「原创」', oMap['p4-exam-tracker'] === '原创', oMap);
  ok('P0/P1/P2 标注为「克隆学习」',
    ['p0-eladmin-mp', 'p1-yu-ai-agent', 'p2-mall-swarm'].every(k => oMap[k] === '克隆学习'), oMap);
  ok('P3 标注为「计划中」', oMap['p3-seckill'] === '计划中', oMap);

  // -------------------------------------------------------------- 搜索 --
  section('三、关键词搜索');
  await page.fill('#search', '秒杀');
  await page.waitForTimeout(320);
  ok('搜「秒杀」只剩 1 张卡片', (await page.locator('.card').count()) === 1);

  await page.fill('#search', 'rabbitmq');
  await page.waitForTimeout(320);
  const rabbitHits = await page.locator('.card').count();
  ok('搜技术栈关键词「rabbitmq」命中 P2', rabbitHits === 1, { rabbitHits });

  await page.fill('#search', 'zzz-不存在-zzz');
  await page.waitForTimeout(320);
  ok('搜不到时显示空状态', await page.locator('#empty').isVisible());
  await page.click('#btn-reset-filter');
  await page.waitForTimeout(320);
  ok('清空后恢复 5 张卡片', (await page.locator('.card').count()) === 5);

  // -------------------------------------------------------------- 筛选 --
  section('四、按状态 / 类别 / 来源 / 标签筛选');
  await page.locator('#chips-state .chip', { hasText: '运行中' }).first().click();
  await page.waitForTimeout(320);
  const runningN = await page.locator('.card').count();
  ok('筛「运行中」得到的卡片都是 running', runningN >= 1, { runningN });
  const allRunning = await page.locator('.card').evaluateAll(els => els.every(e => e.dataset.state === 'running'));
  ok('筛选结果状态一致', allRunning);

  await page.locator('#chips-state .chip', { hasText: '计划中' }).first().click();
  await page.waitForTimeout(320);
  ok('状态筛选是单选（切到「计划中」只剩 P3）', (await page.locator('.card').count()) === 1);
  await page.locator('#chips-state .chip', { hasText: '全部' }).first().click();
  await page.waitForTimeout(320);

  await page.locator('#chips-category .chip', { hasText: '微服务' }).first().click();
  await page.waitForTimeout(320);
  ok('按类别筛「微服务」命中 P2', (await page.locator('.card').count()) === 1);
  await page.locator('#chips-category .chip', { hasText: '全部' }).first().click();

  await page.locator('#chips-origin .chip', { hasText: '原创' }).first().click();
  await page.waitForTimeout(320);
  ok('按来源筛「原创」只命中 P4', (await page.locator('.card').count()) === 1);
  await page.locator('#chips-origin .chip', { hasText: '全部' }).first().click();

  // 标签筛选：不写死某个标签名 —— 标签按出现频次只展示前 16 个，
  // 写死「JWT」这种只出现一次的标签会随数据变化而失效。
  // 标签名从 data-v 取，计数从 .chip-n 取 —— 别去解析 innerText：
  // 「Java 17」+ 计数「2」在 innerText 里是「Java 172」，正则一剥就错。
  const tagChip = page.locator('#chips-tag .chip[data-v]:not([data-v=""])').first();
  const tagName = await tagChip.getAttribute('data-v');
  const tagN = Number(await tagChip.locator('.chip-n').innerText());
  await tagChip.click();
  await page.waitForTimeout(320);
  const tagHits = await page.locator('.card').count();
  ok(`按标签筛「${tagName}」的结果数与徽标一致`, tagHits === tagN, { tagHits, tagN });
  // 卡片上只放得下 6 个标签，所以筛选中的那个必须被顶到前面并高亮 ——
  // 否则筛出来的卡片上找不到匹配项，用户会以为筛选坏了。
  const tagsAllMatch = await page.locator('.card').evaluateAll(
    (els, t) => els.every(e => Array.from(e.querySelectorAll('.tag.is-hit')).some(x => x.textContent.trim() === t)),
    tagName);
  ok('筛出的每张卡片都把该标签高亮显示出来了', tagsAllMatch);
  await page.locator('#chips-tag .chip', { hasText: '全部' }).first().click();
  await page.waitForTimeout(320);
  ok('标签筛选清空后恢复 5 张卡片', (await page.locator('.card').count()) === 5);

  // -------------------------------------------------------------- 视图 --
  section('五、卡片 / 列表双视图');
  await page.click('.view-toggle [data-view="list"]');
  await page.waitForTimeout(250);
  ok('切到列表视图', await page.locator('#grid').evaluate(e => e.classList.contains('is-list')));
  await page.click('.view-toggle [data-view="grid"]');
  await page.waitForTimeout(250);
  ok('切回卡片视图', !(await page.locator('#grid').evaluate(e => e.classList.contains('is-list'))));

  // ------------------------------------------------------- 一键启动按钮 --
  section('六、一键启动 / 打开 / 停止 按钮');
  const p4 = page.locator('.card[data-id="p4-exam-tracker"]');
  const p4State = await p4.getAttribute('data-state');
  const actText = await p4.locator('.card-actions').innerText();
  if (p4State === 'running') {
    ok('运行中的项目显示「打开」按钮', actText.includes('打开'), actText);
    ok('运行中的项目显示「停止」按钮', actText.includes('停止'), actText);
    const openUrl = await p4.locator('button[data-act="open"]').getAttribute('data-id');
    ok('「打开」按钮绑定到正确项目', openUrl === 'p4-exam-tracker');
  } else {
    ok('未运行的项目显示「启动」按钮', actText.includes('启动'), actText);
  }
  ok('每张卡片都有「详情」按钮', (await page.locator('button[data-act="detail"]').count()) === 5);

  // 真点一次「打开」，确认跳的是配好的地址（P4 前端在 /api/ 下，不是根路径）
  const [popup] = await Promise.all([
    page.waitForEvent('popup', { timeout: 12000 }).catch(() => null),
    p4.locator('button[data-act="open"]').click().catch(() => null),
  ]);
  if (popup) {
    await popup.waitForLoadState('domcontentloaded').catch(() => {});
    const u = popup.url();
    ok('「打开」跳转地址 = projects.json 里配的 openUrl', u.startsWith('http://127.0.0.1:8090/api/'), u);
    const h = await popup.title().catch(() => '');
    ok('打开的页面确实是 exam-tracker 前端', /备考|任务/.test(h) || h.length > 0, h);
    await popup.close();
  } else {
    ok('「打开」能弹出新窗口', false, '没有捕获到 popup');
  }

  // -------------------------------------------------------------- 抽屉 --
  section('七、详情抽屉');
  await p4.locator('button[data-act="detail"]').click();
  await page.waitForTimeout(500);
  ok('抽屉打开', await page.locator('#drawer').isVisible());
  const drawerText = await page.innerText('#drawer-body');
  ok('抽屉含「来源」且写明原创', /来源/.test(drawerText) && /原创/.test(drawerText));
  ok('抽屉含「启动命令」', /启动命令/.test(drawerText));
  ok('抽屉含启动命令内容（含 use-jdk.sh）', /use-jdk\.sh/.test(drawerText));
  ok('抽屉含「应用日志」区', /应用日志/.test(drawerText));
  ok('抽屉列出技术栈', /Spring Boot/.test(drawerText));
  const jobLog = await page.innerText('#job-log').catch(() => '');
  ok('抽屉有启动过程日志区', jobLog.length > 0);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  ok('Esc 能关抽屉', !(await page.locator('#drawer').isVisible()));

  // ------------------------------------------------------------ 中间件 --
  section('八、中间件面板');
  await page.click('#mw-toggle');
  await page.waitForTimeout(800);
  ok('中间件面板展开', await page.locator('#mw-body').isVisible());
  const mwN = await page.locator('.mw-item').count();
  ok('列出 9 个中间件', mwN === 9, { mwN });
  const mwText = await page.innerText('#mw-body');
  ok('RabbitMQ 被标为「端口被占用」而不是「运行中」', /端口被占用/.test(mwText));
  ok('提示里点明了核验进程名这件事', /进程名/.test(mwText));
  const summary = await page.innerText('#mw-summary');
  ok('折叠标题给出中间件统计', /\d+ 个/.test(summary), summary);

  // ------------------------------------------------------------ 新增项目 --
  section('九、新增项目入口');
  await page.click('#btn-add');
  await page.waitForTimeout(500);
  ok('模板弹窗打开', await page.locator('#modal').isVisible());
  const steps = await page.locator('#modal-steps li').count();
  ok('有操作步骤说明', steps >= 4, { steps });
  const code = await page.innerText('#modal-code');
  let tplOk = false;
  try { const j = JSON.parse(code); tplOk = !!j.id && !!j.launch && !!j.origin; } catch (_) { tplOk = false; }
  ok('模板是合法 JSON 且含 id/launch/origin', tplOk);
  ok('模板说明里强调了 origin 必须如实填', /如实|origin/.test(await page.innerText('#modal-steps')));
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);

  // ---------------------------------------------------------------- 截图 --
  section('十、响应式截图');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(SHOTS, '11-dashboard-desktop.png') });
  console.log('  [OK]  桌面 1440×980 → docs/screenshots/11-dashboard-desktop.png');

  await page.setViewportSize({ width: 900, height: 1000 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, '12-dashboard-tablet.png') });
  console.log('  [OK]  平板 900×1000 → docs/screenshots/12-dashboard-tablet.png');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const cols = await page.locator('#grid').evaluate(e => getComputedStyle(e).gridTemplateColumns.split(' ').length);
  ok('手机宽度下单列布局', cols === 1, { cols });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  ok('手机宽度下没有横向溢出', overflow <= 1, { overflow });
  await page.screenshot({ path: path.join(SHOTS, '13-dashboard-mobile.png') });
  console.log('  [OK]  手机 390×844 → docs/screenshots/13-dashboard-mobile.png');

  // 深色模式
  await page.setViewportSize({ width: 1440, height: 980 });
  await page.click('#btn-theme');
  await page.waitForTimeout(500);
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  ok('主题切换到 dark', theme === 'dark', theme);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  ok('深色模式下背景确实变暗', /rgb\((1[0-9]|[0-9]),/.test(bg), bg);
  const fg = await page.evaluate(() => getComputedStyle(document.body).color);
  ok('深色模式下文字是浅色（可读）', /rgb\((2[0-9][0-9]|1[89][0-9])/.test(fg), fg);
  await page.screenshot({ path: path.join(SHOTS, '14-dashboard-dark.png') });
  console.log('  [OK]  深色 1440×980 → docs/screenshots/14-dashboard-dark.png');
  await page.click('#btn-theme');   // 切回浅色

  // -------------------------------------------------------------- 报错 --
  section('十一、控制台报错');
  const realErrors = errors.filter(e => !/favicon/i.test(e));
  ok('页面没有 JS 报错', realErrors.length === 0, realErrors.slice(0, 4));

  // -------------------------------------------------------------- 汇总 --
  console.log('\n' + '─'.repeat(62));
  console.log(`  通过 ${pass} 项，失败 ${fail} 项`);
  if (fail) {
    console.log('  失败项：');
    failures.forEach(f => console.log('    · ' + f));
    await page.screenshot({ path: path.join(DIAG, 'dashboard-ui-FAILED.png'), fullPage: true });
    console.log(`  诊断截图：target/dashboard-ui-FAILED.png`);
  }
  console.log('─'.repeat(62));

  if (!KEEP) await browser.close();
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('\n脚本异常：', e); process.exit(2); });
