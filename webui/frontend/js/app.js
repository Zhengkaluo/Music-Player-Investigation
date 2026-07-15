/* app.js —— 控制器：连接后端、驱动 GridLayout、编辑态、设置、持久化。 */

(function () {
  const $ = (id) => document.getElementById(id);
  let api = null;
  let lastState = null;
  let grid = null;
  let _lastPanelsSig = "";   // 已同步进 grid 的 panels 签名，用于避免重复回灌/被覆盖
  let _lastLocalEdit = 0;    // 最近一次本地编辑时间戳，用于阻止轮询覆盖

  function resolveApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return window.MockAPI;
  }

  /* 布局变更 → 落盘（防抖） */
  let saveTimer = null;
  function persistPanels(panels) {
    if (lastState) lastState.config.panels = panels;
    _lastPanelsSig = JSON.stringify(panels);  // 与回灌信号同步，防止被 pullState 覆盖
    _lastLocalEdit = Date.now();
    if (!api || !api.update_config) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { api.update_config({ panels: panels }); }, 300);
  }

  function initGrid(cfg) {
    const layout = cfg.layout || {};
    const gcfg = layout.grid || { cols: 12, rows: 8 };
    grid = new window.GridLayout($("glCanvas"), {
      cols: gcfg.cols, rows: gcfg.rows,
      snap: layout.snap !== false,
      overlap: !!layout.overlap,
      onChange: persistPanels,
    });
    const panels = cfg.panels || [];
    grid.setPanels(panels);
    _lastPanelsSig = JSON.stringify(panels);
    grid.setEdit(!!layout.edit);
    renderAll();
  }

  function renderAll() {
    if (!lastState) return;
    const app = $("app");
    window.Render.applyTheme(app, lastState);
    app.setAttribute("data-mode", (lastState.config.layout || {}).mode || "grid");
    if (grid) {
      grid.render((body, panel) => window.Render.panelBody(body, panel, lastState));
    }
  }

  async function pullState() {
    if (!api) return;
    try {
      const state = await api.get_state();
      const firstTime = !lastState;
      if (firstTime) {
        lastState = state;
        initGrid(state.config);
        syncSettingsUI(state);
        return;
      }
      // 本地编辑保护：刚改过内容/布局的一段时间内，不让轮询回来的旧数据覆盖 panels。
      const editing = (grid && grid.edit) || (Date.now() - _lastLocalEdit < 4000);
      if (editing) {
        // 保留本地 panels，只更新播放信息与主题
        state.config.panels = lastState.config.panels;
      } else {
        syncPanelsIntoGrid(state.config.panels || []);
      }
      lastState = state;
      renderAll();
    } catch (e) { /* 后端未就绪，静默重试 */ }
  }

  /* 把 config.panels 同步进 grid 引擎：仅当内容/数量真正变化时才 setPanels，
     避免每 3 秒无谓重建 DOM。 */
  function syncPanelsIntoGrid(panels) {
    const sig = JSON.stringify(panels);
    if (sig === _lastPanelsSig) return;
    _lastPanelsSig = sig;
    grid.setPanels(panels);
  }

  function renderPanels() {
    if (grid) grid.render((body, panel) => window.Render.panelBody(body, panel, lastState));
  }

  /* ---------- 编辑态 ---------- */
  function setEdit(on) {
    if (!grid) return;
    grid.setEdit(on);
    const btn = $("npEditToggle");
    btn.setAttribute("data-active", on ? "1" : "0");
    btn.textContent = on ? "完成" : "编辑布局";
    $("npAddPanel").hidden = !on;
    if (lastState) {
      lastState.config.layout = lastState.config.layout || {};
      lastState.config.layout.edit = on;
    }
    if (api && api.update_config) api.update_config({ layout: { edit: on } });
  }

  /* ---------- 增删自定义板块 ---------- */
  function addCustomPanel() {
    if (!grid) return;
    const id = "custom-" + Date.now();
    grid.addPanel({
      id, type: "custom", visible: true, locked: false,
      grid: null,
      content: { kind: "text", source: "新内容板块", follow_theme: true, fit: "cover" },
    });
    if (lastState) lastState.config.panels = grid.getPanels();
    renderPanels();
    buildPanelEditors();
  }

  function removePanel(id) {
    if (!grid) return;
    grid.removePanel(id);
    if (lastState) lastState.config.panels = grid.getPanels();
    buildPanelEditors();
  }

  /* 更新某板块的 content 字段并同步渲染+落盘 */
  function updatePanelContent(id, patch) {
    if (!grid) return;
    const panels = grid.getPanels();
    const p = panels.find((x) => x.id === id);
    if (!p) return;
    p.content = Object.assign({}, p.content || {}, patch);
    grid.setPanels(panels);
    if (lastState) lastState.config.panels = panels;
    renderPanels();
    persistPanels(panels);
  }

  /* ---------- 设置面板：自定义板块编辑器 ---------- */
  function buildPanelEditors() {
    const list = $("npPanelList");
    if (!list || !lastState) return;
    list.innerHTML = "";
    const panels = (lastState.config.panels || []).filter((p) => p.type === "custom");
    if (panels.length === 0) {
      list.innerHTML = '<div style="font-size:12px;color:var(--c-muted)">暂无自定义板块，点上方“添加”。</div>';
      return;
    }
    panels.forEach((p, idx) => {
      const node = $("tplPanelEditor").content.cloneNode(true);
      const root = node.querySelector(".np-panel-editor");
      root.dataset.pid = p.id;
      root.querySelector(".np-pe-name").textContent = "板块 " + (idx + 1);
      const c = p.content || {};
      const kindSel = root.querySelector(".np-pe-kind");
      const textField = root.querySelector(".np-pe-text-field");
      const textArea = root.querySelector(".np-pe-text");
      const srcField = root.querySelector(".np-pe-src-field");
      const srcInput = root.querySelector(".np-pe-src");
      const pickBtn = root.querySelector(".np-pe-pick");
      const followCb = root.querySelector(".np-pe-follow");

      kindSel.value = c.kind || "text";
      followCb.checked = c.follow_theme !== false;
      if ((c.kind || "text") === "text") { textArea.value = c.source || ""; }
      else { srcInput.value = c.source || ""; }

      function refreshFields() {
        const isText = kindSel.value === "text";
        textField.hidden = !isText;
        srcField.hidden = isText;
      }
      refreshFields();

      // 切换类型时只切换输入区显隐，不立即应用（等“保存修改”）。
      kindSel.addEventListener("change", () => {
        refreshFields();
        markDirty();
      });
      textArea.addEventListener("input", markDirty);
      srcInput.addEventListener("input", markDirty);
      followCb.addEventListener("change", markDirty);

      const saveBtn = root.querySelector(".np-pe-save");
      function markDirty() {
        saveBtn.textContent = "保存修改";
        saveBtn.removeAttribute("data-saved");
      }
      saveBtn.addEventListener("click", () => {
        const isText = kindSel.value === "text";
        const source = isText ? textArea.value : srcInput.value;
        // 一次性应用所有字段到显示区并落盘
        updatePanelContent(p.id, {
          kind: kindSel.value,
          source: source,
          follow_theme: followCb.checked,
        });
        saveBtn.textContent = "已保存 ✓";
        saveBtn.setAttribute("data-saved", "1");
      });

      pickBtn.addEventListener("click", async () => {
        if (api && api.pick_file) {
          const path = await api.pick_file(kindSel.value);
          if (path) { srcInput.value = path; markDirty(); }
        } else {
          srcInput.focus();
        }
      });

      root.querySelector(".np-pe-del").addEventListener("click", () => removePanel(p.id));
      list.appendChild(node);
    });
  }

  /* ---------- 设置面板：外观/窗口 ---------- */
  function syncSettingsUI(state) {
    const cfg = state.config || {};
    $("npThemeSelect").value = cfg.theme_id || "immersive";
    $("npModeSelect").value = (cfg.layout || {}).mode || "grid";
    const win = cfg.window || {};
    const alphaPct = Math.round((win.alpha != null ? win.alpha : 0.95) * 100);
    $("npAlpha").value = alphaPct;
    $("npAlphaVal").textContent = alphaPct + "%";
    $("npTopmost").checked = win.topmost !== false;
    buildPanelEditors();
  }

  function wireUI() {
    $("npGear").addEventListener("click", () => {
      const s = $("npSettings"); s.hidden = !s.hidden;
      if (!s.hidden) buildPanelEditors();
    });
    $("npSettingsClose").addEventListener("click", () => { $("npSettings").hidden = true; });

    $("npThemeSelect").addEventListener("change", async (e) => {
      const themeId = e.target.value;
      if (lastState) { lastState.config.theme_id = themeId; renderAll(); }
      if (api && api.update_config) await api.update_config({ theme_id: themeId });
    });

    $("npModeSelect").addEventListener("change", async (e) => {
      const mode = e.target.value;
      if (lastState) {
        lastState.config.layout = lastState.config.layout || {};
        lastState.config.layout.mode = mode;
        $("app").setAttribute("data-mode", mode);
      }
      if (api && api.update_config) await api.update_config({ layout: { mode } });
    });

    $("npAlpha").addEventListener("input", (e) => {
      const pct = parseInt(e.target.value, 10);
      $("npAlphaVal").textContent = pct + "%";
    });
    $("npAlpha").addEventListener("change", async (e) => {
      const alpha = parseInt(e.target.value, 10) / 100;
      if (lastState) { lastState.config.window = lastState.config.window || {}; lastState.config.window.alpha = alpha; }
      if (api && api.set_window_opacity) await api.set_window_opacity(alpha);
      else if (api && api.update_config) await api.update_config({ window: { alpha } });
    });

    $("npTopmost").addEventListener("change", async (e) => {
      const on = e.target.checked;
      if (lastState) { lastState.config.window = lastState.config.window || {}; lastState.config.window.topmost = on; }
      if (api && api.set_topmost) await api.set_topmost(on);
      else if (api && api.update_config) await api.update_config({ window: { topmost: on } });
    });

    $("npEditToggle").addEventListener("click", () => {
      const active = $("npEditToggle").getAttribute("data-active") === "1";
      setEdit(!active);
    });
    $("npAddPanel").addEventListener("click", addCustomPanel);
    $("npAddPanel2").addEventListener("click", addCustomPanel);

    wireResizeGrip();
  }

  /* 无边框窗口缩放：拖右下角 grip，实时调用后端 resize_window。 */
  function wireResizeGrip() {
    const grip = $("npResizeGrip");
    if (!grip) return;
    let dragging = false, sx = 0, sy = 0, sw = 0, sh = 0, rafPending = false, pendW = 0, pendH = 0;

    function applyResize() {
      rafPending = false;
      if (api && api.resize_window) api.resize_window(pendW, pendH);
    }
    grip.addEventListener("mousedown", (e) => {
      dragging = true;
      sx = e.screenX; sy = e.screenY;
      sw = window.innerWidth; sh = window.innerHeight;
      e.preventDefault(); e.stopPropagation();
    });
    document.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      pendW = Math.max(320, sw + (e.screenX - sx));
      pendH = Math.max(200, sh + (e.screenY - sy));
      if (!rafPending) { rafPending = true; requestAnimationFrame(applyResize); }
    });
    document.addEventListener("mouseup", () => { dragging = false; });
  }

  window.onStatePush = function () { pullState(); };

  function init() {
    api = resolveApi();
    wireUI();
    const ro = new ResizeObserver(() => { if (grid) grid.reflow(); });
    ro.observe($("glCanvas"));
    pullState();
    setInterval(pullState, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else { init(); }

  window.addEventListener("pywebviewready", () => { api = resolveApi(); pullState(); });
})();
