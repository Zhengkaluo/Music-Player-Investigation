/* app.js —— 控制器：连接后端、驱动 GridLayout、编辑态、设置、持久化。 */

(function () {
  const $ = (id) => document.getElementById(id);
  let api = null;
  let lastState = null;
  let grid = null;

  function resolveApi() {
    if (window.pywebview && window.pywebview.api) return window.pywebview.api;
    return window.MockAPI;
  }

  /* 布局变更 → 落盘（防抖） */
  let saveTimer = null;
  function persistPanels(panels) {
    if (!api || !api.update_config) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      api.update_config({ panels: panels });
    }, 300);
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
    grid.setPanels(cfg.panels || []);
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
      lastState = state;
      if (firstTime) {
        initGrid(state.config);
        syncSettingsUI(state);
      } else {
        // 后续刷新只更新内容与主题，不重建网格（避免打断拖动）
        renderAll();
      }
    } catch (e) { /* 后端未就绪，静默重试 */ }
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

  /* ---------- 添加自定义板块 ---------- */
  function addCustomPanel() {
    if (!grid) return;
    const id = "custom-" + Date.now();
    grid.addPanel({
      id, type: "custom", visible: true, locked: false,
      grid: null,   // 由引擎找空位
      content: { kind: "text", source: "新内容板块", follow_theme: true, fit: "cover" },
    });
    grid.render((body, panel) => window.Render.panelBody(body, panel, lastState));
  }

  /* ---------- 设置面板 ---------- */
  function syncSettingsUI(state) {
    const cfg = state.config || {};
    $("npThemeSelect").value = cfg.theme_id || "immersive";
    $("npModeSelect").value = (cfg.layout || {}).mode || "grid";
  }

  function wireUI() {
    $("npGear").addEventListener("click", () => {
      const s = $("npSettings"); s.hidden = !s.hidden;
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

    $("npEditToggle").addEventListener("click", () => {
      const active = $("npEditToggle").getAttribute("data-active") === "1";
      setEdit(!active);
    });
    $("npAddPanel").addEventListener("click", addCustomPanel);
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
