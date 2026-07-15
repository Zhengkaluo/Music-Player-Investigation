/* render.js —— 渲染层：主题注入 + 面板内容填充。
   与 GridLayout 配合：GridLayout 负责外壳与定位，render 负责把 state
   填进每个面板的 .gl-body（通过 renderPanelBody 回调）。 */

(function () {
  const $ = (id) => document.getElementById(id);

  function fmtTime(sec) {
    if (sec == null || isNaN(sec)) return "0:00";
    sec = Math.max(0, Math.floor(sec));
    return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
  }

  function applyTheme(app, state) {
    const theme = state.theme || {};
    const themeId = (state.config && state.config.theme_id) || "immersive";
    app.setAttribute("data-theme", themeId);
    const followsCover = themeId === "immersive" || themeId === "adaptive";
    if (followsCover) {
      ["bg", "fg", "muted", "primary", "accent"].forEach((k) => {
        if (theme[k]) app.style.setProperty("--c-" + k, theme[k]);
      });
    } else {
      ["--c-bg", "--c-fg", "--c-muted", "--c-primary"].forEach((v) => app.style.removeProperty(v));
      if (theme.accent) app.style.setProperty("--c-accent", theme.accent);
    }
    // 沉浸主题：模糊背景用封面
    const bg = $("npBg");
    const src = coverSrc(state.track || {});
    if (themeId === "immersive" && src) {
      bg.style.backgroundImage = "url('" + src + "')";
      bg.style.opacity = "1";
    } else {
      bg.style.opacity = "0";
    }
  }

  function coverSrc(track) {
    if (track.cover_data_url) return track.cover_data_url;
    if (track.cover_base64) return "data:image/png;base64," + track.cover_base64;
    return null;
  }

  function fillNowPlaying(body, track) {
    if (!body.querySelector(".np-info")) {
      body.appendChild($("tplNowPlaying").content.cloneNode(true));
    }
    body.querySelector(".np-status").textContent = track.status || "";
    body.querySelector(".np-title").textContent = track.title || "未在播放";
    body.querySelector(".np-artist").textContent = track.artist || "—";
    body.querySelector(".np-album").textContent = track.album || "";

    const img = body.querySelector(".np-cover-img");
    const fb = body.querySelector(".np-cover-fallback");
    const src = coverSrc(track);
    if (src) { img.src = src; img.hidden = false; fb.style.display = "none"; }
    else { img.hidden = true; fb.style.display = "block"; }

    const prog = body.querySelector(".np-progress");
    if (track.duration && track.duration > 0) {
      prog.hidden = false;
      const pct = Math.min(100, ((track.position || 0) / track.duration) * 100);
      body.querySelector(".np-progress-fill").style.width = pct + "%";
      body.querySelector(".np-pos").textContent = fmtTime(track.position);
      body.querySelector(".np-dur").textContent = fmtTime(track.duration);
    } else {
      prog.hidden = true;
    }
  }

  /* 本地路径 → 可加载 URL 的解析缓存：{ 原始source: 解析后URL } */
  const _mediaCache = {};
  function resolveMedia(source, cb) {
    if (!source) { cb(""); return; }
    const low = source.toLowerCase();
    if (low.startsWith("http") || low.startsWith("data:") || low.startsWith("file://")) {
      cb(source); return;
    }
    if (_mediaCache[source] !== undefined) { cb(_mediaCache[source]); return; }
    const api = (window.pywebview && window.pywebview.api) || window.MockAPI;
    if (api && api.resolve_media) {
      api.resolve_media(source).then((url) => { _mediaCache[source] = url || source; cb(_mediaCache[source]); })
        .catch(() => cb(source));
    } else {
      cb(source);
    }
  }

  function fillCustom(body, panel) {
    if (!body.querySelector(".np-custom-empty")) {
      body.appendChild($("tplCustom").content.cloneNode(true));
    }
    const c = panel.content || {};
    const vid = body.querySelector(".np-custom-video");
    const img = body.querySelector(".np-custom-image");
    const txt = body.querySelector(".np-custom-text");
    const empty = body.querySelector(".np-custom-empty");

    const kind = c.kind || "text";
    const hasSource = !!c.source;
    empty.hidden = hasSource;

    const showVideo = kind === "video" && hasSource;
    const showImage = kind === "image" && hasSource;
    const showText = kind === "text" && hasSource;

    vid.hidden = !showVideo; img.hidden = !showImage; txt.hidden = !showText;

    if (showVideo) {
      vid.style.objectFit = c.fit || "cover";
      resolveMedia(c.source, (url) => {
        if (vid.getAttribute("data-src-key") !== c.source) {
          vid.src = url; vid.setAttribute("data-src-key", c.source);
        }
        vid.autoplay = true; vid.play().catch(() => {});
      });
    } else if (!vid.paused) { vid.pause(); }

    if (showImage) {
      img.style.objectFit = c.fit || "cover";
      resolveMedia(c.source, (url) => {
        if (img.getAttribute("data-src-key") !== c.source) {
          img.src = url; img.setAttribute("data-src-key", c.source);
        }
      });
    }
    if (showText) { txt.textContent = c.source; }
  }

  window.Render = {
    applyTheme,
    // 供 GridLayout 调用：填充单个面板内容
    panelBody(body, panel, state) {
      if (panel.type === "nowplaying") fillNowPlaying(body, (state && state.track) || {});
      else if (panel.type === "custom") fillCustom(body, panel);
    },
  };
})();
