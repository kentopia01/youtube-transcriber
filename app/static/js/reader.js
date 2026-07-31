const root = document.getElementById("reader-document");

if (root) {
  const transcriptDetails = document.getElementById("reader-transcript-details");
  const blocks = [...root.querySelectorAll(".reader-block")];
  const syncTranscriptState = () => {
    root.dataset.transcriptOpen = transcriptDetails?.open ? "true" : "false";
  };
  const openTranscript = () => {
    if (transcriptDetails && !transcriptDetails.open) transcriptDetails.open = true;
    syncTranscriptState();
  };
  if (location.hash) {
    let hashId = location.hash.slice(1);
    try { hashId = decodeURIComponent(hashId); } catch { /* keep the literal fragment */ }
    const hashTarget = document.getElementById(hashId);
    if (hashTarget && transcriptDetails?.contains(hashTarget)) transcriptDetails.open = true;
  }
  transcriptDetails?.addEventListener("toggle", syncTranscriptState);
  syncTranscriptState();
  const originalCopies = new Map(blocks.map(block => [block.id, block.querySelector(".reader-copy")?.textContent || ""]));
  const restoreCopies = () => blocks.forEach(block => {
    const copy = block.querySelector(".reader-copy");
    if (copy) copy.textContent = originalCopies.get(block.id) || "";
  });
  const settingsKey = "yt-reader-settings-v1";
  const defaultSettings = { theme: "paper", fontSize: "19", lineHeight: "1.75", contentWidth: "42", fontWeight: "400" };
  let settings;
  try { settings = { ...defaultSettings, ...JSON.parse(localStorage.getItem(settingsKey) || "{}") }; }
  catch { settings = { ...defaultSettings }; }

  const applySettings = () => {
    root.dataset.readerTheme = settings.theme;
    root.style.setProperty("--reader-font-size", settings.fontSize + "px");
    root.style.setProperty("--reader-line-height", settings.lineHeight);
    root.style.setProperty("--reader-width", settings.contentWidth + "rem");
    root.style.setProperty("--reader-weight", settings.fontWeight);
    root.querySelectorAll("[data-reader-theme]").forEach(button => button.classList.toggle("is-active", button.dataset.readerTheme === settings.theme));
    root.querySelectorAll("[data-setting]").forEach(control => { control.value = settings[control.dataset.setting]; });
  };
  applySettings();

  root.querySelectorAll("[data-reader-theme]").forEach(button => button.addEventListener("click", () => {
    settings.theme = button.dataset.readerTheme; localStorage.setItem(settingsKey, JSON.stringify(settings)); applySettings();
  }));
  root.querySelectorAll("[data-setting]").forEach(control => control.addEventListener("change", () => {
    settings[control.dataset.setting] = control.value; localStorage.setItem(settingsKey, JSON.stringify(settings)); applySettings();
  }));

  const tools = document.getElementById("reader-tools");
  root.querySelector("[data-open-tools]")?.addEventListener("click", () => tools.showModal());
  root.querySelector("[data-close-tools]")?.addEventListener("click", () => tools.close());

  const apiUrl = new URL(root.dataset.stateUrl, location.origin);
  const apiKey = new URLSearchParams(location.search).get("api_key");
  if (apiKey) apiUrl.searchParams.set("api_key", apiKey);
  const annotationCollectionUrl = new URL("/api/reader/videos/" + root.dataset.videoId + "/annotations", location.origin);
  if (apiKey) annotationCollectionUrl.searchParams.set("api_key", apiKey);
  const chapterUrl = new URL("/api/reader/videos/" + root.dataset.videoId + "/chapters", location.origin);
  if (apiKey) chapterUrl.searchParams.set("api_key", apiKey);
  const exportLink = root.querySelector('.reader-notebook-head a');
  if (apiKey && exportLink) exportLink.href += "?api_key=" + encodeURIComponent(apiKey);
  const saveStatus = document.getElementById("reader-save-status");
  let saveTimer;
  const saveState = async payload => {
    try {
      const response = await fetch(apiUrl, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error("HTTP " + response.status);
      saveStatus.textContent = payload.status === "finished" ? "Marked finished" : payload.status === "later" ? "Saved for later" : "Progress saved";
    } catch { saveStatus.textContent = "Progress could not be saved"; }
  };
  root.querySelectorAll("[data-reader-status]").forEach(button => button.addEventListener("click", () => saveState({ status: button.dataset.readerStatus })));
  root.querySelector("[data-generate-chapters]")?.addEventListener("click", async event => {
    const button = event.currentTarget; const status = document.getElementById("reader-chapter-status"); button.disabled = true; status.textContent = "Generating a grounded outline…";
    try {
      const response = await fetch(chapterUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "semantic" }) });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = await response.json(); const nav = document.getElementById("reader-outline-links"); nav.replaceChildren();
      payload.chapters.forEach(chapter => { const link = document.createElement("a"); link.href = "#" + chapter.anchor; const time = document.createElement("span"); const total = Math.floor(chapter.start_time); time.textContent = Math.floor(total / 60) + ":" + String(total % 60).padStart(2, "0"); link.append(time, document.createTextNode(chapter.title)); nav.append(link); });
      status.textContent = payload.provenance === "semantic" ? "Smart outline saved" : "Deterministic outline used; AI was unavailable";
    } catch { status.textContent = "Outline generation failed; the built-in outline remains available"; }
    finally { button.disabled = false; }
  });

  let currentIndex = Math.max(0, blocks.findIndex(block => block.id === root.dataset.resumeAnchor));
  const setCurrent = (index, persist = true) => {
    currentIndex = Math.max(0, Math.min(blocks.length - 1, index));
    blocks.forEach((block, blockIndex) => block.classList.toggle("is-current", blockIndex === currentIndex));
    const progress = blocks.length < 2 ? 100 : Math.round(currentIndex / (blocks.length - 1) * 1000) / 10;
    document.getElementById("reader-progress-bar").style.width = progress + "%";
    root.querySelector(".reader-progress")?.setAttribute("aria-valuenow", String(Math.round(progress)));
    if (persist) {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => saveState({ status: "reading", progress_pct: progress, last_block_anchor: blocks[currentIndex].id, last_timestamp_seconds: Number(blocks[currentIndex].dataset.start) }), 700);
    }
  };
  setCurrent(currentIndex, false);
  if (transcriptDetails?.open && root.dataset.resumeAnchor && !location.hash) {
    requestAnimationFrame(() => document.getElementById(root.dataset.resumeAnchor)?.scrollIntoView({ block: "center" }));
  }
  const observer = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => Math.abs(a.boundingClientRect.top) - Math.abs(b.boundingClientRect.top));
    if (visible[0]) setCurrent(blocks.indexOf(visible[0].target));
  }, { rootMargin: "-20% 0px -60% 0px", threshold: 0 });
  blocks.forEach(block => observer.observe(block));

  const search = document.getElementById("reader-search");
  const searchStatus = document.getElementById("reader-search-status");
  let matches = []; let matchIndex = -1;
  const runSearch = () => {
    restoreCopies(); matches = []; matchIndex = -1;
    const query = search.value.trim();
    if (!query) { searchStatus.textContent = "Type to find a passage"; renderAnnotationMarks(); return; }
    openTranscript();
    root.querySelectorAll(".reader-copy").forEach(copy => {
      const text = copy.textContent; const lower = text.toLowerCase(); const needle = query.toLowerCase(); let cursor = 0; let found;
      const fragment = document.createDocumentFragment();
      while ((found = lower.indexOf(needle, cursor)) !== -1) {
        fragment.append(document.createTextNode(text.slice(cursor, found)));
        const mark = document.createElement("mark"); mark.className = "reader-search-mark"; mark.textContent = text.slice(found, found + query.length); fragment.append(mark); matches.push(mark); cursor = found + query.length;
      }
      if (cursor) { fragment.append(document.createTextNode(text.slice(cursor))); copy.replaceChildren(fragment); }
    });
    searchStatus.textContent = matches.length ? matches.length + " matches" : "No matches";
    if (matches.length) showMatch(0);
  };
  const showMatch = index => {
    if (!matches.length) return; matchIndex = (index + matches.length) % matches.length;
    openTranscript();
    matches.forEach((mark, i) => mark.classList.toggle("is-active", i === matchIndex));
    matches[matchIndex].scrollIntoView({ block: "center" }); searchStatus.textContent = (matchIndex + 1) + " of " + matches.length + " matches";
  };
  search.addEventListener("input", runSearch);
  search.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); showMatch(matchIndex + (event.shiftKey ? -1 : 1)); } });
  root.querySelector("[data-search-next]")?.addEventListener("click", () => showMatch(matchIndex + 1));

  const annotationList = document.getElementById("reader-annotation-list");
  const selectionTools = document.getElementById("reader-selection-tools");
  const noteDialog = document.getElementById("reader-note-dialog");
  const noteText = document.getElementById("reader-note-text");
  let annotations = []; let pendingSelection = null;
  const renderAnnotationMarks = () => {
    restoreCopies();
    const grouped = new Map();
    annotations.filter(item => item.annotation_type !== "bookmark" && item.block_anchor).forEach(item => {
      if (!grouped.has(item.block_anchor)) grouped.set(item.block_anchor, []);
      grouped.get(item.block_anchor).push(item);
    });
    grouped.forEach((items, anchor) => {
      const block = document.getElementById(anchor); const copy = block?.querySelector(".reader-copy");
      if (!copy) return;
      const text = originalCopies.get(anchor) || ""; let cursor = 0; const fragment = document.createDocumentFragment();
      items.sort((a, b) => a.start_offset - b.start_offset).forEach(item => {
        const start = Math.max(cursor, Math.min(text.length, item.start_offset));
        const end = Math.max(start, Math.min(text.length, item.end_offset));
        if (end <= start) return;
        fragment.append(document.createTextNode(text.slice(cursor, start)));
        const mark = document.createElement("mark"); mark.className = "reader-annotation-mark reader-annotation-" + item.annotation_type; mark.textContent = text.slice(start, end); if (item.note_text) mark.title = item.note_text; fragment.append(mark); cursor = end;
      });
      fragment.append(document.createTextNode(text.slice(cursor))); copy.replaceChildren(fragment);
    });
  };
  const renderAnnotations = () => {
    annotationList.replaceChildren();
    blocks.forEach(block => block.classList.remove("has-annotation"));
    if (!annotations.length) { restoreCopies(); const empty = document.createElement("p"); empty.className = "reader-tool-status"; empty.textContent = "No saved passages in this transcript"; annotationList.append(empty); return; }
    annotations.forEach(annotation => {
      const item = document.createElement("article"); item.className = "reader-annotation-item";
      const label = document.createElement("strong"); label.textContent = annotation.annotation_type + " · " + Math.floor(annotation.start_timestamp_seconds / 60) + ":" + String(Math.floor(annotation.start_timestamp_seconds % 60)).padStart(2, "0");
      const copy = document.createElement("p"); copy.textContent = annotation.note_text || annotation.selected_text_snapshot || "Bookmark";
      const jump = document.createElement("button"); jump.type = "button"; jump.textContent = "Jump to passage"; jump.addEventListener("click", () => { openTranscript(); document.getElementById(annotation.block_anchor)?.scrollIntoView({ block: "center" }); });
      const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "Delete"; remove.addEventListener("click", async () => {
        const url = new URL("/api/reader/annotations/" + annotation.id, location.origin); if (apiKey) url.searchParams.set("api_key", apiKey);
        const response = await fetch(url, { method: "DELETE" }); if (response.ok) { annotations = annotations.filter(value => value.id !== annotation.id); renderAnnotations(); }
      });
      item.append(label, copy, jump, remove); annotationList.append(item); document.getElementById(annotation.block_anchor)?.classList.add("has-annotation");
    });
    if (!search.value.trim()) renderAnnotationMarks();
  };
  const loadAnnotations = async () => {
    try { const response = await fetch(annotationCollectionUrl); if (response.ok) annotations = await response.json(); }
    finally { renderAnnotations(); }
  };
  loadAnnotations();

  const createAnnotation = async (type, selection, note = null) => {
    const payload = { annotation_type: type, block_anchor: selection.block.id, start_timestamp_seconds: Number(selection.block.dataset.start), end_timestamp_seconds: Number(selection.block.dataset.start), start_offset: selection.startOffset, end_offset: selection.endOffset, selected_text_snapshot: selection.text, note_text: note };
    const response = await fetch(annotationCollectionUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) { saveStatus.textContent = "Annotation could not be saved"; return; }
    annotations.push(await response.json()); renderAnnotations(); saveStatus.textContent = type === "note" ? "Note saved" : type === "bookmark" ? "Passage bookmarked" : "Highlight saved"; window.getSelection()?.removeAllRanges(); selectionTools.hidden = true;
  };
  root.querySelector("[data-bookmark-current]")?.addEventListener("click", () => createAnnotation("bookmark", { block: blocks[currentIndex], startOffset: 0, endOffset: 0, text: "" }));
  document.addEventListener("selectionchange", () => {
    const selection = window.getSelection(); const text = selection?.toString().trim();
    if (!text || selection.rangeCount < 1) { selectionTools.hidden = true; return; }
    const range = selection.getRangeAt(0); const copy = range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentElement?.closest(".reader-copy") : range.commonAncestorContainer.closest?.(".reader-copy");
    if (!copy) { selectionTools.hidden = true; return; }
    const block = copy.closest(".reader-block"); const full = copy.textContent; const startOffset = Math.max(0, full.indexOf(text));
    pendingSelection = { block, startOffset, endOffset: startOffset + text.length, text };
    const rect = range.getBoundingClientRect(); selectionTools.hidden = false; selectionTools.style.left = Math.max(8, Math.min(innerWidth - selectionTools.offsetWidth - 8, rect.left)) + "px"; selectionTools.style.top = Math.max(70, rect.top - selectionTools.offsetHeight - 8) + "px";
  });
  selectionTools.querySelector('[data-create-annotation="highlight"]')?.addEventListener("click", () => pendingSelection && createAnnotation("highlight", pendingSelection));
  selectionTools.querySelector('[data-create-annotation="note"]')?.addEventListener("click", () => { if (!pendingSelection) return; document.getElementById("reader-note-selection").textContent = pendingSelection.text; noteText.value = ""; noteDialog.showModal(); noteText.focus(); });
  selectionTools.querySelectorAll("[data-selection-research]").forEach(button => button.addEventListener("click", () => {
    if (!pendingSelection) return;
    const params = new URLSearchParams({ video_id: root.dataset.videoId, action: button.dataset.selectionResearch, selection: pendingSelection.text });
    location.href = "/chat?" + params.toString();
  }));
  noteDialog.querySelector("[data-save-note]")?.addEventListener("click", event => { event.preventDefault(); if (!noteText.value.trim() || !pendingSelection) return; noteDialog.close(); createAnnotation("note", pendingSelection, noteText.value.trim()); });

  document.addEventListener("keydown", event => {
    if (event.key === "/" && document.activeElement !== search) { event.preventDefault(); openTranscript(); if (innerWidth < 1024 && !tools.open) tools.showModal(); search.focus(); }
    if (event.target.matches("input, select, textarea")) return;
    if (event.key.toLowerCase() === "j") { openTranscript(); blocks[Math.min(blocks.length - 1, currentIndex + 1)]?.scrollIntoView({ block: "center" }); }
    if (event.key.toLowerCase() === "k") { openTranscript(); blocks[Math.max(0, currentIndex - 1)]?.scrollIntoView({ block: "center" }); }
  });
}
