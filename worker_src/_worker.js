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

// ---------- 字典 ----------
async function apiBootstrap(request, env) {
  const projects = (await env.DB.prepare(
    'SELECT id, name FROM projects WHERE is_active = 1 ORDER BY id').all()).results;
  const tags = (await env.DB.prepare(
    'SELECT id, name FROM tags ORDER BY name LIMIT 500').all()).results;
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

// ---------- 标签解析：名字数组 → 确保存在 → 返回 id 数组 ----------
async function resolveTagIds(env, names) {
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
  const tagIds = await resolveTagIds(env, body.tags);
  const ins = await env.DB.prepare(
    `INSERT INTO requirements (project_id, title, description, type, urgency, status, channel, created_by, updated_at)
     VALUES (?, ?, ?, ?, ?, 'submitted', 'web', ?, ?)`)
    .bind(projectId, title, description, type, urgency, u.userId, nowIso()).run();
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
function ftsQuery(q) {
  const tokens = String(q || '').trim().split(/\s+/).filter(Boolean)
    .map(t => '"' + t.replace(/"/g, '') + '"');
  return tokens.join(' OR ');
}
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
  const tag = (url.searchParams.get('tag') || '').trim();
  if (tag) {
    where.push(`EXISTS (SELECT 1 FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
      WHERE rt.req_id = r.id AND t.name = ?)`);
    args.push(tag);
  }
  const q = (url.searchParams.get('q') || '').trim();
  if (q) {
    const fq = ftsQuery(q);
    if (fq) { where.push('r.id IN (SELECT rowid FROM requirements_fts WHERE requirements_fts MATCH ?)'); args.push(fq); }
    else { where.push('0 = 1'); }
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
async function apiMyWork(request, env, u) {
  const items = (await env.DB.prepare(
    `SELECT c.id, c.content, c.status, c.req_id, r.title, r.status AS req_status,
            us.display_name AS creator_name, r.updated_at
     FROM checklist_items c
     JOIN requirements r ON r.id = c.req_id
     LEFT JOIN users us ON us.id = r.created_by
     WHERE c.assignee_id = ? AND c.status != 'done'
       AND r.status NOT IN ('closed','dup_closed')
     ORDER BY r.updated_at DESC, c.id ASC LIMIT 100`).bind(u.userId).all()).results;
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
  const tags = (await env.DB.prepare(
    `SELECT t.id, t.name FROM requirement_tags rt JOIN tags t ON t.id = rt.tag_id
     WHERE rt.req_id = ? ORDER BY t.name`).bind(id).all()).results;
  const attachments = (await env.DB.prepare(
    `SELECT id, store_key, orig_name, size, created_at FROM attachments
     WHERE req_id = ? ORDER BY id`).bind(id).all()).results;
  const checklist = (await env.DB.prepare(
    `SELECT c.id, c.content, c.status, c.sort_order, c.assignee_id, us.display_name AS assignee_name
     FROM checklist_items c LEFT JOIN users us ON us.id = c.assignee_id
     WHERE c.req_id = ? ORDER BY c.sort_order, c.id`).bind(id).all()).results;
  const events = (await env.DB.prepare(
    `SELECT e.id, e.action, e.detail, e.created_at, us.display_name AS actor_name
     FROM events e LEFT JOIN users us ON us.id = e.actor_id
     WHERE e.req_id = ? ORDER BY e.created_at ASC, e.id ASC`).bind(id).all()).results;
  let dupOf = null;
  if (r.duplicate_of) {
    dupOf = (await env.DB.prepare('SELECT id, title, status FROM requirements WHERE id = ?')
      .bind(r.duplicate_of).first());
  }
  return json({ ok: true, req: r, tags, attachments, checklist, events, dup_of: dupOf });
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
      urgency: URGENCIES.includes(body.urgency) ? body.urgency : r.urgency
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
      `UPDATE requirements SET title = ?, description = ?, type = ?, urgency = ?, project_id = ?, updated_at = ?
       WHERE id = ?`)
      .bind(next.title, next.description, next.type, next.urgency, next.project_id, nowIso(), id).run();
    await env.DB.prepare(
      `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'edit', '')`)
      .bind(id, u.userId).run();
    return json({ ok: true });
  }
  if (op === 'tags') {
    const tagIds = await resolveTagIds(env, body.tags);
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
async function apiComment(request, env, u, id) {
  const r = (await env.DB.prepare('SELECT id FROM requirements WHERE id = ?').bind(id).first());
  if (!r) return json({ error: '需求不存在' }, 404);
  let body = {};
  try { body = await request.json(); } catch (e) {}
  const text = (body.text || '').trim().slice(0, 2000);
  if (!text) return json({ error: '评论不能为空' }, 400);
  await env.DB.prepare(
    `INSERT INTO events (req_id, actor_id, action, detail) VALUES (?, ?, 'comment', ?)`)
    .bind(id, u.userId, text).run();
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
async function apiUpload(request, env, u) {
  let form;
  try { form = await request.formData(); } catch (e) { return json({ error: '表单解析失败' }, 400); }
  const file = form.get('file');
  if (!file || typeof file === 'string') return json({ error: '缺少文件' }, 400);
  const ct = file.type || '';
  if (!EXTS[ct]) return json({ error: '仅支持图片（png/jpg/webp/gif）' }, 400);
  if (file.size > MAX_FILE_BYTES) return json({ error: '单张图片不超过 2MB' }, 400);
  const token = crypto.randomUUID();
  await env.DB.prepare(
    'INSERT INTO attachment_blobs (token, mime, size, data) VALUES (?, ?, ?, ?)')
    .bind(token, ct, file.size, await file.arrayBuffer()).run();
  return json({ ok: true, key: token, name: file.name || '', size: file.size });
}

// ---------- 读取附件（门禁内，按 token） ----------
// 注意：D1 运行时可能把 BLOB 读成普通 Array（非 Uint8Array），必须规范化再进 Response
async function apiFileGet(request, env, token) {
  if (!validAttachToken(token)) return json({ error: '非法路径' }, 400);
  const obj = await env.DB.prepare('SELECT mime, data FROM attachment_blobs WHERE token = ?')
    .bind(token).first();
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

// ---------- 去重提示（FTS5） ----------
async function apiDedup(request, env) {
  const url = new URL(request.url);
  const fq = ftsQuery(url.searchParams.get('q') || '');
  if (!fq) return json({ ok: true, items: [] });
  const items = (await env.DB.prepare(
    `SELECT r.id, r.title, r.status, r.type, r.urgency, p.name AS project_name
     FROM requirements_fts f JOIN requirements r ON r.id = f.rowid
     JOIN projects p ON p.id = r.project_id
     WHERE requirements_fts MATCH ? AND r.status NOT IN ('closed','dup_closed')
     ORDER BY rank LIMIT 5`).bind(fq).all()).results;
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
      if (p === '/api/tags' && method === 'GET') return apiTagList(request, env);
      if (p === '/api/my-work') return apiMyWork(request, env, u);
      if (p === '/api/dedup-suggest') return apiDedup(request, env);
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

    // 白名单静态：登录页 + 图标
    if (p === '/login' || p === '/login.html') return serveStatic(url.origin + '/login.html', env);
    if (p === '/favicon.svg' || p === '/favicon.ico' || p === '/robots.txt') return serveStatic(url.origin + p, env);

    // 其余页面：必须登录
    const u = await currentUser(request, env);
    if (!u) {
      return new Response(null, { status: 302, headers: { Location: '/login', 'Cache-Control': 'no-store' } });
    }
    const target = p === '/' ? '/index.html' : p;
    return serveStatic(url.origin + target, env);
  }
};
