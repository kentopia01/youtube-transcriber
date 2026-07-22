window.marked = {
  setOptions() {},
  parse(value) {
    return String(value || "")
      .replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm, "<h2>$1</h2>")
      .replace(/^# (.+)$/gm, "<h1>$1</h1>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .split(/\n{2,}/).map(block => /^<h[1-3]>/.test(block) ? block : "<p>" + block.replace(/\n/g, "<br>") + "</p>").join("");
  }
};
