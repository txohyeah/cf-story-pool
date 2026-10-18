// app-common.js — 需求池全站共享 UI 组件（#197 组件化：提单弹框/确认框/改密码弹框）
// 用法：页面引入本文件后调 PoolUI.openNewReqModal(projectId) / PoolUI.showConfirm(msg, onOk) / PoolUI.openPwdModal()
// 组件 DOM 由本文件动态创建，页面无需预置 HTML。
(function () {
  'use strict';
  const UI = {};
  const BASE = '';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function api(path, opts) {
    return fetch(BASE + path, opts).then(r => {
      if (r.status === 401) { location.href = '/login'; return {}; }
      return r.json();
    });
  }

  // ---------- 提单弹框（iframe 承载 new.html 全功能；成功 postMessage 关闭并回调） ----------
  let onReqCreated = null;
  window.addEventListener('message', e => {
    if (e.origin !== location.origin) return;
    if (e.data && e.data.type === 'req-created' && UI.onReqCreated) UI.onReqCreated(e.data.id);
  });

  UI.openNewReqModal = function (projectId, onCreated) {
    UI.onReqCreated = onCreated || null;
    closeOverlay('nr-overlay');
    const ov = document.createElement('div');
    ov.className = 'modal-overlay'; ov.id = 'nr-overlay'; ov.style.zIndex = 90;
    ov.innerHTML = '<div class="modal" style="position:relative;width:min(700px,94vw);height:min(88vh,800px);padding:0;overflow:hidden">'
      + '<button id="nr-x" title="关闭（提单内容将丢失）" style="position:absolute;top:8px;right:10px;z-index:10;'
      + 'border:1px solid var(--line);background:#fff;border-radius:6px;padding:2px 10px;cursor:pointer;font-size:14px">✕ 关闭</button>'
      + '<iframe style="width:100%;height:100%;border:0" src="' + BASE + '/new.html?project=' + esc(projectId) + '&embed=1"></iframe></div>';
    document.body.appendChild(ov);
    ov.querySelector('#nr-x').onclick = () => closeOverlay('nr-overlay');
  };
  function closeOverlay(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
  }

  // ---------- 统一二次确认框（替代原生 confirm） ----------
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

  // ---------- 改密码弹框（当页组件，不再跳转） ----------
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

  window.PoolUI = UI;
})();
