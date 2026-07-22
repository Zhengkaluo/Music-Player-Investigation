(() => {
  "use strict";

  const AUDIO_EXTENSIONS = new Set(["mp3", "m4a", "wav", "flac", "ogg", "oga", "aac", "aif", "aiff"]);
  const STORAGE_KEY = "flowset-annotation-draft-v1";
  const SCHEMA_VERSION = "flowset.annotations/v1";

  const initialDimensions = [
    { id: "time-scene", name: "适合的时段", mode: "single", options: makeOptions(["清晨", "白天", "黄昏", "深夜", "不确定"]) },
    { id: "energy-state", name: "能量状态", mode: "single", options: makeOptions(["平静", "渐进", "有冲劲", "爆发", "不确定"]) },
    { id: "emotion", name: "情绪感受", mode: "multiple", options: makeOptions(["温暖", "明亮", "忧郁", "梦幻", "紧张", "释放", "不确定"]) },
    { id: "texture", name: "声音质感", mode: "multiple", options: makeOptions(["通透", "柔软", "粗粝", "厚重", "空间感", "不确定"]) },
  ];

  const state = {
    dimensions: clone(initialDimensions),
    files: [],
    annotations: {},
    importedTracks: [],
    objectUrls: [],
  };

  const elements = {
    chooseFolderButton: byId("chooseFolderButton"),
    chooseFilesButton: byId("chooseFilesButton"),
    folderInput: byId("folderInput"),
    filesInput: byId("filesInput"),
    dropZone: byId("dropZone"),
    loadStatus: byId("loadStatus"),
    annotatorInput: byId("annotatorInput"),
    datasetInput: byId("datasetInput"),
    dimensionEditor: byId("dimensionEditor"),
    addDimensionButton: byId("addDimensionButton"),
    searchInput: byId("searchInput"),
    unfinishedOnlyInput: byId("unfinishedOnlyInput"),
    emptyState: byId("emptyState"),
    trackList: byId("trackList"),
    progressLabel: byId("progressLabel"),
    progressFill: byId("progressFill"),
    draftStatus: byId("draftStatus"),
    exportButton: byId("exportButton"),
    importButton: byId("importButton"),
    importInput: byId("importInput"),
    clearDraftButton: byId("clearDraftButton"),
    toast: byId("toast"),
  };

  restoreDraft();
  bindEvents();
  renderDimensionEditor();
  renderTracks();
  updateProgress();

  function byId(id) { return document.getElementById(id); }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function makeId(prefix) { return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`; }
  function makeOptions(labels) { return labels.map((label, index) => ({ id: `option-${index + 1}-${slug(label)}`, label })); }
  function slug(text) { return String(text).trim().toLowerCase().replace(/\s+/g, "-").replace(/[^\p{L}\p{N}-]/gu, "").slice(0, 32) || "item"; }
  function fileKey(file) { return `${file.name}::${file.size}::${file.lastModified || 0}`; }
  function importedTrackKey(track) { return `${track.file?.name || ""}::${track.file?.size || 0}`; }
  function selectedCount(annotation) { return Object.values(annotation?.selections || {}).reduce((sum, values) => sum + values.length, 0); }
  function isComplete(annotation) { return selectedCount(annotation) > 0; }
  function fileExtension(name) { return name.includes(".") ? name.split(".").pop().toLowerCase() : ""; }
  function audioFiles(files) { return [...files].filter((file) => file.type.startsWith("audio/") || AUDIO_EXTENSIONS.has(fileExtension(file.name))); }
  function formatBytes(bytes) { if (!bytes) return "0 B"; const units = ["B", "KB", "MB", "GB"]; const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1); return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`; }
  function safeFilename(value) { return String(value || "flowset-annotations").trim().replace(/[\\/:*?"<>|]+/g, "-").replace(/\s+/g, "-").slice(0, 80) || "flowset-annotations"; }

  function bindEvents() {
    elements.chooseFolderButton.addEventListener("click", () => elements.folderInput.click());
    elements.chooseFilesButton.addEventListener("click", () => elements.filesInput.click());
    elements.folderInput.addEventListener("change", (event) => loadFiles(event.target.files));
    elements.filesInput.addEventListener("change", (event) => loadFiles(event.target.files));
    elements.addDimensionButton.addEventListener("click", addDimension);
    elements.searchInput.addEventListener("input", renderTracks);
    elements.unfinishedOnlyInput.addEventListener("change", renderTracks);
    elements.annotatorInput.addEventListener("input", saveDraftSoon);
    elements.datasetInput.addEventListener("input", saveDraftSoon);
    elements.exportButton.addEventListener("click", exportJson);
    elements.importButton.addEventListener("click", () => elements.importInput.click());
    elements.importInput.addEventListener("change", importJson);
    elements.clearDraftButton.addEventListener("click", clearDraft);

    ["dragenter", "dragover"].forEach((name) => elements.dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      elements.dropZone.classList.add("is-dragging");
    }));
    ["dragleave", "drop"].forEach((name) => elements.dropZone.addEventListener(name, (event) => {
      event.preventDefault();
      elements.dropZone.classList.remove("is-dragging");
    }));
    elements.dropZone.addEventListener("drop", (event) => loadFiles(event.dataTransfer.files));
    elements.dropZone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") elements.chooseFilesButton.click();
    });

    window.addEventListener("beforeunload", revokeObjectUrls);
  }

  function loadFiles(fileList) {
    const files = audioFiles(fileList).sort((a, b) => a.name.localeCompare(b.name, "zh-CN", { numeric: true }));
    if (!files.length) {
      showToast("没有找到支持的音频文件");
      return;
    }

    revokeObjectUrls();
    state.files = files.map((file) => {
      const url = URL.createObjectURL(file);
      state.objectUrls.push(url);
      const relativePath = file.webkitRelativePath || file.name;
      return { file, url, relativePath, key: fileKey(file) };
    });

    applyImportedAnnotations();
    elements.loadStatus.textContent = `已载入 ${files.length} 首音乐，共 ${formatBytes(files.reduce((sum, file) => sum + file.size, 0))}。音频只在当前浏览器标签页中使用。`;
    elements.folderInput.value = "";
    elements.filesInput.value = "";
    renderTracks();
    updateProgress();
    saveDraftSoon();
    showToast(`已载入 ${files.length} 首音乐`);
  }

  function revokeObjectUrls() {
    state.objectUrls.forEach((url) => URL.revokeObjectURL(url));
    state.objectUrls = [];
  }

  function defaultAnnotation() { return { selections: {}, confidence: "", note: "" }; }
  function annotationFor(key) { return state.annotations[key] || (state.annotations[key] = defaultAnnotation()); }

  function renderDimensionEditor() {
    elements.dimensionEditor.replaceChildren();
    state.dimensions.forEach((dimension) => {
      const row = document.createElement("div");
      row.className = "dimension-row";
      row.dataset.dimensionId = dimension.id;
      row.innerHTML = `
        <label>维度名称<input class="dimension-name" type="text" value="${escapeAttribute(dimension.name)}" /></label>
        <label>选择方式<select class="dimension-mode"><option value="single" ${dimension.mode === "single" ? "selected" : ""}>单选</option><option value="multiple" ${dimension.mode === "multiple" ? "selected" : ""}>多选</option></select></label>
        <label>选项<input class="dimension-options" type="text" value="${escapeAttribute(dimension.options.map((option) => option.label).join("，"))}" /></label>
        <button class="icon-button delete-dimension" type="button" title="删除这个维度" aria-label="删除 ${escapeAttribute(dimension.name)}">×</button>`;

      row.querySelector(".dimension-name").addEventListener("change", (event) => updateDimension(dimension.id, { name: event.target.value.trim() || "未命名维度" }));
      row.querySelector(".dimension-mode").addEventListener("change", (event) => updateDimension(dimension.id, { mode: event.target.value }));
      row.querySelector(".dimension-options").addEventListener("change", (event) => {
        const labels = event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean);
        if (!labels.length) { event.target.value = dimension.options.map((option) => option.label).join("，"); showToast("每个维度至少需要一个选项"); return; }
        const existingByLabel = new Map(dimension.options.map((option) => [option.label, option]));
        updateDimension(dimension.id, { options: labels.map((label) => existingByLabel.get(label) || { id: makeId("option"), label }) });
      });
      row.querySelector(".delete-dimension").addEventListener("click", () => deleteDimension(dimension.id));
      elements.dimensionEditor.append(row);
    });
  }

  function addDimension() {
    state.dimensions.push({ id: makeId("dimension"), name: "我的新维度", mode: "single", options: makeOptions(["选项 A", "选项 B", "不确定"]) });
    renderDimensionEditor();
    renderTracks();
    saveDraftSoon();
  }

  function updateDimension(id, patch) {
    const dimension = state.dimensions.find((item) => item.id === id);
    if (!dimension) return;
    Object.assign(dimension, patch);
    if (dimension.mode === "single") {
      Object.values(state.annotations).forEach((annotation) => {
        if ((annotation.selections[id] || []).length > 1) annotation.selections[id] = annotation.selections[id].slice(0, 1);
      });
    }
    renderDimensionEditor();
    renderTracks();
    saveDraftSoon();
  }

  function deleteDimension(id) {
    if (state.dimensions.length === 1) { showToast("至少保留一个维度"); return; }
    state.dimensions = state.dimensions.filter((item) => item.id !== id);
    Object.values(state.annotations).forEach((annotation) => delete annotation.selections[id]);
    renderDimensionEditor();
    renderTracks();
    saveDraftSoon();
  }

  function renderTracks() {
    elements.trackList.replaceChildren();
    elements.emptyState.hidden = state.files.length > 0;
    if (!state.files.length) return;

    const query = elements.searchInput.value.trim().toLocaleLowerCase("zh-CN");
    const unfinishedOnly = elements.unfinishedOnlyInput.checked;
    const visible = state.files.filter((entry) => {
      const matchesQuery = !query || entry.file.name.toLocaleLowerCase("zh-CN").includes(query);
      const matchesProgress = !unfinishedOnly || !isComplete(annotationFor(entry.key));
      return matchesQuery && matchesProgress;
    });

    if (!visible.length) {
      const message = document.createElement("div");
      message.className = "no-results";
      message.textContent = "没有符合当前筛选条件的曲目。";
      elements.trackList.append(message);
      return;
    }

    visible.forEach((entry) => elements.trackList.append(createTrackCard(entry, state.files.indexOf(entry))));
  }

  function createTrackCard(entry, index) {
    const annotation = annotationFor(entry.key);
    const card = document.createElement("article");
    card.className = `track-card${isComplete(annotation) ? " is-complete" : ""}`;
    card.dataset.trackKey = entry.key;

    const head = document.createElement("div");
    head.className = "track-head";
    head.innerHTML = `<div><div class="track-number">TRACK ${String(index + 1).padStart(2, "0")}</div><h3 class="track-title">${escapeHtml(stripExtension(entry.file.name))}</h3><div class="track-meta">${escapeHtml(fileExtension(entry.file.name).toUpperCase())} · ${formatBytes(entry.file.size)}</div></div>`;
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = entry.url;
    audio.addEventListener("play", () => document.querySelectorAll("audio").forEach((other) => { if (other !== audio) other.pause(); }));
    head.append(audio);

    const body = document.createElement("div");
    body.className = "track-body";
    const tagGrid = document.createElement("div");
    tagGrid.className = "tag-grid";
    state.dimensions.forEach((dimension) => tagGrid.append(createTagField(entry.key, dimension, annotation)));
    body.append(tagGrid);

    const extras = document.createElement("div");
    extras.className = "track-extras";
    extras.innerHTML = `
      <label>把握程度<select class="confidence-input"><option value="">未填写</option>${[1, 2, 3, 4, 5].map((value) => `<option value="${value}" ${String(annotation.confidence) === String(value) ? "selected" : ""}>${value} / 5</option>`).join("")}</select></label>
      <label>备注（可选）<textarea class="note-input" rows="1" placeholder="例如：只在 1:20 之后有冲劲">${escapeHtml(annotation.note || "")}</textarea></label>`;
    extras.querySelector(".confidence-input").addEventListener("change", (event) => { annotation.confidence = event.target.value; annotationChanged(card); });
    extras.querySelector(".note-input").addEventListener("input", (event) => { annotation.note = event.target.value; annotationChanged(card, false); });
    body.append(extras);
    card.append(head, body);
    return card;
  }

  function createTagField(trackKey, dimension, annotation) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "tag-field";
    const legend = document.createElement("legend");
    legend.textContent = dimension.name;
    const options = document.createElement("div");
    options.className = "option-list";
    const selected = new Set(annotation.selections[dimension.id] || []);

    dimension.options.forEach((option) => {
      const label = document.createElement("label");
      label.className = "tag-option";
      const input = document.createElement("input");
      input.type = dimension.mode === "single" ? "radio" : "checkbox";
      input.name = dimension.mode === "single" ? `${trackKey}-${dimension.id}` : `${trackKey}-${dimension.id}-${option.id}`;
      input.value = option.id;
      input.checked = selected.has(option.id);
      input.addEventListener("change", () => {
        const current = new Set(annotation.selections[dimension.id] || []);
        if (dimension.mode === "single") annotation.selections[dimension.id] = input.checked ? [option.id] : [];
        else {
          if (input.checked) current.add(option.id); else current.delete(option.id);
          annotation.selections[dimension.id] = [...current];
        }
        annotationChanged(fieldset.closest(".track-card"));
      });
      const text = document.createElement("span");
      text.textContent = option.label;
      label.append(input, text);
      options.append(label);
    });
    fieldset.append(legend, options);
    return fieldset;
  }

  function annotationChanged(card, rerenderCard = true) {
    updateProgress();
    saveDraftSoon();
    if (card && rerenderCard) card.classList.toggle("is-complete", isComplete(annotationFor(card.dataset.trackKey)));
  }

  function updateProgress() {
    const complete = state.files.filter((entry) => isComplete(annotationFor(entry.key))).length;
    const total = state.files.length;
    elements.progressLabel.textContent = `${complete} / ${total} 首已标注`;
    elements.progressFill.style.width = `${total ? (complete / total) * 100 : 0}%`;
    elements.exportButton.disabled = total === 0;
  }

  let saveTimer;
  function saveDraftSoon() {
    elements.draftStatus.textContent = "正在保存草稿…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraft, 250);
  }

  function saveDraft() {
    try {
      const annotationsByFile = state.files.length ? state.files.map((entry) => ({
        file: { name: entry.file.name, size: entry.file.size, relativePath: entry.relativePath },
        annotation: clone(annotationFor(entry.key)),
      })) : clone(state.importedTracks);
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        dimensions: state.dimensions,
        annotator: elements.annotatorInput.value,
        dataset: elements.datasetInput.value,
        annotationsByFile,
      }));
      elements.draftStatus.textContent = "草稿已保存在本机浏览器";
    } catch {
      elements.draftStatus.textContent = "草稿保存失败，请及时导出 JSON";
    }
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (!draft) return;
      if (Array.isArray(draft.dimensions) && draft.dimensions.length) state.dimensions = draft.dimensions;
      state.importedTracks = draft.annotationsByFile || [];
      setTimeout(() => {
        elements.annotatorInput.value = draft.annotator || "";
        elements.datasetInput.value = draft.dataset || "Flowset 个人审美样本";
      }, 0);
    } catch { localStorage.removeItem(STORAGE_KEY); }
  }

  function clearDraft() {
    if (!confirm("确定清空本机草稿和当前所有标签吗？音乐文件不会被删除。")) return;
    localStorage.removeItem(STORAGE_KEY);
    state.annotations = {};
    state.importedTracks = [];
    state.dimensions = clone(initialDimensions);
    elements.annotatorInput.value = "";
    elements.datasetInput.value = "Flowset 个人审美样本";
    renderDimensionEditor();
    renderTracks();
    updateProgress();
    showToast("草稿已清空");
  }

  function buildExport() {
    return {
      schemaVersion: SCHEMA_VERSION,
      app: { name: "Flowset 个人审美打标", version: "0.1.0" },
      exportedAt: new Date().toISOString(),
      annotator: { id: elements.annotatorInput.value.trim() || "anonymous" },
      dataset: { name: elements.datasetInput.value.trim() || "Flowset 个人审美样本", trackCount: state.files.length },
      dimensions: clone(state.dimensions),
      tracks: state.files.map((entry, index) => {
        const annotation = annotationFor(entry.key);
        return {
          order: index + 1,
          file: { name: entry.file.name, relativePath: entry.relativePath, size: entry.file.size, lastModified: entry.file.lastModified || null, type: entry.file.type || null },
          selections: state.dimensions.map((dimension) => {
            const ids = annotation.selections[dimension.id] || [];
            const labelsById = new Map(dimension.options.map((option) => [option.id, option.label]));
            return { dimensionId: dimension.id, dimension: dimension.name, optionIds: ids, labels: ids.map((id) => labelsById.get(id)).filter(Boolean) };
          }).filter((selection) => selection.optionIds.length),
          confidence: annotation.confidence ? Number(annotation.confidence) : null,
          note: annotation.note.trim() || null,
          completed: isComplete(annotation),
        };
      }),
      summary: {
        completedTracks: state.files.filter((entry) => isComplete(annotationFor(entry.key))).length,
        incompleteTracks: state.files.filter((entry) => !isComplete(annotationFor(entry.key))).length,
      },
    };
  }

  function exportJson() {
    const payload = buildExport();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const date = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = `${safeFilename(payload.dataset.name)}-${safeFilename(payload.annotator.id)}-${date}.json`;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast(`JSON 已生成：${payload.summary.completedTracks} 首已标注`);
  }

  async function importJson(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      if (payload.schemaVersion !== SCHEMA_VERSION || !Array.isArray(payload.dimensions) || !Array.isArray(payload.tracks)) throw new Error("schema");
      state.dimensions = clone(payload.dimensions);
      state.importedTracks = payload.tracks.map((track) => ({
        file: track.file,
        annotation: {
          selections: Object.fromEntries((track.selections || []).map((selection) => [selection.dimensionId, selection.optionIds || []])),
          confidence: track.confidence || "",
          note: track.note || "",
        },
      }));
      elements.annotatorInput.value = payload.annotator?.id === "anonymous" ? "" : payload.annotator?.id || "";
      elements.datasetInput.value = payload.dataset?.name || "Flowset 个人审美样本";
      applyImportedAnnotations();
      renderDimensionEditor();
      renderTracks();
      updateProgress();
      saveDraftSoon();
      showToast("标注 JSON 已导入；重新选择同一批音乐即可继续试听");
    } catch { showToast("无法导入：这不是有效的 Flowset 标注 JSON"); }
  }

  function applyImportedAnnotations() {
    if (!state.importedTracks.length || !state.files.length) return;
    const imported = new Map(state.importedTracks.map((track) => [importedTrackKey(track), track.annotation]));
    state.files.forEach((entry) => {
      const match = imported.get(`${entry.file.name}::${entry.file.size}`);
      if (match) state.annotations[entry.key] = clone(match);
    });
  }

  let toastTimer;
  function showToast(message) {
    elements.toast.textContent = message;
    elements.toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => elements.toast.classList.remove("is-visible"), 2600);
  }

  function stripExtension(name) { return name.replace(/\.[^.]+$/, ""); }
  function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character]); }
  function escapeAttribute(value) { return escapeHtml(value); }
})();
