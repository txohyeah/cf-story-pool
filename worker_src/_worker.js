// cf-story-pool 需求池 — CF Pages + D1（附件存 D1 BLOB；R2 预留未启用）
// 认证/会话/限速照抄 zhixidao（PBKDF2 + session + 每 IP 每小时 10 次失败限速）
// 业务：需求 CRUD + 状态机 + 标签 + 工作项清单 + 截图 + FTS5 去重提示
// bindings: env.DB(D1) / env.ASSETS(静态)
const COOKIE = 'storypool_auth';
const SESSION_DAYS = 30;
const PBKDF2_ITER = 100000;
const PBKDF2_KEYLEN = 32;

const STATUSES = ['submitted', 'confirmed', 'scheduled', 'fixed', 'verified', 'closed', 'dup_closed'];
const OPEN_STATUSES = ['submitted', 'confirmed', 'scheduled', 'fixed', 'verified'];
const TYPES = ['bug', 'req', 'opt'];
const URGENCIES = ['normal', 'urgent'];
const SEVERITIES = ['critical', 'major', 'general', 'watch'];       // R3：关键/重大/一般/观察（CSV-14 口径）
const ROOT_CAUSES = ['config', 'defect', 'usage', 'external', 'data', 'requirement']; // R3：根因六分类
const MAX_ATTACH = 3;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const EXTS = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' };

// ---------- utils ----------
const enc = new TextEncoder();
function b64FromBytes(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}
function bytesFromB64(s) {
  const bin = atob(s);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
function json(data, status) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }
  });
}
function nowIso() { return new Date().toISOString(); }

// ---------- password ----------
async function deriveBytes(passphrase, saltB64, iter, keylen) {
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(passphrase), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: bytesFromB64(saltB64), iterations: iter },
    keyMaterial, keylen * 8);
  return new Uint8Array(bits);
}
async function hashPass(passphrase) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const bits = await deriveBytes(passphrase, b64FromBytes(salt), PBKDF2_ITER, PBKDF2_KEYLEN);
  return 'pbkdf2$' + PBKDF2_ITER + '$' + b64FromBytes(salt) + '$' + b64FromBytes(bits);
}
async function verifyPass(passphrase, stored) {
  try {
    const parts = (stored || '').split('$');
    if (parts.length !== 4 || parts[0] !== 'pbkdf2') return false;
    const iter = parseInt(parts[1], 10);
    const bits = await deriveBytes(passphrase, parts[2], iter, PBKDF2_KEYLEN);
    const expect = bytesFromB64(parts[3]);
    if (bits.length !== expect.length) return false;
    let diff = 0;
    for (let i = 0; i < bits.length; i++) diff |= bits[i] ^ expect[i];
    return diff === 0;
  } catch (e) { return false; }
}

// ---------- session ----------
function cookieToken(request) {
  const cookie = request.headers.get('Cookie') || '';
  const m = cookie.match(new RegExp('(?:^|;\\s*)' + COOKIE + '=([^;]+)'));
  return m ? m[1] : null;
}
async function currentUser(request, env) {
  const token = cookieToken(request);
  if (!token) return null;
  const row = await env.DB.prepare(
    `SELECT s.token, s.expires_at, u.id AS user_id, u.username, u.role, u.active
     FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?`
  ).bind(token).first();
  if (!row) return null;
  if (row.expires_at < nowIso() || !row.active) {
    await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
    return null;
  }
  return { token, userId: row.user_id, username: row.username, role: row.role };
}
function cookieFor(token) {
  return `${COOKIE}=${token}; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=${SESSION_DAYS * 86400}`;
}
function clearCookieFor() {
  return `${COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Secure; Max-Age=0`;
}
async function serveStatic(urlstr, env) {
  const r = await env.ASSETS.fetch(urlstr);
  const h = new Headers(r.headers);
  h.set('Cache-Control', 'no-store');
  return new Response(r.body, { status: r.status, headers: h });
}
async function issueSession(user, env) {
  const token = crypto.randomUUID();
  const exp = addDays(SESSION_DAYS);
  await env.DB.prepare('INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)')
    .bind(token, user.id, exp).run();
  return new Response(JSON.stringify({ ok: true, username: user.username }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'Set-Cookie': cookieFor(token)
    }
  });
}
function addDays(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString();
}

// ---------- 登录限速：每 IP 每小时最多 10 次失败（成功即清零） ----------
const LOGIN_MAX_FAILS = 10;
const LOGIN_WINDOW_MS = 3600 * 1000;
function clientIp(request) {
  return request.headers.get('CF-Connecting-IP')
    || (request.headers.get('X-Forwarded-For') || '').split(',')[0].trim()
    || 'unknown';
}
async function throttleStatus(request, env) {
  const ip = clientIp(request);
  const row = await env.DB.prepare('SELECT fail_count, window_start FROM login_throttle WHERE ip = ?')
    .bind(ip).first();
  if (!row) return { ip, blocked: false };
  const cutoff = new Date(Date.now() - LOGIN_WINDOW_MS).toISOString();
  if (row.window_start > cutoff && row.fail_count >= LOGIN_MAX_FAILS) {
    const retryAfter = Math.max(1, Math.ceil((Date.parse(row.window_start) + LOGIN_WINDOW_MS - Date.now()) / 1000));
    return { ip, blocked: true, retryAfter };
  }
  return { ip, blocked: false };
}
async function throttleRecordFail(env, ip) {
  const now = new Date().toISOString();
  const cutoff = new Date(Date.now() - LOGIN_WINDOW_MS).toISOString();
  await env.DB.prepare(
    `INSERT INTO login_throttle (ip, fail_count, window_start) VALUES (?1, 1, ?2)
     ON CONFLICT(ip) DO UPDATE SET
       fail_count = CASE WHEN login_throttle.window_start <= ?3 THEN 1 ELSE login_throttle.fail_count + 1 END,
       window_start = CASE WHEN login_throttle.window_start <= ?3 THEN ?2 ELSE login_throttle.window_start END`
  ).bind(ip, now, cutoff).run();
}
async function throttleClear(env, ip) {
  await env.DB.prepare('DELETE FROM login_throttle WHERE ip = ?').bind(ip).run();
}

// ---------- login/logout/me ----------
async function apiLogin(request, env) {
  const throttle = await throttleStatus(request, env);
  if (throttle.blocked) {
    return new Response(JSON.stringify({ error: '失败次数过多，请稍后再试' }), {
      status: 429,
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Retry-After': String(throttle.retryAfter)
      }
    });
  }
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const username = (body.username || '').trim();
  const password = body.password || '';
  if (!username || !password) return json({ error: '请输入用户名和密码' }, 400);
  const user = await env.DB.prepare('SELECT * FROM users WHERE username = ? AND active = 1').bind(username).first();
  const ok = user ? await verifyPass(password, user.pw_hash) : false;
  if (!ok) {
    await throttleRecordFail(env, throttle.ip);
    return json({ error: '用户名或密码错误' }, 401);
  }
  await throttleClear(env, throttle.ip);
  return issueSession(user, env);
}
async function apiLogout(request, env) {
  const token = cookieToken(request);
  if (token) await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
  return new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Set-Cookie': clearCookieFor() }
  });
}
async function apiMe(request, env) {
  const u = await currentUser(request, env);
  if (!u) return json({ authed: false }, 200);
  const row = await env.DB.prepare('SELECT display_name FROM users WHERE id = ?').bind(u.userId).first();
  return json({ authed: true, username: u.username, display_name: row ? row.display_name : u.username, user_id: u.userId });
}

// ---------- 改密码（保留当前会话，踢掉其他设备） ----------
async function changeMyPassword(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const current = body.current || '';
  const next = (body.next || '').trim();
  if (!next || next.length < 6) return json({ error: '新密码至少 6 位' }, 400);
  const user = await env.DB.prepare('SELECT * FROM users WHERE id = ?').bind(u.userId).first();
  if (!user) return json({ error: '用户不存在' }, 404);
  const ok = await verifyPass(current, user.pw_hash);
  if (!ok) return json({ error: '当前密码错误' }, 400);
  const hash = await hashPass(next);
  await env.DB.prepare('UPDATE users SET pw_hash = ? WHERE id = ?').bind(hash, u.userId).run();
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ? AND token != ?').bind(u.userId, u.token).run();
  return json({ ok: true });
}

// ---------- 项目：统计列表 / 创建 / 删除（仅空项目） ----------
async function apiProjectList(request, env) {
  const rows = (await env.DB.prepare(
    `SELECT p.id, p.name,
            COUNT(r.id) AS total,
            COALESCE(SUM(CASE WHEN r.status NOT IN ('closed','dup_closed') THEN 1 ELSE 0 END), 0) AS open
     FROM projects p LEFT JOIN requirements r ON r.project_id = p.id
     WHERE p.is_active = 1
     GROUP BY p.id ORDER BY p.id`).all()).results;
  return json({ ok: true, projects: rows });
}
async function apiProjectCreate(request, env) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const name = (body.name || '').trim().slice(0, 50);
  if (!name) return json({ error: '项目名称必填' }, 400);
  const dup = await env.DB.prepare('SELECT id FROM projects WHERE name = ?').bind(name).first();
  if (dup) return json({ error: '项目已存在' }, 400);
  const ins = await env.DB.prepare('INSERT INTO projects (name, is_active) VALUES (?, 1)').bind(name).run();
  return json({ ok: true, id: ins.meta.last_row_id, name });
}
async function apiProjectDelete(request, env, id) {
  const p = await env.DB.prepare('SELECT id FROM projects WHERE id = ?').bind(id).first();
  if (!p) return json({ error: '项目不存在' }, 404);
  const n = (await env.DB.prepare('SELECT COUNT(*) AS n FROM requirements WHERE project_id = ?').bind(id).first()).n;
  if (n > 0) return json({ error: '项目下仍有需求，不能删除' }, 400);
  // 先清标签归属引用，否则外键约束会让 DELETE 失败
  await env.DB.batch([
    env.DB.prepare('DELETE FROM project_tags WHERE project_id = ?').bind(id),
    env.DB.prepare('DELETE FROM projects WHERE id = ?').bind(id),
  ]);
  return json({ ok: true });
}

// ---------- 字典 ----------
async function apiBootstrap(request, env) {
  const projects = (await env.DB.prepare(
    'SELECT id, name FROM projects WHERE is_active = 1 ORDER BY id').all()).results;
  // 标签按项目隔离：一行一 (标签, 项目)，project_tags 无记录的孤儿标签不返回
  const tags = (await env.DB.prepare(
    `SELECT t.id, t.name, pt.project_id FROM tags t
     JOIN project_tags pt ON pt.tag_id = t.id ORDER BY t.name LIMIT 500`).all()).results;
  const users = (await env.DB.prepare(
    'SELECT id, username, display_name FROM users WHERE active = 1 ORDER BY id').all()).results;
  return json({ ok: true, projects, tags, users, statuses: STATUSES, open_statuses: OPEN_STATUSES, types: TYPES, urgencies: URGENCIES });
}
async function apiTagList(request, env) {
  const url = new URL(request.url);
  const q = (url.searchParams.get('q') || '').trim();
  let rows;
  if (q) {
    rows = (await env.DB.prepare('SELECT id, name FROM tags WHERE name LIKE ? ORDER BY name LIMIT 50')
      .bind('%' + q.replace(/[%_]/g, '') + '%').all()).results;
  } else {
    rows = (await env.DB.prepare('SELECT id, name FROM tags ORDER BY name LIMIT 50').all()).results;
  }
  return json({ ok: true, tags: rows });
}

// ---------- 标签解析：名字数组 → 确保存在并归属项目 → 返回 id 数组 ----------
async function resolveTagIds(env, names, projectId) {
  const clean = [];
  const seen = new Set();
  for (const n0 of (names || [])) {
    const n = String(n0 || '').trim().slice(0, 30);
    if (!n || seen.has(n)) continue;
    seen.add(n);
    clean.push(n);
    if (clean.length >= 10) break;
  }
  if (!clean.length) return [];
  for (const n of clean) {
    await env.DB.prepare('INSERT OR IGNORE INTO tags (name) VALUES (?)').bind(n).run();
  }
  const placeholders = clean.map(() => '?').join(',');
  const rows = (await env.DB.prepare(
    `SELECT id, name FROM tags WHERE name IN (${placeholders})`).bind(...clean).all()).results;
  // 标签与项目绑定：新标签/已有标签都确保挂到当前项目下（幂等）
  if (projectId) {
    const binds = rows.map(r => env.DB.prepare(
      'INSERT OR IGNORE INTO project_tags (tag_id, project_id) VALUES (?, ?)').bind(r.id, projectId));
    if (binds.length) await env.DB.batch(binds);
  }
  const byName = new Map(rows.map(r => [r.name, r.id]));
  return clean.map(n => byName.get(n)).filter(Boolean);
}

// ---------- 附件 token 校验（D1 BLOB 方案：token 即 attachment_blobs 主键） ----------
function validAttachToken(k) {
  return typeof k === 'string' && /^[A-Za-z0-9-]{8,64}$/.test(k);
}

// ---------- 建需求 ----------
async function apiReqCreate(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const title = (body.title || '').trim().slice(0, 200);
  if (!title) return json({ error: '标题必填' }, 400);
  const projectId = parseInt(body.project_id, 10);
  if (!projectId) return json({ error: '请选择研发项目' }, 400);
  const proj = await env.DB.prepare('SELECT id FROM projects WHERE id = ? AND is_active = 1').bind(projectId).first();
  if (!proj) return json({ error: '项目不存在' }, 400);
  const type = TYPES.includes(body.type) ? body.type : 'req';
  const urgency = URGENCIES.includes(body.urgency) ? body.urgency : 'normal';
  const description = (body.description || '').slice(0, 5000);
  const attaches = Array.isArray(body.attachments) ? body.attachments.slice(0, MAX_ATTACH) : [];
  for (const a of attaches) {
    if (!a || !validAttachToken(a.key)) return json({ error: '附件参数非法' }, 400);
  }
  const tagIds = await resolveTagIds(env, body.tags, projectId);
  const severity = SEVERITIES.includes(body.severity) ? body.severity : '';
  const rootCause = ROOT_CAUSES.includes(body.root_cause) ? body.root_cause : '';
  const refCode = String(body.ref_code || '').trim().slice(0, 60);
  const relatedCodes = JSON.stringify((Array.isArray(body.related_codes) ? body.related_codes : [])
    .map(x => String(x).trim().slice(0, 60)).filter(Boolean).slice(0, 20));
  const ins = await env.DB.prepare(
    `INSERT INTO requirements (project_id, title, description, type, urgency, status, channel, created_by, updated_at, severity, root_cause, ref_code, related_codes)
     VALUES (?, ?, ?, ?, ?, 'submitted', 'web', ?, ?, ?, ?, ?, ?)`)
    .bind(projectId, title, description, type, urgency, u.userId, nowIso(), severity, rootCause, refCode, relatedCodes).run();
  const reqId = ins.meta.last_row_id;
  const stmts = [];
  for (const tid of tagIds) {
    stmts.push(env.DB.prepare('INSERT OR IGNORE INTO requirement_tags (req_id, tag_id) VALUES (?, ?)').bind(reqId, tid));
  }
  for (const a of attaches) {
    stmts.push(env.DB.prepare(
      'INSERT INTO attachments (req_id, store_key, orig_name, size) VALUES (?, ?, ?, ?)')
      .bind(reqId, a.key, String(a.name || '').slice(0, 200), parseInt(a.size, 10) || 0));
  }
  stmts.push(env.DB.prepare(
    `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'create', ?)`)
    .bind(reqId, u.userId, JSON.stringify({ title })));
  if (stmts.length) await env.DB.batch(stmts);
  return json({ ok: true, id: reqId });
}

// ---------- 列表 ----------
// 中文搜索：FTS5 默认 unicode61 分词器把连续中文整段当一个 token，子串搜不到（如搜"药杯"命中不了"药杯打印加条件"）。
// 数据量小（百条级），直接用 LIKE 子串匹配；FTS 表与触发器保留但不走查询路径。
function likeEsc(t) { return '%' + String(t).replace(/[\\%_]/g, c => '\\' + c) + '%'; }
function qTokens(q) { return String(q || '').trim().split(/\s+/).filter(Boolean).slice(0, 8); }
async function apiReqList(request, env, u) {
  const url = new URL(request.url);
  const page = Math.max(1, parseInt(url.searchParams.get('page'), 10) || 1);
  const pageSize = Math.min(50, Math.max(1, parseInt(url.searchParams.get('page_size'), 10) || 50));
  const where = [];
  const args = [];
  const status = (url.searchParams.get('status') || '').trim();
  if (status === 'open') {
    where.push(`r.status NOT IN ('closed','dup_closed')`);
  } else if (status) {
    const ss = status.split(',').filter(s => STATUSES.includes(s));
    if (ss.length) { where.push(`r.status IN (${ss.map(() => '?').join(',')})`); args.push(...ss); }
  }
  const project = parseInt(url.searchParams.get('project'), 10);
  if (project) { where.push('r.project_id = ?'); args.push(project); }
  const type = url.searchParams.get('type');
  if (TYPES.includes(type)) { where.push('r.type = ?'); args.push(type); }
  const urgency = url.searchParams.get('urgency');
  if (URGENCIES.includes(urgency)) { where.push('r.urgency = ?'); args.push(urgency); }
  const severity = url.searchParams.get('severity');
  if (severity === 'none') { where.push("r.severity = ''"); }
  else if (SEVERITIES.includes(severity)) { where.push('r.severity = ?'); args.push(severity); }
  const ref = (url.searchParams.get('ref') || '').trim();
  if (ref) { where.push('r.ref_code = ?'); args.push(ref.slice(0, 60)); }
  const tag = (url.searchParams.get('tag') || '').trim();
  if (tag) {
    where.push(`EXISTS (SELECT 1 FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
      WHERE rt.req_id = r.id AND t.name = ?)`);
    args.push(tag);
  }
  const q = (url.searchParams.get('q') || '').trim();
  if (q) {
    const tokens = qTokens(q);
    if (tokens.length) {
      where.push('(' + tokens.map(() =>
        `(r.title LIKE ? ESCAPE '\\' OR r.description LIKE ? ESCAPE '\\')`).join(' OR ') + ')');
      for (const t of tokens) { const like = likeEsc(t); args.push(like, like); }
    } else { where.push('0 = 1'); }
  }
  const assignee = url.searchParams.get('assignee');
  if (assignee === 'me') {
    where.push(`EXISTS (SELECT 1 FROM checklist_items c
      WHERE c.req_id = r.id AND c.assignee_id = ? AND c.status != 'done')`);
    args.push(u.userId);
  }
  const W = where.length ? 'WHERE ' + where.join(' AND ') : '';
  const total = (await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM requirements r ${W}`).bind(...args).first()).n;
  const items = (await env.DB.prepare(
    `SELECT r.id, r.title, r.type, r.urgency, r.status, r.created_at, r.updated_at,
            r.severity, r.root_cause, r.ref_code,
            p.name AS project_name, us.display_name AS creator_name
     FROM requirements r
     JOIN projects p ON p.id = r.project_id
     LEFT JOIN users us ON us.id = r.created_by
     ${W} ORDER BY r.updated_at DESC, r.id DESC LIMIT ? OFFSET ?`)
    .bind(...args, pageSize, (page - 1) * pageSize).all()).results;
  const ids = items.map(x => x.id);
  let tagMap = new Map();
  let chkMap = new Map();
  if (ids.length) {
    const ph = ids.map(() => '?').join(',');
    const tg = (await env.DB.prepare(
      `SELECT rt.req_id, t.name FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
       WHERE rt.req_id IN (${ph}) ORDER BY t.name`).bind(...ids).all()).results;
    for (const row of tg) {
      if (!tagMap.has(row.req_id)) tagMap.set(row.req_id, []);
      tagMap.get(row.req_id).push(row.name);
    }
    const ck = (await env.DB.prepare(
      `SELECT req_id, COUNT(*) AS n FROM checklist_items
       WHERE req_id IN (${ph}) AND status != 'done' GROUP BY req_id`).bind(...ids).all()).results;
    for (const row of ck) chkMap.set(row.req_id, row.n);
  }
  return json({
    ok: true, items: items.map(x => ({
      ...x, tags: tagMap.get(x.id) || [], open_tasks: chkMap.get(x.id) || 0
    })), total, page, pages: Math.max(1, Math.ceil(total / pageSize))
  });
}

// ---------- 我的工作项 ----------
// 支持与需求列表同名的过滤参数 project/status/type/tag/q（套在 JOIN 的需求上）；
// q 同时匹配需求标题/描述与工作项内容。不带参数时行为与原版完全一致。
async function apiMyWork(request, env, u) {
  const url = new URL(request.url);
  const where = [`c.assignee_id = ?`, `c.status != 'done'`,
    `r.status NOT IN ('closed','dup_closed')`];
  const args = [u.userId];
  const status = (url.searchParams.get('status') || '').trim();
  if (status === 'open') {
    // 未关闭 = 默认条件，无需追加
  } else if (status) {
    const ss = status.split(',').filter(s => STATUSES.includes(s));
    if (ss.length) { where.push(`r.status IN (${ss.map(() => '?').join(',')})`); args.push(...ss); }
  }
  const project = parseInt(url.searchParams.get('project'), 10);
  if (project) { where.push('r.project_id = ?'); args.push(project); }
  const type = url.searchParams.get('type');
  if (TYPES.includes(type)) { where.push('r.type = ?'); args.push(type); }
  const urgency = url.searchParams.get('urgency');
  if (URGENCIES.includes(urgency)) { where.push('r.urgency = ?'); args.push(urgency); }
  const severity = url.searchParams.get('severity');
  if (severity === 'none') { where.push("r.severity = ''"); }
  else if (SEVERITIES.includes(severity)) { where.push('r.severity = ?'); args.push(severity); }
  const ref = (url.searchParams.get('ref') || '').trim();
  if (ref) { where.push('r.ref_code = ?'); args.push(ref.slice(0, 60)); }
  const tag = (url.searchParams.get('tag') || '').trim();
  if (tag) {
    where.push(`EXISTS (SELECT 1 FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
      WHERE rt.req_id = r.id AND t.name = ?)`);
    args.push(tag);
  }
  const q = (url.searchParams.get('q') || '').trim();
  if (q) {
    const tokens = qTokens(q);
    if (tokens.length) {
      where.push('(' + tokens.map(() =>
        `(r.title LIKE ? ESCAPE '\\' OR r.description LIKE ? ESCAPE '\\' OR c.content LIKE ? ESCAPE '\\')`).join(' OR ') + ')');
      for (const t of tokens) { const like = likeEsc(t); args.push(like, like, like); }
    } else { where.push('0 = 1'); }
  }
  const items = (await env.DB.prepare(
    `SELECT c.id, c.content, c.status, c.req_id, r.title, r.status AS req_status,
            us.display_name AS creator_name, r.updated_at
     FROM checklist_items c
     JOIN requirements r ON r.id = c.req_id
     LEFT JOIN users us ON us.id = r.created_by
     WHERE ${where.join(' AND ')}
     ORDER BY r.updated_at DESC, c.id ASC LIMIT 100`).bind(...args).all()).results;
  return json({ ok: true, items });
}

// ---------- 详情 ----------
async function apiReqDetail(request, env, u, id) {
  const r = (await env.DB.prepare(
    `SELECT r.*, p.name AS project_name, us.display_name AS creator_name
     FROM requirements r
     JOIN projects p ON p.id = r.project_id
     LEFT JOIN users us ON us.id = r.created_by
     WHERE r.id = ?`).bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  // 互不依赖的 5 路查询并行（原串行 5 次 D1 往返，是详情页慢的主因之一）
  const [tagsR, attsR, ckR, evR, dupOf] = await Promise.all([
    env.DB.prepare(
      `SELECT t.id, t.name FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
       WHERE rt.req_id = ? ORDER BY t.name`).bind(id).all(),
    env.DB.prepare(
      `SELECT id, store_key, orig_name, size, created_at FROM attachments
       WHERE req_id = ? ORDER BY id`).bind(id).all(),
    env.DB.prepare(
      `SELECT c.id, c.content, c.status, c.sort_order, c.assignee_id, us.display_name AS assignee_name
       FROM checklist_items c LEFT JOIN users us ON us.id = c.assignee_id
       WHERE c.req_id = ? ORDER BY c.sort_order, c.id`).bind(id).all(),
    env.DB.prepare(
      `SELECT e.id, e.action, e.detail, e.created_at, e.ctype, us.display_name AS actor_name
       FROM events e LEFT JOIN users us ON us.id = e.actor_id
       WHERE e.req_id = ? ORDER BY e.created_at ASC, e.id ASC`).bind(id).all(),
    r.duplicate_of
      ? env.DB.prepare('SELECT id, title, status FROM requirements WHERE id = ?')
          .bind(r.duplicate_of).first()
      : Promise.resolve(null)
  ]);
  return json({ ok: true, req: r, tags: tagsR.results, attachments: attsR.results,
    checklist: ckR.results, events: evR.results, dup_of: dupOf });
}

// ---------- 编辑/流转 ----------
async function apiReqPatch(request, env, u, id) {
  const r = (await env.DB.prepare('SELECT * FROM requirements WHERE id = ?').bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const op = body.op;
  if (op === 'status') {
    const to = body.status;
    if (!STATUSES.includes(to)) return json({ error: '非法状态' }, 400);
    let dupOf = r.duplicate_of;
    if (to === 'dup_closed') {
      const target = parseInt(body.duplicate_of, 10);
      if (!target) return json({ error: '重复关闭必须指定原单 ID' }, 400);
      if (target === r.id) return json({ error: '不能指向自己' }, 400);
      const t = await env.DB.prepare('SELECT id FROM requirements WHERE id = ?').bind(target).first();
      if (!t) return json({ error: '原单不存在' }, 400);
      dupOf = target;
    }
    if (to !== 'dup_closed' && r.status === 'dup_closed') dupOf = null;
    await env.DB.prepare('UPDATE requirements SET status = ?, duplicate_of = ?, updated_at = ? WHERE id = ?')
      .bind(to, dupOf, nowIso(), id).run();
    await env.DB.prepare(
      `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'status', ?)`)
      .bind(id, u.userId, JSON.stringify({ from: r.status, to, note: (body.note || '').slice(0, 500) })).run();
    return json({ ok: true });
  }
  if (op === 'edit') {
    const next = {
      title: body.title !== undefined ? String(body.title).trim().slice(0, 200) : r.title,
      description: body.description !== undefined ? String(body.description).slice(0, 5000) : r.description,
      type: TYPES.includes(body.type) ? body.type : r.type,
      urgency: URGENCIES.includes(body.urgency) ? body.urgency : r.urgency,
      severity: body.severity !== undefined ? (SEVERITIES.includes(body.severity) ? body.severity : '') : r.severity,
      root_cause: body.root_cause !== undefined ? (ROOT_CAUSES.includes(body.root_cause) ? body.root_cause : '') : r.root_cause,
      ref_code: body.ref_code !== undefined ? String(body.ref_code).trim().slice(0, 60) : r.ref_code,
      related_codes: body.related_codes !== undefined
        ? JSON.stringify((Array.isArray(body.related_codes) ? body.related_codes : [])
            .map(x => String(x).trim().slice(0, 60)).filter(Boolean).slice(0, 20))
        : (r.related_codes || '[]'),
      release_id: body.release_id !== undefined
        ? (body.release_id ? (parseInt(body.release_id, 10) || null) : null)
        : r.release_id
    };
    if (body.project_id !== undefined) {
      const pid = parseInt(body.project_id, 10);
      const p = await env.DB.prepare('SELECT id FROM projects WHERE id = ? AND is_active = 1').bind(pid).first();
      if (!p) return json({ error: '项目不存在' }, 400);
      next.project_id = pid;
    } else {
      next.project_id = r.project_id;
    }
    if (!next.title) return json({ error: '标题不能为空' }, 400);
    await env.DB.prepare(
      `UPDATE requirements SET title = ?, description = ?, type = ?, urgency = ?, project_id = ?, updated_at = ?,
       severity = ?, root_cause = ?, ref_code = ?, related_codes = ?, release_id = ?
       WHERE id = ?`)
      .bind(next.title, next.description, next.type, next.urgency, next.project_id, nowIso(),
            next.severity, next.root_cause, next.ref_code, next.related_codes, next.release_id, id).run();
    await env.DB.prepare(
      `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'edit', '')`)
      .bind(id, u.userId).run();
    return json({ ok: true });
  }
  if (op === 'tags') {
    // 标签归属需求所在项目（r 在本函数开头已查出）
    const tagIds = await resolveTagIds(env, body.tags, r.project_id);
    await env.DB.prepare('DELETE FROM requirement_tags WHERE req_id = ?').bind(id).run();
    for (const tid of tagIds) {
      await env.DB.prepare('INSERT OR IGNORE INTO requirement_tags (req_id, tag_id) VALUES (?, ?)').bind(id, tid).run();
    }
    const names = (await env.DB.prepare(
      `SELECT t.name FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id WHERE rt.req_id = ? ORDER BY t.name`)
      .bind(id).all()).results.map(x => x.name);
    await env.DB.prepare(
      `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'tag', ?)`)
      .bind(id, u.userId, JSON.stringify({ tags: names })).run();
    await env.DB.prepare('UPDATE requirements SET updated_at = ? WHERE id = ?').bind(nowIso(), id).run();
    return json({ ok: true, tags: names });
  }
  return json({ error: '未知操作' }, 400);
}

// ---------- 删除（清理/误录；硬删 + 附件 BLOB 清理） ----------
async function apiReqDelete(request, env, u, id) {
  const r = (await env.DB.prepare('SELECT id FROM requirements WHERE id = ?').bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  const atts = (await env.DB.prepare('SELECT store_key FROM attachments WHERE req_id = ?').bind(id).all()).results;
  const stmts = [
    env.DB.prepare('UPDATE requirements SET duplicate_of = NULL WHERE duplicate_of = ?').bind(id),
    env.DB.prepare('DELETE FROM requirement_tags WHERE req_id = ?').bind(id),
    env.DB.prepare('DELETE FROM attachments WHERE req_id = ?').bind(id),
    env.DB.prepare('DELETE FROM checklist_items WHERE req_id = ?').bind(id),
    env.DB.prepare('DELETE FROM events WHERE req_id = ?').bind(id),
    env.DB.prepare('DELETE FROM requirements WHERE id = ?').bind(id)
  ];
  if (atts.length) {
    const ph = atts.map(() => '?').join(',');
    stmts.push(env.DB.prepare(
      `DELETE FROM attachment_blobs WHERE token IN (${ph})`).bind(...atts.map(a => a.store_key)));
  }
  await env.DB.batch(stmts);
  return json({ ok: true });
}

// ---------- 评论 ----------
const COMMENT_CTYPES = ['normal', 'ac'];   // R7 修订：普通/验收标准；"测试用例"类型移除防与用例库漂移，用例一律进用例库
async function apiComment(request, env, u, id) {
  const r = (await env.DB.prepare('SELECT id FROM requirements WHERE id = ?').bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const text = (body.text || '').trim().slice(0, 2000);
  if (!text) return json({ error: '评论不能为空' }, 400);
  const ctype = COMMENT_CTYPES.includes(body.ctype) ? body.ctype : 'normal';
  await env.DB.prepare(
    `INSERT INTO events (req_id, actor_id, action, detail, ctype) VALUES (?, ?, 'comment', ?, ?)`)
    .bind(id, u.userId, text, ctype).run();
  await env.DB.prepare('UPDATE requirements SET updated_at = ? WHERE id = ?').bind(nowIso(), id).run();
  return json({ ok: true });
}

// ---------- 工作项清单 ----------
async function apiChkAdd(request, env, u, id) {
  const r = (await env.DB.prepare('SELECT id FROM requirements WHERE id = ?').bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const content = (body.content || '').trim().slice(0, 200);
  if (!content) return json({ error: '工作项内容必填' }, 400);
  let assigneeId = null;
  if (body.assignee_id) {
    assigneeId = parseInt(body.assignee_id, 10);
    const a = await env.DB.prepare('SELECT id FROM users WHERE id = ? AND active = 1').bind(assigneeId).first();
    if (!a) return json({ error: '负责人不存在' }, 400);
  }
  const maxRow = await env.DB.prepare(
    'SELECT COALESCE(MAX(sort_order), 0) AS m FROM checklist_items WHERE req_id = ?').bind(id).first();
  const ins = await env.DB.prepare(
    'INSERT INTO checklist_items (req_id, content, assignee_id, status, sort_order) VALUES (?, ?, ?, ?, ?)')
    .bind(id, content, assigneeId, 'todo', (maxRow.m || 0) + 1).run();
  await env.DB.prepare(
    `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'checklist', ?)`)
    .bind(id, u.userId, JSON.stringify({ op: 'add', content })).run();
  await env.DB.prepare('UPDATE requirements SET updated_at = ? WHERE id = ?').bind(nowIso(), id).run();
  return json({ ok: true, id: ins.meta.last_row_id });
}
async function apiChkPatch(request, env, u, cid) {
  const c = (await env.DB.prepare('SELECT * FROM checklist_items WHERE id = ?').bind(cid).first());
  if (!c) return json({ error: '工作项不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const next = {
    content: body.content !== undefined ? String(body.content).trim().slice(0, 200) || c.content : c.content,
    status: ['todo', 'doing', 'done'].includes(body.status) ? body.status : c.status,
    assignee_id: c.assignee_id
  };
  if (body.assignee_id !== undefined) {
    if (body.assignee_id === null || body.assignee_id === '') {
      next.assignee_id = null;
    } else {
      const aid = parseInt(body.assignee_id, 10);
      const a = await env.DB.prepare('SELECT id FROM users WHERE id = ? AND active = 1').bind(aid).first();
      if (!a) return json({ error: '负责人不存在' }, 400);
      next.assignee_id = aid;
    }
  }
  await env.DB.prepare('UPDATE checklist_items SET content = ?, status = ?, assignee_id = ? WHERE id = ?')
    .bind(next.content, next.status, next.assignee_id, cid).run();
  if (next.status !== c.status) {
    await env.DB.prepare(
      `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'checklist', ?)`)
      .bind(c.req_id, u.userId, JSON.stringify({ op: 'status', content: c.content, from: c.status, to: next.status })).run();
    await env.DB.prepare('UPDATE requirements SET updated_at = ? WHERE id = ?').bind(nowIso(), c.req_id).run();
  }
  return json({ ok: true });
}
async function apiChkDelete(request, env, u, cid) {
  const c = (await env.DB.prepare('SELECT * FROM checklist_items WHERE id = ?').bind(cid).first());
  if (!c) return json({ error: '工作项不存在' }, 404);
  await env.DB.prepare('DELETE FROM checklist_items WHERE id = ?').bind(cid).run();
  await env.DB.prepare(
    `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'checklist', ?)`)
    .bind(c.req_id, u.userId, JSON.stringify({ op: 'delete', content: c.content })).run();
  await env.DB.prepare('UPDATE requirements SET updated_at = ? WHERE id = ?').bind(nowIso(), c.req_id).run();
  return json({ ok: true });
}

// ---------- 上传（存 D1 BLOB；R2 预留切换点） ----------
// ---------- R10 图片存储抽象层：换后端（OSS/R2）时只改 BlobStorage，调用方与 URL 不变 ----------
const BlobStorage = {
  async put(env, mime, size, data) {
    const token = crypto.randomUUID();
    await env.DB.prepare('INSERT INTO attachment_blobs (token, mime, size, data) VALUES (?, ?, ?, ?)')
      .bind(token, mime, size, data).run();
    return token;
  },
  async get(env, token) {
    return env.DB.prepare('SELECT mime, data FROM attachment_blobs WHERE token = ?').bind(token).first();
  }
};

async function apiUpload(request, env, u) {
  let form;
  try { form = await request.formData(); } catch (e) { return json({ error: '表单解析失败' }, 400); }
  const file = form.get('file');
  if (!file || typeof file === 'string') return json({ error: '缺少文件' }, 400);
  const ct = file.type || '';
  if (!EXTS[ct]) return json({ error: '仅支持图片（png/jpg/webp/gif）' }, 400);
  if (file.size > MAX_FILE_BYTES) return json({ error: '单张图片不超过 2MB' }, 400);
  const token = await BlobStorage.put(env, ct, file.size, await file.arrayBuffer());
  return json({ ok: true, key: token, name: file.name || '', size: file.size });
}

// ---------- 读取附件（门禁内，按 token） ----------
// 注意：D1 运行时可能把 BLOB 读成普通 Array（非 Uint8Array），必须规范化再进 Response
async function apiFileGet(request, env, token) {
  if (!validAttachToken(token)) return json({ error: '非法路径' }, 400);
  const obj = await BlobStorage.get(env, token);
  if (!obj) return json({ error: '文件不存在' }, 404);
  let d = obj.data;
  if (Array.isArray(d)) d = new Uint8Array(d);
  if (!d || (d.byteLength !== undefined && d.byteLength === 0) || (d.length !== undefined && d.length === 0)) {
    return json({ error: '文件内容为空' }, 404);
  }
  const h = new Headers();
  h.set('Content-Type', obj.mime || 'application/octet-stream');
  h.set('Cache-Control', 'private, max-age=86400');
  return new Response(d, { status: 200, headers: h });
}

// ---------- 文档页（v2 P0：项目内 md 文档 + 版本快照 + 评审） ----------
async function apiDocList(request, env) {
  const url = new URL(request.url);
  const pid = url.searchParams.get('project_id');
  if (!pid) return json({ error: '缺少 project_id' }, 400);
  const items = (await env.DB.prepare(
    `SELECT d.id, d.title, d.status, d.current_version, d.updated_at,
            u.display_name AS author, p.name AS project_name,
            (SELECT COUNT(*) FROM doc_comments c WHERE c.doc_id = d.id) AS comment_count
     FROM docs d JOIN users u ON u.id = d.created_by JOIN projects p ON p.id = d.project_id
     WHERE d.project_id = ?
     ORDER BY d.updated_at DESC`).bind(parseInt(pid, 10)).all()).results;
  return json({ ok: true, items });
}

async function apiDocCreate(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const pid = parseInt(body.project_id, 10);
  const title = String(body.title || '').trim().slice(0, 200);
  const content = String(body.content_md || '');
  if (!pid) return json({ error: '缺少项目' }, 400);
  if (!title) return json({ error: '标题不能为空' }, 400);
  if (content.length > 200000) return json({ error: '文档内容过大（>200KB）' }, 400);
  const proj = await env.DB.prepare('SELECT id FROM projects WHERE id = ?').bind(pid).first();
  if (!proj) return json({ error: '项目不存在' }, 404);
  const now = nowIso();
  const r = await env.DB.prepare(
    `INSERT INTO docs (project_id, title, current_version, status, created_by, created_at, updated_at)
     VALUES (?, ?, 1, 'draft', ?, ?, ?)`).bind(pid, title, u.userId, now, now).run();
  const docId = r.meta.last_row_id;
  await env.DB.prepare(
    `INSERT INTO doc_versions (doc_id, version, content_md, change_summary, author_id, created_at)
     VALUES (?, 1, ?, '首版', ?, ?)`).bind(docId, content, u.userId, now).run();
  return json({ ok: true, id: docId });
}

async function apiDocDetail(request, env, u, id) {
  const d = (await env.DB.prepare(
    `SELECT d.*, u.display_name AS author, p.name AS project_name
     FROM docs d JOIN users u ON u.id = d.created_by JOIN projects p ON p.id = d.project_id
     WHERE d.id = ?`).bind(id).first());
  if (!d) return json({ error: '文档不存在' }, 404);
  const cur = (await env.DB.prepare(
    'SELECT content_md FROM doc_versions WHERE doc_id = ? AND version = ?')
    .bind(id, d.current_version).first());
  const versions = (await env.DB.prepare(
    `SELECT v.version, v.change_summary, v.created_at, u.display_name AS author
     FROM doc_versions v LEFT JOIN users u ON u.id = v.author_id
     WHERE v.doc_id = ? ORDER BY v.version DESC`).bind(id).all()).results;
  const comments = (await env.DB.prepare(
    `SELECT c.id, c.doc_version, c.content, c.created_at, u.display_name AS user
     FROM doc_comments c JOIN users u ON u.id = c.user_id
     WHERE c.doc_id = ? ORDER BY c.created_at ASC`).bind(id).all()).results;
  return json({ ok: true, doc: d, content_md: cur ? cur.content_md : '', versions, comments });
}

async function apiDocPatch(request, env, u, id) {
  const d = (await env.DB.prepare('SELECT * FROM docs WHERE id = ?').bind(id).first());
  if (!d) return json({ error: '文档不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const now = nowIso();

  // 仅状态流转（不携带内容）
  if (body.status && body.content_md === undefined) {
    const st = String(body.status);
    if (!['draft', 'review', 'approved'].includes(st)) return json({ error: '非法状态' }, 400);
    if (st === 'approved') {
      await env.DB.prepare('UPDATE docs SET status = ?, approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?')
        .bind(st, u.userId, now, now, id).run();
    } else {
      await env.DB.prepare('UPDATE docs SET status = ?, updated_at = ? WHERE id = ?').bind(st, now, id).run();
    }
    return json({ ok: true });
  }

  // 内容编辑 → 新版本快照；已批准文档再编辑自动回草稿（批准记录随历史版本保留）
  if (body.content_md !== undefined) {
    const content = String(body.content_md);
    if (content.length > 200000) return json({ error: '文档内容过大（>200KB）' }, 400);
    const title = body.title !== undefined ? String(body.title).trim().slice(0, 200) : d.title;
    if (!title) return json({ error: '标题不能为空' }, 400);
    const newVer = d.current_version + 1;
    const summary = String(body.change_summary || '').trim().slice(0, 300);
    const backToDraft = d.status === 'approved';
    await env.DB.prepare(
      `INSERT INTO doc_versions (doc_id, version, content_md, change_summary, author_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`).bind(id, newVer, content, summary, u.userId, now).run();
    await env.DB.prepare(
      'UPDATE docs SET title = ?, current_version = ?, status = ?, approved_by = NULL, approved_at = NULL, updated_at = ? WHERE id = ?')
      .bind(title, newVer, backToDraft ? 'draft' : d.status, now, id).run();
    return json({ ok: true, version: newVer, status: backToDraft ? 'draft' : d.status });
  }

  // 仅改标题
  if (body.title !== undefined) {
    const title = String(body.title).trim().slice(0, 200);
    if (!title) return json({ error: '标题不能为空' }, 400);
    await env.DB.prepare('UPDATE docs SET title = ?, updated_at = ? WHERE id = ?').bind(title, now, id).run();
    return json({ ok: true });
  }
  return json({ error: '无可更新内容' }, 400);
}

async function apiDocVersion(request, env, id, v) {
  const row = (await env.DB.prepare(
    `SELECT v.content_md, v.created_at, u.display_name AS author
     FROM doc_versions v LEFT JOIN users u ON u.id = v.author_id
     WHERE v.doc_id = ? AND v.version = ?`).bind(id, v).first());
  if (!row) return json({ error: '版本不存在' }, 404);
  return json({ ok: true, version: v, content_md: row.content_md, created_at: row.created_at, author: row.author });
}

async function apiDocComment(request, env, u, id) {
  const d = (await env.DB.prepare('SELECT id, current_version FROM docs WHERE id = ?').bind(id).first());
  if (!d) return json({ error: '文档不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const text = String(body.content || '').trim().slice(0, 2000);
  if (!text) return json({ error: '评论不能为空' }, 400);
  const ver = body.version ? parseInt(body.version, 10) : d.current_version;
  await env.DB.prepare(
    'INSERT INTO doc_comments (doc_id, doc_version, user_id, content) VALUES (?, ?, ?, ?)')
    .bind(id, ver, u.userId, text).run();
  await env.DB.prepare('UPDATE docs SET updated_at = ? WHERE id = ?').bind(nowIso(), id).run();
  return json({ ok: true });
}

async function apiDocDelete(request, env, u, id) {
  await env.DB.prepare('DELETE FROM doc_comments WHERE doc_id = ?').bind(id).run();
  await env.DB.prepare('DELETE FROM doc_versions WHERE doc_id = ?').bind(id).run();
  const r = await env.DB.prepare('DELETE FROM docs WHERE id = ?').bind(id).run();
  if (!r.meta.changes) return json({ error: '文档不存在' }, 404);
  return json({ ok: true });
}

// ---------- R2 筛选导出（CSV，门禁内；CSV-14 五维度统计取数口） ----------
async function apiExport(request, env, u) {
  const url = new URL(request.url);
  const where = []; const args = [];
  const project = parseInt(url.searchParams.get('project'), 10);
  if (project) { where.push('r.project_id = ?'); args.push(project); }
  const status = (url.searchParams.get('status') || '').trim();
  if (status === 'open') { where.push(`r.status NOT IN ('closed','dup_closed')`); }
  else if (status) {
    const ss = status.split(',').filter(x => STATUSES.includes(x));
    if (ss.length) { where.push(`r.status IN (${ss.map(() => '?').join(',')})`); args.push(...ss); }
  }
  const type = url.searchParams.get('type');
  if (TYPES.includes(type)) { where.push('r.type = ?'); args.push(type); }
  const severity = url.searchParams.get('severity');
  if (severity === 'none') { where.push("r.severity = ''"); }
  else if (SEVERITIES.includes(severity)) { where.push('r.severity = ?'); args.push(severity); }
  const tag = (url.searchParams.get('tag') || '').trim();
  if (tag) {
    where.push(`EXISTS (SELECT 1 FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
      WHERE rt.req_id = r.id AND t.name = ?)`);
    args.push(tag);
  }
  const W = where.length ? 'WHERE ' + where.join(' AND ') : '';
  const rows = (await env.DB.prepare(
    `SELECT r.id, r.title, r.type, r.urgency, r.status, r.severity, r.root_cause, r.ref_code,
            r.created_at, us.display_name AS creator, p.name AS project_name
     FROM requirements r
     JOIN projects p ON p.id = r.project_id
     LEFT JOIN users us ON us.id = r.created_by
     ${W} ORDER BY r.id ASC LIMIT 5000`).bind(...args).all()).results;
  const ids = rows.map(x => x.id);
  const acMap = new Map();
  if (ids.length) {
    const ph = ids.map(() => '?').join(',');
    const evs = (await env.DB.prepare(
      `SELECT req_id, detail FROM events
       WHERE req_id IN (${ph}) AND action = 'comment'
         AND (ctype = 'ac' OR detail LIKE '【验收标准】%') ORDER BY id`)
      .bind(...ids).all()).results;
    for (const e of evs) {
      if (!acMap.has(e.req_id)) acMap.set(e.req_id, []);
      acMap.get(e.req_id).push(e.detail.replace(/^【验收标准】\s*/, ''));
    }
  }
  const SEV = { critical: '关键', major: '重大', general: '一般', watch: '观察' };
  const RC = { config: '配置', defect: '缺陷', usage: '使用', external: '外部依赖', data: '数据', requirement: '需求有误' };
  const TY = { bug: 'bug', req: '需求', opt: '优化' };
  const ST = { submitted: '待复现', confirmed: '已确认', scheduled: '已排期', fixed: '已修复', verified: '已验证', closed: '关闭', dup_closed: '重复关闭' };
  const cell = v => '"' + String(v == null ? '' : v).replace(/"/g, '""').replace(/\r?\n/g, '\\n') + '"';
  const lines = [['编号','标题','类型','状态','紧急度','严重级别','根因分类','提单人','创建日期','关联编号','验收标准汇总'].map(cell).join(',')];
  for (const x of rows) {
    lines.push([x.id, x.title, TY[x.type] || x.type, ST[x.status] || x.status,
      x.urgency === 'urgent' ? '紧急' : '一般', SEV[x.severity] || '', RC[x.root_cause] || '',
      x.creator || '', (x.created_at || '').slice(0, 10), x.ref_code || '',
      (acMap.get(x.id) || []).join(' ||| ')].map(cell).join(','));
  }
  const cnt = key => {
    const m = new Map();
    for (const x of rows) { const k = key(x); m.set(k, (m.get(k) || 0) + 1); }
    return [...m.entries()].map(([k, v]) => `${k}:${v}`).join(' | ') || '无';
  };
  const stats = [
    ['== 统计汇总 ==', ''],
    ['导出条数', String(rows.length)],
    ['按状态', cnt(x => ST[x.status] || x.status)],
    ['按严重级别', cnt(x => SEV[x.severity] || '未定级')],
    ['按根因分类', cnt(x => RC[x.root_cause] || '未填')],
    ['按项目', cnt(x => x.project_name)],
    ['按类型', cnt(x => TY[x.type] || x.type)]
  ];
  for (const [k, v] of stats) lines.push([cell(k), cell(v)].join(','));
  const csv = '\uFEFF' + lines.join('\r\n');
  const h = new Headers();
  h.set('Content-Type', 'text/csv; charset=utf-8');
  h.set('Content-Disposition', `attachment; filename="export-${nowIso().slice(0, 10)}.csv"`);
  h.set('Cache-Control', 'no-store');
  return new Response(csv, { status: 200, headers: h });
}

// ---------- R4 releases 版本发布单（CR-V 承载；发布确认人≠实施人） ----------
const RELEASE_STATUSES = ['planning', 'testing', 'reverify', 'published', 'closed'];

async function apiRelList(request, env) {
  const url = new URL(request.url);
  const pid = parseInt(url.searchParams.get('project'), 10);
  if (!pid) return json({ error: '缺少 project' }, 400);
  const items = (await env.DB.prepare(
    `SELECT rl.*, u.display_name AS creator,
            (SELECT COUNT(*) FROM requirements r WHERE r.release_id = rl.id) AS bug_count
     FROM releases rl LEFT JOIN users u ON u.id = rl.created_by
     WHERE rl.project_id = ? ORDER BY rl.id DESC`).bind(pid).all()).results;
  return json({ ok: true, items });
}

async function apiRelCreate(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const pid = parseInt(body.project_id, 10);
  const version = String(body.version || '').trim().slice(0, 60);
  if (!pid) return json({ error: '缺少项目' }, 400);
  if (!version) return json({ error: '版本号必填' }, 400);
  const proj = await env.DB.prepare('SELECT id FROM projects WHERE id = ?').bind(pid).first();
  if (!proj) return json({ error: '项目不存在' }, 404);
  const now = nowIso();
  const r = await env.DB.prepare(
    `INSERT INTO releases (project_id, version, change_scope, retest_scope, status, created_by, created_at, updated_at)
     VALUES (?, ?, ?, ?, 'planning', ?, ?, ?)`)
    .bind(pid, version, String(body.change_scope || '').slice(0, 2000),
          String(body.retest_scope || '').slice(0, 2000), u.userId, now, now).run();
  return json({ ok: true, id: r.meta.last_row_id });
}

async function apiRelPatch(request, env, u, id) {
  const rl = (await env.DB.prepare('SELECT * FROM releases WHERE id = ?').bind(id).first());
  if (!rl) return json({ error: '版本不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const now = nowIso();
  const op = body.op || 'edit';
  if (op === 'status') {
    const to = body.status;
    if (!RELEASE_STATUSES.includes(to)) return json({ error: '非法状态' }, 400);
    if (to === 'published') {
      // 发布确认：确认人≠实施人（创建人），确认动作即发布
      if (u.userId === rl.created_by) return json({ error: '发布确认人不能是实施人（创建人）本人' }, 400);
      await env.DB.prepare(
        `UPDATE releases SET status = 'published', published_by = ?, published_at = ?, confirmor_id = ?, confirmor_at = ?, updated_at = ? WHERE id = ?`)
        .bind(u.userId, now, u.userId, now, now, id).run();
    } else {
      await env.DB.prepare('UPDATE releases SET status = ?, updated_at = ? WHERE id = ?').bind(to, now, id).run();
    }
    return json({ ok: true });
  }
  // edit：版本信息与关联 bug（release_id 挂需求单上）
  const next = {
    version: body.version !== undefined ? String(body.version).trim().slice(0, 60) : rl.version,
    change_scope: body.change_scope !== undefined ? String(body.change_scope).slice(0, 2000) : rl.change_scope,
    retest_scope: body.retest_scope !== undefined ? String(body.retest_scope).slice(0, 2000) : rl.retest_scope
  };
  if (!next.version) return json({ error: '版本号必填' }, 400);
  await env.DB.prepare('UPDATE releases SET version = ?, change_scope = ?, retest_scope = ?, updated_at = ? WHERE id = ?')
    .bind(next.version, next.change_scope, next.retest_scope, now, id).run();
  return json({ ok: true });
}

async function apiRelDelete(request, env, u, id) {
  await env.DB.prepare('UPDATE requirements SET release_id = NULL WHERE release_id = ?').bind(id).run();
  const r = await env.DB.prepare('DELETE FROM releases WHERE id = ?').bind(id).run();
  if (!r.meta.changes) return json({ error: '版本不存在' }, 404);
  return json({ ok: true });
}

// ---------- R5+R6 用例库 test_cases + 执行记录 tc_executions ----------
const TC_RISKS = ['high', 'middle', 'low', 'external'];
const TC_TYPES = ['positive', 'negative', 'boundary'];
const TC_RESULTS = ['pass', 'fail', 'deviation'];

async function nextTcCode(env, projectId) {
  for (let i = 0; i < 5; i++) {
    const row = (await env.DB.prepare(
      `SELECT MAX(CAST(SUBSTR(tc_code, 4) AS INTEGER)) AS n FROM test_cases WHERE project_id = ?`)
      .bind(projectId).first());
    const n = (row && row.n ? row.n : 0) + 1;
    const code = 'TC-' + String(n).padStart(3, '0');
    const dup = (await env.DB.prepare('SELECT id FROM test_cases WHERE tc_code = ?').bind(code).first());
    if (!dup) return code;
  }
  return 'TC-' + Date.now();
}

async function apiTcList(request, env) {
  const url = new URL(request.url);
  const pid = parseInt(url.searchParams.get('project'), 10);
  if (!pid) return json({ error: '缺少 project' }, 400);
  const where = ['t.project_id = ?']; const args = [pid];
  const req = parseInt(url.searchParams.get('req'), 10);
  if (req) { where.push('t.related_req = ?'); args.push(req); }
  const status = url.searchParams.get('status');
  if (status === 'draft' || status === 'approved') { where.push('t.status = ?'); args.push(status); }
  const items = (await env.DB.prepare(
    `SELECT t.*, u.display_name AS creator,
            r.title AS related_req_title
     FROM test_cases t
     LEFT JOIN users u ON u.id = t.created_by
     LEFT JOIN requirements r ON r.id = t.related_req
     ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY t.tc_code ASC LIMIT 2000`).bind(...args).all()).results;
  return json({ ok: true, items });
}

async function apiTcCreate(request, env, u) {
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const pid = parseInt(body.project_id, 10);
  const title = String(body.title || '').trim().slice(0, 200);
  if (!pid) return json({ error: '缺少项目' }, 400);
  if (!title) return json({ error: '标题必填' }, 400);
  const proj = await env.DB.prepare('SELECT id FROM projects WHERE id = ?').bind(pid).first();
  if (!proj) return json({ error: '项目不存在' }, 404);
  const tcCode = await nextTcCode(env, pid);
  const now = nowIso();
  const steps = String(body.steps_md || '').slice(0, 20000);
  const related = body.related_req ? parseInt(body.related_req, 10) || null : null;
  const r = await env.DB.prepare(
    `INSERT INTO test_cases (project_id, tc_code, title, steps_md, related_req, covers_urs, risk, ctype, status, current_version, created_by, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, ?, ?, ?)`)
    .bind(pid, tcCode, title, steps, related,
          String(body.covers_urs || '').slice(0, 300),
          TC_RISKS.includes(body.risk) ? body.risk : 'middle',
          TC_TYPES.includes(body.ctype) ? body.ctype : 'positive', u.userId, now, now).run();
  const tcId = r.meta.last_row_id;
  await env.DB.prepare(
    `INSERT INTO test_case_versions (tc_id, version, steps_md, change_summary, author_id, created_at)
     VALUES (?, 1, ?, '首版', ?, ?)`).bind(tcId, steps, u.userId, now).run();
  return json({ ok: true, id: tcId, tc_code: tcCode });
}

async function apiTcDetail(request, env, id) {
  const t = (await env.DB.prepare(
    `SELECT t.*, u.display_name AS creator, ua.display_name AS approver, r.title AS related_req_title
     FROM test_cases t
     LEFT JOIN users u ON u.id = t.created_by
     LEFT JOIN users ua ON ua.id = t.approved_by
     LEFT JOIN requirements r ON r.id = t.related_req
     WHERE t.id = ?`).bind(id).first());
  if (!t) return json({ error: '用例不存在' }, 404);
  const cur = (await env.DB.prepare('SELECT steps_md FROM test_case_versions WHERE tc_id = ? AND version = ?')
    .bind(id, t.current_version).first());
  const versions = (await env.DB.prepare(
    `SELECT v.version, v.change_summary, v.created_at, u.display_name AS author
     FROM test_case_versions v LEFT JOIN users u ON u.id = v.author_id
     WHERE v.tc_id = ? ORDER BY v.version DESC`).bind(id).all()).results;
  const execs = (await env.DB.prepare(
    `SELECT e.*, rl.version AS release_version, u.display_name AS executor
     FROM tc_executions e
     JOIN releases rl ON rl.id = e.release_id
     LEFT JOIN users u ON u.id = e.executed_by
     WHERE e.tc_id = ? ORDER BY e.executed_at DESC`).bind(id).all()).results;
  return json({ ok: true, tc: t, steps_md: cur ? cur.steps_md : '', versions, executions: execs });
}

async function apiTcPatch(request, env, u, id) {
  const t = (await env.DB.prepare('SELECT * FROM test_cases WHERE id = ?').bind(id).first());
  if (!t) return json({ error: '用例不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const now = nowIso();
  if (body.op === 'status') {
    const st = body.status;
    if (st !== 'approved' && st !== 'draft') return json({ error: '非法状态' }, 400);
    if (st === 'approved') {
      await env.DB.prepare('UPDATE test_cases SET status = ?, approved_by = ?, approved_at = ?, updated_at = ? WHERE id = ?')
        .bind(st, u.userId, now, now, id).run();
    } else {
      await env.DB.prepare('UPDATE test_cases SET status = ?, approved_by = NULL, approved_at = NULL, updated_at = ? WHERE id = ?')
        .bind(st, now, id).run();
    }
    return json({ ok: true });
  }
  // edit：steps_md 变化 → 新版本快照；approved 用例编辑自动回 draft
  const next = {
    title: body.title !== undefined ? String(body.title).trim().slice(0, 200) : t.title,
    steps_md: body.steps_md !== undefined ? String(body.steps_md).slice(0, 20000) : t.steps_md,
    risk: TC_RISKS.includes(body.risk) ? body.risk : t.risk,
    ctype: TC_TYPES.includes(body.ctype) ? body.ctype : t.ctype,
    covers_urs: body.covers_urs !== undefined ? String(body.covers_urs).slice(0, 300) : t.covers_urs,
    related_req: body.related_req !== undefined ? (body.related_req ? parseInt(body.related_req, 10) || null : null) : t.related_req
  };
  if (!next.title) return json({ error: '标题必填' }, 400);
  const backToDraft = t.status === 'approved';
  let newVer = t.current_version;
  if (body.steps_md !== undefined && next.steps_md !== t.steps_md) {
    newVer = t.current_version + 1;
    await env.DB.prepare(
      `INSERT INTO test_case_versions (tc_id, version, steps_md, change_summary, author_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`)
      .bind(id, newVer, next.steps_md, String(body.change_summary || '').slice(0, 300), u.userId, now).run();
  }
  await env.DB.prepare(
    `UPDATE test_cases SET title = ?, steps_md = ?, risk = ?, ctype = ?, covers_urs = ?, related_req = ?,
     status = ?, approved_by = NULL, approved_at = NULL, current_version = ?, updated_at = ? WHERE id = ?`)
    .bind(next.title, next.steps_md, next.risk, next.ctype, next.covers_urs, next.related_req,
          backToDraft ? 'draft' : t.status, newVer, now, id).run();
  return json({ ok: true, version: newVer, status: backToDraft ? 'draft' : t.status });
}

async function apiTcDelete(request, env, u, id) {
  const stmts = [
    env.DB.prepare('DELETE FROM tc_executions WHERE tc_id = ?').bind(id),
    env.DB.prepare('DELETE FROM test_case_versions WHERE tc_id = ?').bind(id),
    env.DB.prepare('DELETE FROM test_cases WHERE id = ?').bind(id)
  ];
  await env.DB.batch(stmts);
  return json({ ok: true });
}

async function apiTcExecPut(request, env, u, id) {
  const t = (await env.DB.prepare('SELECT id FROM test_cases WHERE id = ?').bind(id).first());
  if (!t) return json({ error: '用例不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const rid = parseInt(body.release_id, 10);
  if (!rid) return json({ error: '缺少 release_id' }, 400);
  const rl = (await env.DB.prepare('SELECT id FROM releases WHERE id = ?').bind(rid).first());
  if (!rl) return json({ error: '版本不存在' }, 404);
  const result = TC_RESULTS.includes(body.result) ? body.result : '';
  const conclusion = String(body.conclusion || '').slice(0, 2000);
  const devRef = String(body.dev_ref || '').trim().slice(0, 60);
  const evRef = String(body.ev_ref || '').trim().slice(0, 60);
  await env.DB.prepare(
    `INSERT INTO tc_executions (tc_id, release_id, result, conclusion, dev_ref, ev_ref, executed_by, executed_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT (tc_id, release_id) DO UPDATE SET result = excluded.result, conclusion = excluded.conclusion,
       dev_ref = excluded.dev_ref, ev_ref = excluded.ev_ref, executed_by = excluded.executed_by,
       executed_at = excluded.executed_at`)
    .bind(id, rid, result, conclusion, devRef, evRef, u.userId, nowIso()).run();
  return json({ ok: true });
}

async function apiTcExecList(request, env, id) {
  const rl = (await env.DB.prepare('SELECT id, version FROM releases WHERE id = ?').bind(id).first());
  if (!rl) return json({ error: '版本不存在' }, 404);
  const items = (await env.DB.prepare(
    `SELECT e.*, t.tc_code, t.title AS tc_title, t.status AS tc_status, u.display_name AS executor
     FROM tc_executions e
     JOIN test_cases t ON t.id = e.tc_id
     LEFT JOIN users u ON u.id = e.executed_by
     WHERE e.release_id = ? ORDER BY t.tc_code ASC`).bind(id).all()).results;
  const stat = { pass: 0, fail: 0, deviation: 0, empty: 0 };
  for (const e of items) stat[e.result || 'empty'] = (stat[e.result || 'empty'] || 0) + 1;
  return json({ ok: true, release: { id: rl.id, version: rl.version }, items, stat });
}

// ---------- 去重提示（LIKE 子串） ----------
async function apiDedup(request, env) {
  const url = new URL(request.url);
  const tokens = qTokens(url.searchParams.get('q') || '');
  if (!tokens.length) return json({ ok: true, items: [] });
  const args = [];
  for (const t of tokens) { const like = likeEsc(t); args.push(like, like); }
  const items = (await env.DB.prepare(
    `SELECT r.id, r.title, r.status, r.type, r.urgency, p.name AS project_name
     FROM requirements r JOIN projects p ON p.id = r.project_id
     WHERE (${tokens.map(() => `(r.title LIKE ? ESCAPE '\\' OR r.description LIKE ? ESCAPE '\\')`).join(' OR ')})
       AND r.status NOT IN ('closed','dup_closed')
     ORDER BY r.updated_at DESC LIMIT 5`).bind(...args).all()).results;
  return json({ ok: true, items });
}

// ---------- main fetch ----------
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname;
    const method = request.method;

    if (p === '/api/health') return json({ ok: true, t: nowIso() });
    if (p === '/api/login' && method === 'POST') return apiLogin(request, env);

    if (p.startsWith('/api/')) {
      const u = await currentUser(request, env);
      if (!u) return json({ error: '未登录' }, 401);
      if (p === '/api/logout' && method === 'POST') return apiLogout(request, env);
      if (p === '/api/me') return apiMe(request, env);
      if (p === '/api/me/password' && method === 'POST') return changeMyPassword(request, env, u);
      if (p === '/api/bootstrap') return apiBootstrap(request, env);
      if (p === '/api/projects' && method === 'GET') return apiProjectList(request, env);
      if (p === '/api/projects' && method === 'POST') return apiProjectCreate(request, env);
      const pm = p.match(/^\/api\/projects\/(\d+)$/);
      if (pm && method === 'DELETE') return apiProjectDelete(request, env, parseInt(pm[1], 10));
      if (p === '/api/tags' && method === 'GET') return apiTagList(request, env);
      if (p === '/api/my-work') return apiMyWork(request, env, u);
      if (p === '/api/dedup-suggest') return apiDedup(request, env);
      if (p === '/api/export' && method === 'GET') return apiExport(request, env, u);
      if (p === '/api/releases' && method === 'GET') return apiRelList(request, env);
      if (p === '/api/releases' && method === 'POST') return apiRelCreate(request, env, u);
      const rlm = p.match(/^\/api\/releases\/(\d+)$/);
      if (rlm) {
        const id = parseInt(rlm[1], 10);
        if (method === 'PATCH') return apiRelPatch(request, env, u, id);
        if (method === 'DELETE') return apiRelDelete(request, env, u, id);
      }
      const rlmx = p.match(/^\/api\/releases\/(\d+)\/executions$/);
      if (rlmx && method === 'GET') return apiTcExecList(request, env, parseInt(rlmx[1], 10));
      if (p === '/api/testcases' && method === 'GET') return apiTcList(request, env);
      if (p === '/api/testcases' && method === 'POST') return apiTcCreate(request, env, u);
      const tcm = p.match(/^\/api\/testcases\/(\d+)$/);
      if (tcm) {
        const id = parseInt(tcm[1], 10);
        if (method === 'GET') return apiTcDetail(request, env, id);
        if (method === 'PATCH') return apiTcPatch(request, env, u, id);
        if (method === 'DELETE') return apiTcDelete(request, env, u, id);
      }
      const tcem = p.match(/^\/api\/testcases\/(\d+)\/execution$/);
      if (tcem && method === 'PUT') return apiTcExecPut(request, env, u, parseInt(tcem[1], 10));
      if (p === '/api/docs' && method === 'GET') return apiDocList(request, env);
      if (p === '/api/docs' && method === 'POST') return apiDocCreate(request, env, u);
      const dm = p.match(/^\/api\/docs\/(\d+)$/);
      if (dm) {
        const id = parseInt(dm[1], 10);
        if (method === 'GET') return apiDocDetail(request, env, u, id);
        if (method === 'PATCH') return apiDocPatch(request, env, u, id);
        if (method === 'DELETE') return apiDocDelete(request, env, u, id);
      }
      const dvm = p.match(/^\/api\/docs\/(\d+)\/versions\/(\d+)$/);
      if (dvm && method === 'GET') return apiDocVersion(request, env, parseInt(dvm[1], 10), parseInt(dvm[2], 10));
      const dcm = p.match(/^\/api\/docs\/(\d+)\/comment$/);
      if (dcm && method === 'POST') return apiDocComment(request, env, u, parseInt(dcm[1], 10));
      if (p === '/api/upload' && method === 'POST') return apiUpload(request, env, u);
      if (p.startsWith('/api/files/') && method === 'GET') return apiFileGet(request, env, p.slice('/api/files/'.length));
      if (p === '/api/requirements' && method === 'GET') return apiReqList(request, env, u);
      if (p === '/api/requirements' && method === 'POST') return apiReqCreate(request, env, u);
      const rm = p.match(/^\/api\/requirements\/(\d+)$/);
      if (rm) {
        const id = parseInt(rm[1], 10);
        if (method === 'GET') return apiReqDetail(request, env, u, id);
        if (method === 'PATCH') return apiReqPatch(request, env, u, id);
        if (method === 'DELETE') return apiReqDelete(request, env, u, id);
      }
      const cm = p.match(/^\/api\/requirements\/(\d+)\/comment$/);
      if (cm && method === 'POST') return apiComment(request, env, u, parseInt(cm[1], 10));
      const km = p.match(/^\/api\/requirements\/(\d+)\/checklist$/);
      if (km && method === 'POST') return apiChkAdd(request, env, u, parseInt(km[1], 10));
      const ki = p.match(/^\/api\/checklist\/(\d+)$/);
      if (ki) {
        const cid = parseInt(ki[1], 10);
        if (method === 'PATCH') return apiChkPatch(request, env, u, cid);
        if (method === 'DELETE') return apiChkDelete(request, env, u, cid);
      }
      return json({ error: '未找到' }, 404);
    }

    // 白名单静态：登录页 + 样式表 + 图标（style.css 必须匿名可达，否则登录页裸奔）
    if (p === '/login' || p === '/login.html') return serveStatic(url.origin + '/login.html', env);
    if (p === '/favicon.svg' || p === '/favicon.ico' || p === '/robots.txt' || p === '/style.css') {
      return serveStatic(url.origin + p, env);
    }

    // 其余页面：必须登录
    const u = await currentUser(request, env);
    if (!u) {
      return new Response(null, { status: 302, headers: { Location: '/login', 'Cache-Control': 'no-store' } });
    }
    const target = p === '/' ? '/index.html' : p;
    return serveStatic(url.origin + target, env);
  }
};
