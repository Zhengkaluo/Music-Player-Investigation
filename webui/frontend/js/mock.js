/* mock.js —— 浏览器独立预览用的假数据。
   当页面不在 pywebview 中（window.pywebview 不存在）时，
   app.js 会退回用 MockAPI，让整套前端能在普通浏览器里预览。 */

(function () {
  function makeCoverDataUrl(c1, c2) {
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="300">' +
      '<defs><radialGradient id="g" cx="50%" cy="45%" r="70%">' +
      '<stop offset="0%" stop-color="' + c1 + '"/>' +
      '<stop offset="100%" stop-color="' + c2 + '"/>' +
      '</radialGradient></defs>' +
      '<rect width="300" height="300" fill="url(#g)"/>' +
      '<circle cx="150" cy="135" r="60" fill="rgba(0,0,0,0.25)"/>' +
      '<circle cx="150" cy="135" r="16" fill="' + c2 + '"/>' +
      '</svg>';
    return 'data:image/svg+xml;base64,' + btoa(svg);
  }

  const MOCK_STATE = {
    track: {
      title: "夜航西飞",
      artist: "柏林独奏 · Solo Berlin",
      album: "午夜漫游",
      status: "正在播放",
      cover_base64: null,
      cover_data_url: makeCoverDataUrl("#7f6fe0", "#2a2440"),
      position: 102,
      duration: 185,
      app_name: "MockPlayer",
      is_playing: true,
    },
    theme: {
      primary: "#6d5ec9",
      accent: "#8f7fe0",
      bg: "#1f1b2e",
      fg: "#ffffff",
      muted: "#c9c4ec",
      palette: ["#6d5ec9", "#4a3f9e", "#2a2440"],
      is_dark: true,
    },
    config: {
      theme_id: "immersive",
      window: { width: 640, height: 380, alpha: 0.95, topmost: true },
      style: {
        font_family: "Microsoft YaHei UI",
        alignment: { title: "left", artist: "left", album: "left", status: "left" },
      },
      thumbnail: { show: true, size: 400 },
      auto_update: { enabled: true, interval: 5 },
      manual_data: {},
      layout: {
        mode: "grid",
        grid: { cols: 12, rows: 8 },
        edit: false,
        snap: true,
        overlap: false,
      },
      panels: [
        { id: "nowplaying", type: "nowplaying", visible: true, locked: false,
          grid: { col: 0, row: 1, w: 7, h: 5 } },
        { id: "custom-1", type: "custom", visible: true, locked: false,
          grid: { col: 7, row: 1, w: 5, h: 5 },
          content: { kind: "text", source: "☕ 咖啡店营业中\n每日 9:00 - 18:00\n扫码点单 →", follow_theme: true, fit: "cover" } },
      ],
      custom_content: {
        enabled: true, type: "text",
        source: "☕ 咖啡店营业中\n每日 9:00 - 18:00\n扫码点单 →",
        follow_theme: true, fit: "cover",
      },
    },
  };

  window.MockAPI = {
    _state: JSON.parse(JSON.stringify(MOCK_STATE)),
    get_state() { return Promise.resolve(this._state); },
    update_config(patch) {
      const cfg = this._state.config;
      patch = patch || {};
      if (patch.theme_id !== undefined) cfg.theme_id = patch.theme_id;
      if (patch.panels) cfg.panels = patch.panels;
      if (patch.layout) Object.assign(cfg.layout, patch.layout);
      if (patch.style) Object.assign(cfg.style, patch.style);
      if (patch.custom_content) Object.assign(cfg.custom_content, patch.custom_content);
      return Promise.resolve(cfg);
    },
    set_window_bounds() { return Promise.resolve(this._state.config.window); },
    refresh_now() { return Promise.resolve(this._state); },
  };
})();
