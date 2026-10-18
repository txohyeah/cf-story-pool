// app-common.js — 需求池全站共享 UI 组件
// 组件：提单弹框（原生表单，含压缩/粘贴上传/幂等键）/统一确认框/改密码弹框/全局项目上下文
// 用法：PoolUI.openNewReqModal(projectId, onCreated) / PoolUI.showConfirm(msg, onOk) / PoolUI.openPwdModal()
//       PoolUI.getProject() / PoolUI.setProject(id)
(function () {
  'use strict';
  const UI = {};
  const SEV = { critical: '关键', major: '重大', general: '一般', watch: '观察' };
  const RC = { config: '配置', defect: '缺陷', usage: '使用', external: '外部依赖', data: '数据', requirement: '需求有误' };

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function api(path, opts) {
    return fetch(path, opts).then(r => {
      if (r.status === 401) { location.href = '/login'; return {}; }
      return r.json();
    });
  }
  function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // ---------- 全局项目上下文（#200） ----------
  const PKEY = 'pool_project';
  UI.getProject = function () {
    return localStorage.getItem(PKEY) || '';
  };
  UI.setProject = function (id) {
    if (id) localStorage.setItem(PKEY, String(id));
    else localStorage.removeItem(PKEY);
  };

  // ---------- 图片压缩（与 new.html 同管线：>300KB 转 JPEG 0.8） ----------
  async function compressImage(file) {
    if (file.type === 'image/gif') return file;
    if (file.size <= 300 * 1024) return file;
    const img = await createImageBitmap(file);
    const maxSide = 1600;
    const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.8));
    return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' });
  }

  // ---------- 统一二次确认框 ----------
  UI.showConfirm = function (msg, onOk) {
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.style.zIndex = 95;
    ov.innerHTML = '<div class="modal"><h3>确认操作</h3>'
      + '<div style="margin:10px 0;white-space:pre-wrap;font-size:14px">' + esc(msg) + '</div>'
      + '<div class="modal-btns" style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">'
      + '<button class="btn" id="sc-no">取消</button>'
      + '<button class="btn primary" id="sc-ok">确认</button></div></div>';
    document.body.appendChild(ov);
    const close = () => ov.remove();
    ov.querySelector('#sc-no').onclick = close;
    ov.addEventListener('click', e => { if (e.target === ov) close(); });
    ov.querySelector('#sc-ok').onclick = () => { close(); onOk(); };
  };

  // ---------- 改密码弹框 ----------
  UI.openPwdModal = function () {
    closeOverlay('pwd-overlay');
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.id = 'pwd-overlay'; ov.style.zIndex = 90;
    ov.innerHTML = '<div class="modal"><h3>修改密码</h3>'
      + '<label>当前密码<input type="password" id="pw-cur" autocomplete="current-password"></label>'
      + '<label>新密码（至少 6 位）<input type="password" id="pw-new" autocomplete="new-password"></label>'
      + '<label>确认新密码<input type="password" id="pw-new2" autocomplete="new-password"></label>'
      + '<label class="pw-show"><input type="checkbox" id="pw-show"> 显示密码</label>'
      + '<div class="err" id="pw-err" style="margin:2px 0 0"></div>'
      + '<div class="modal-btns"><button class="btn" id="pw-cancel">取消</button>'
      + '<button class="btn primary" id="pw-save">保存</button></div></div>';
    document.body.appendChild(ov);
    ov.querySelector('#pw-show').addEventListener('change', function () {
      const t = this.checked ? 'text' : 'password';
      ov.querySelector('#pw-cur').type = t;
      ov.querySelector('#pw-new').type = t;
      ov.querySelector('#pw-new2').type = t;
    });
    const close = () => ov.remove();
    ov.querySelector('#pw-cancel').onclick = close;
    ov.addEventListener('click', e => { if (e.target === ov) close(); });
    ov.querySelector('#pw-save').onclick = async () => {
      const err = ov.querySelector('#pw-err');
      err.textContent = '';
      const cur = ov.querySelector('#pw-cur').value, nxt = ov.querySelector('#pw-new').value, nxt2 = ov.querySelector('#pw-new2').value;
      if (!cur) { err.textContent = '请输入当前密码'; return; }
      if (nxt.length < 6) { err.textContent = '新密码至少 6 位'; return; }
      if (nxt !== nxt2) { err.textContent = '两次输入的新密码不一致'; return; }
      ov.querySelector('#pw-save').disabled = true;
      try {
        const d = await api('/api/me/password', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ current: cur, next: nxt }) });
        if (d.ok) { close(); return; }
        err.textContent = d.error || '修改失败';
      } catch (e) { err.textContent = '网络错误'; }
      ov.querySelector('#pw-save').disabled = false;
    };
    ov.querySelector('#pw-cur').focus();
  };

  // ---------- 全局项目条（#200：顶栏选择器，localStorage 持久，全站联动） ----------
  UI.renderProjectBar = function (containerId, opts) {
    opts = opts || {};
    const sel = document.getElementById(containerId);
    if (!sel) return;
    sel.style.padding = '4px 8px';
    sel.style.fontSize = '13px';
    api('/api/projects').then(d => {
      const projects = (d && d.projects) || [];
      let cur = UI.getProject();
      if (!cur && opts.defaultFirst && projects.length) { UI.setProject(projects[0].id); cur = String(projects[0].id); }
      let html = '';
      if (opts.allowAll !== false) html += '<option value=""' + (cur === '' ? ' selected' : '') + '>全部项目</option>';
      html += projects.map(x => '<option value="' + x.id + '"' + (String(x.id) === cur ? ' selected' : '') + '>' + esc(x.name) + '</option>').join('');
      sel.innerHTML = html;
      sel.addEventListener('change', () => {
        UI.setProject(sel.value);
        if (opts.onChange) opts.onChange(sel.value);
      });
    });
  };

  // ---------- 提单弹框（原生表单组件：压缩/粘贴上传/幂等键/bug 字段） ----------
  let onReqCreated = null;
  window.addEventListener('message', e => {
    if (e.origin !== location.origin) return;
    if (e.data && e.data.type === 'req-created' && UI.onReqCreated) UI.onReqCreated(e.data.id);
  });
  // 粘贴上传：弹框开着时，剪贴板图片直接进压缩管线
  document.addEventListener('paste', async e => {
    const ov = document.getElementById('nr-overlay');
    if (!ov) return; // 提单弹框未打开时不拦截
    const items = (e.clipboardData || {}).items || [];
    const imgs = [...items].filter(it => it.type && it.type.startsWith('image/'));
    if (!imgs.length) return;
    e.preventDefault();
    for (const it of imgs) {
      if (ov.__files.length >= 3) { alert('最多 3 张'); break; }
      const f = it.getAsFile();
      if (!f) continue;
      const named = new File([f], 'paste-' + Date.now() + '.png', { type: f.type || 'image/png' });
      const c = await compressImage(named);
      c._url = URL.createObjectURL(c);
      ov.__files.push(c);
    }
    renderNrThumbs(ov);
  });
  function renderNrThumbs(ov) {
    ov.querySelector('#nr-thumbs').innerHTML = ov.__files.map((f, i) =>
      '<div style="text-align:center"><img class="thumb" src="' + f._url + '">'
      + '<div class="sub" style="font-size:11px;cursor:pointer" data-i="' + i + '">移除</div></div>').join('');
  }

  UI.openNewReqModal = function (projectId, onCreated) {
    UI.onReqCreated = onCreated || null;
    closeOverlay('nr-overlay');
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.id = 'nr-overlay'; ov.style.zIndex = 90;
    ov.__files = [];
    ov.innerHTML = '<div class="modal" style="width:min(640px,94vw);max-height:92vh;overflow:auto">'
      + '<h3>＋ 新需求</h3>'
      + '<div class="fld-row">'
      + '<label class="fld" style="min-width:170px"><span>研发项目 *</span><select id="nr-project"></select></label>'
      + '<label class="fld" style="min-width:130px"><span>类型</span><select id="nr-type">'
      + '<option value="req">需求</option><option value="bug">Bug</option><option value="opt">优化</option></select></label>'
      + '<label class="fld" style="min-width:110px"><span>紧急度</span><select id="nr-urgency">'
      + '<option value="normal">普通</option><option value="urgent">紧急</option></select></label></div>'
      + '<div class="fld-row" id="nr-bug-fields" style="display:none">'
      + '<label class="fld"><span>严重级别</span><select id="nr-severity">'
      + '<option value="">未定级</option><option value="critical">关键</option><option value="major">重大</option>'
      + '<option value="general">一般</option><option value="watch">观察</option></select></label>'
      + '<label class="fld"><span>根因分类</span><select id="nr-root-cause">'
      + '<option value="">未填</option><option value="config">配置</option><option value="defect">缺陷</option>'
      + '<option value="usage">使用</option><option value="external">外部依赖</option><option value="data">数据</option>'
      + '<option value="requirement">需求有误</option></select></label>'
      + '<label class="fld" style="min-width:140px"><span>关联编号</span><input id="nr-ref" maxlength="60" placeholder="ISS-2026-001"></label></div>'
      + '<label>标题 *<input id="nr-title" maxlength="200"></label>'
      + '<label>描述 / 复现步骤<textarea id="nr-desc" rows="4"></textarea></label>'
      + '<label>标签（逗号分隔，可多选）<input id="nr-tags" placeholder="如：测试用,UI"></label>'
      + '<div class="fld"><span>截图（可选，最多 3 张，自动压缩）</span>'
      + '<div style="display:flex;gap:8px;align-items:center;margin-top:4px">'
      + '<button class="btn small" type="button" id="nr-pick">选择文件</button>'
      + '<span class="sub" style="color:#888;font-size:12px">或直接 Command/Ctrl+V 粘贴截图</span></div>'
      + '<input type="file" id="nr-files" accept="image/png,image/jpeg,image/webp,image/gif" multiple style="display:none">'
      + '<div id="nr-thumbs" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"></div></div>'
      + '<div class="err" id="nr-err" style="margin:6px 0 0"></div>'
      + '<div class="modal-btns" style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">'
      + '<button class="btn" id="nr-cancel">取消</button>'
      + '<button class="btn primary" id="nr-submit">提 交</button></div></div>';
    document.body.appendChild(ov);

    const $ = sel => ov.querySelector(sel);
    ov.__files = [];

    // 项目下拉：全局上下文优先，无则传入值
    api('/api/projects').then(d => {
      const projects = (d && d.projects) || [];
      const gp = UI.getProject() || String(projectId || '');
      $('nr-project').innerHTML = projects.map(x => '<option value="' + x.id + '"' + (String(x.id) === gp ? ' selected' : '') + '>' + esc(x.name) + '</option>').join('');
    });
    // 类型切换：bug 字段
    $('nr-type').addEventListener('change', () => {
      $('nr-bug-fields').style.display = $('nr-type').value === 'bug' ? '' : 'none';
    });
    // 文件选择
    $('nr-pick').onclick = () => $('nr-files').click();
    $('nr-files').addEventListener('change', async e => {
      for (const f of e.target.files) {
        if (ov.__files.length >= 3) { alert('最多 3 张'); break; }
        const c = await compressImage(f);
        c._url = URL.createObjectURL(c);
        ov.__files.push(c);
      }
      e.target.value = '';
      renderNrThumbs(ov);
    });
    // 缩略图移除
    $('nr-thumbs').addEventListener('click', e => {
      const i = e.target.dataset && e.target.dataset.i;
      if (i !== undefined) { ov.__files.splice(parseInt(i, 10), 1); renderNrThumbs(ov); }
    });
    // 关闭
    const close = () => closeOverlay('nr-overlay');
    $('nr-cancel').onclick = close;
    ov.addEventListener('click', e => { if (e.target === ov) close(); });
    // 提交（幂等 token）
    $('nr-submit').onclick = async () => {
      const err = $('nr-err');
      err.textContent = '';
      const title = $('nr-title').value.trim();
      if (!title) { err.textContent = '标题必填'; return; }
      if (!$('nr-project').value) { err.textContent = '请选择研发项目'; return; }
      const isBug = $('nr-type').value === 'bug';
      if (isBug && ['general', 'watch'].includes($('nr-severity').value)) {
        const okg = confirm('涉及权限、稽查轨迹、编号唯一性、数据更正留痕的问题，级别最低应定为「重大」。\n确认以当前级别提交吗？');
        if (!okg) return;
      }
      $('nr-submit').disabled = true;
      try {
        if (!window.__nrToken) window.__nrToken = crypto.randomUUID();
        const attachments = [];
        for (const f of ov.__files) {
          const fd = new FormData();
          fd.append('file', f);
          const up = await api('/api/upload', { method: 'POST', body: fd });
          if (!up.ok) throw new Error(up.error || '上传失败');
          attachments.push({ key: up.key, name: up.name, size: up.size });
        }
        const tags = $('nr-tags').value.split(/[,，]/).map(x => x.trim()).filter(Boolean);
        const d = await api('/api/requirements', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            project_id: parseInt($('nr-project').value, 10), title,
            severity: isBug ? $('nr-severity').value : '',
            root_cause: isBug ? $('nr-root-cause').value : '',
            ref_code: isBug ? $('nr-ref').value.trim() : '',
            description: $('nr-desc').value, type: $('nr-type').value,
            urgency: $('nr-urgency').value, tags, attachments,
            client_token: window.__nrToken
          }) });
        if (d.ok) {
          const createdId = d.id;
          window.__nrToken = null;
          close();
          if (UI.onReqCreated) UI.onReqCreated(createdId);
          return;
        }
        err.textContent = d.error || '提交失败';
      } catch (e) { err.textContent = e.message || '网络错误'; }
      $('nr-submit').disabled = false;
    };
    $('nr-title').focus();
  };

  window.PoolUI = UI;
})();
