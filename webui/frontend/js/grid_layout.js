/* grid_layout.js —— 轻量网格布局引擎（无第三方依赖）。

核心概念：
- 虚拟网格 cols×rows；每个板块存网格坐标 {col,row,w,h}。
- 渲染时按容器像素尺寸换算 → 天然比例自适应（窗口缩放板块等比缩放）。
- 编辑态：拖动标题栏移动、拖右下角把手缩放；实时吸附到网格；
  禁止重叠（碰撞检测，冲突则回退到拖动前的位置）。
- 展示态：只读渲染，无手柄。
- 布局变化通过 onChange 回调抛出（由 app.js 落盘）。

对外 API：
  const grid = new GridLayout(canvasEl, { cols, rows, snap, overlap, onChange });
  grid.setPanels(panels);   // panels: [{id,type,visible,grid,locked,content}]
  grid.setEdit(bool);
  grid.render(renderPanelBody);  // renderPanelBody(panelEl, panel) 填充内容
  grid.getPanels();         // 取当前布局（含最新 grid 坐标）
*/

(function () {
  function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

  function rectsOverlap(a, b) {
    return !(a.col + a.w <= b.col || b.col + b.w <= a.col ||
             a.row + a.h <= b.row || b.row + b.h <= a.row);
  }

  class GridLayout {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas;
      this.cols = opts.cols || 12;
      this.rows = opts.rows || 8;
      this.snap = opts.snap !== false;
      this.overlap = !!opts.overlap;
      this.onChange = opts.onChange || function () {};
      this.edit = false;
      this.panels = [];
      this._els = new Map();      // id -> panelEl
      this._drag = null;
      this._bodyRenderer = null;

      this._onMove = this._onMove.bind(this);
      this._onUp = this._onUp.bind(this);
      document.addEventListener("mousemove", this._onMove);
      document.addEventListener("mouseup", this._onUp);
    }

    setPanels(panels) {
      this.panels = (panels || []).map((p) => JSON.parse(JSON.stringify(p)));
    }
    getPanels() { return this.panels.map((p) => JSON.parse(JSON.stringify(p))); }

    setEdit(on) {
      this.edit = !!on;
      this.canvas.setAttribute("data-edit", this.edit ? "1" : "0");
      this._layoutAll();
    }

    setGrid(cols, rows) { this.cols = cols; this.rows = rows; this._layoutAll(); }

    /* 网格 → 像素 */
    _cellW() { return this.canvas.clientWidth / this.cols; }
    _cellH() { return this.canvas.clientHeight / this.rows; }

    _applyRect(el, g) {
      const cw = this._cellW(), ch = this._cellH();
      el.style.left = (g.col * cw) + "px";
      el.style.top = (g.row * ch) + "px";
      el.style.width = (g.w * cw) + "px";
      el.style.height = (g.h * ch) + "px";
    }

    render(bodyRenderer) {
      if (bodyRenderer) this._bodyRenderer = bodyRenderer;
      // 清理已不存在的元素
      const ids = new Set(this.panels.map((p) => p.id));
      this._els.forEach((el, id) => {
        if (!ids.has(id)) { el.remove(); this._els.delete(id); }
      });

      this.panels.forEach((p) => {
        if (!p.visible) {
          const ex = this._els.get(p.id);
          if (ex) { ex.remove(); this._els.delete(p.id); }
          return;
        }
        let el = this._els.get(p.id);
        if (!el) {
          el = this._createPanelEl(p);
          this._els.set(p.id, el);
          this.canvas.appendChild(el);
        }
        el.setAttribute("data-type", p.type);
        el.setAttribute("data-locked", p.locked ? "1" : "0");
        // 内容区交给外部渲染
        const body = el.querySelector(".gl-body");
        if (this._bodyRenderer) this._bodyRenderer(body, p);
        this._applyRect(el, p.grid);
      });
    }

    _createPanelEl(p) {
      const el = document.createElement("div");
      el.className = "gl-panel";
      el.setAttribute("data-id", p.id);

      const bar = document.createElement("div");
      bar.className = "gl-bar";
      bar.innerHTML = '<span class="gl-title"></span>';
      bar.addEventListener("mousedown", (e) => this._startDrag(e, p.id, "move"));

      const body = document.createElement("div");
      body.className = "gl-body";

      const handle = document.createElement("div");
      handle.className = "gl-resize";
      handle.addEventListener("mousedown", (e) => this._startDrag(e, p.id, "resize"));

      el.appendChild(bar);
      el.appendChild(body);
      el.appendChild(handle);
      return el;
    }

    _startDrag(e, id, mode) {
      if (!this.edit) return;
      const p = this.panels.find((x) => x.id === id);
      if (!p || p.locked) return;
      e.preventDefault();
      e.stopPropagation();
      this._drag = {
        id, mode,
        sx: e.clientX, sy: e.clientY,
        orig: JSON.parse(JSON.stringify(p.grid)),
      };
    }

    _onMove(e) {
      if (!this._drag) return;
      const p = this.panels.find((x) => x.id === this._drag.id);
      if (!p) return;
      const cw = this._cellW(), ch = this._cellH();
      const dCol = (e.clientX - this._drag.sx) / cw;
      const dRow = (e.clientY - this._drag.sy) / ch;
      const o = this._drag.orig;
      let g;
      if (this._drag.mode === "move") {
        g = {
          col: clamp(o.col + dCol, 0, this.cols - o.w),
          row: clamp(o.row + dRow, 0, this.rows - o.h),
          w: o.w, h: o.h,
        };
      } else {
        g = {
          col: o.col, row: o.row,
          w: clamp(o.w + dCol, 2, this.cols - o.col),
          h: clamp(o.h + dRow, 2, this.rows - o.row),
        };
      }
      // 拖动过程中实时预览（用未吸附的浮点值，视觉更跟手）
      p.grid = g;
      this._applyRect(this._els.get(p.id), g);
    }

    _onUp() {
      if (!this._drag) return;
      const drag = this._drag;
      this._drag = null;
      const p = this.panels.find((x) => x.id === drag.id);
      if (!p) return;

      // 吸附到整数网格
      let g = {
        col: Math.round(p.grid.col),
        row: Math.round(p.grid.row),
        w: Math.max(2, Math.round(p.grid.w)),
        h: Math.max(2, Math.round(p.grid.h)),
      };
      g.col = clamp(g.col, 0, this.cols - g.w);
      g.row = clamp(g.row, 0, this.rows - g.h);

      // 碰撞检测：禁止重叠时，若冲突则就近找空位，找不到则还原到拖动前。
      if (!this.overlap && this._collides(p.id, g)) {
        const fixed = this._findFreeSpot(p.id, g);
        g = fixed || {
          col: clamp(drag.orig.col, 0, this.cols - drag.orig.w),
          row: clamp(drag.orig.row, 0, this.rows - drag.orig.h),
          w: drag.orig.w, h: drag.orig.h,
        };
        // 找到的空位若与拖动前完全一致（即无处可去），保持原状
      }

      p.grid = g;
      this._applyRect(this._els.get(p.id), g);
      this.onChange(this.getPanels());
    }

    _collides(id, g) {
      return this.panels.some(
        (o) => o.id !== id && o.visible && rectsOverlap(g, o.grid)
      );
    }

    /* 从目标位置附近螺旋搜索一个不冲突的整数格位（保持 w,h 不变）。 */
    _findFreeSpot(id, g) {
      const w = g.w, h = g.h;
      for (let r = 0; r <= this.rows - h; r++) {
        for (let c = 0; c <= this.cols - w; c++) {
          const cand = { col: c, row: r, w, h };
          if (!this._collides(id, cand)) return cand;
        }
      }
      return null;
    }

    _layoutAll() {
      this.panels.forEach((p) => {
        const el = this._els.get(p.id);
        if (el) this._applyRect(el, p.grid);
      });
    }

    /* 窗口/容器尺寸变化时调用：像素按新尺寸重算（网格坐标不变=比例自适应）。 */
    reflow() { this._layoutAll(); }

    /* 增删板块 */
    addPanel(panel) {
      if (!panel.grid) {
        const spot = this._findFreeSpot(panel.id, { col: 0, row: 0, w: 4, h: 3 });
        panel.grid = spot || { col: 0, row: 0, w: 4, h: 3 };
      }
      this.panels.push(panel);
      this.render();
      this.onChange(this.getPanels());
    }
    removePanel(id) {
      this.panels = this.panels.filter((p) => p.id !== id);
      const el = this._els.get(id);
      if (el) { el.remove(); this._els.delete(id); }
      this.onChange(this.getPanels());
    }

    destroy() {
      document.removeEventListener("mousemove", this._onMove);
      document.removeEventListener("mouseup", this._onUp);
    }
  }

  window.GridLayout = GridLayout;
})();
