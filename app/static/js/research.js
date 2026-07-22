const form = document.getElementById("research-search-form");

if (form) {
  const scope = document.getElementById("research-scope");
  const channel = document.getElementById("research-channel");
  const video = document.getElementById("research-video-id");
  const results = document.getElementById("search-results");
  const query = document.getElementById("search-query");

  const applyScope = () => {
    channel.disabled = scope.value !== "channel";
    if (video) video.disabled = scope.value !== "video";
  };
  scope.addEventListener("change", applyScope);
  applyScope();

  form.addEventListener("htmx:beforeRequest", () => {
    results.setAttribute("aria-busy", "true");
  });
  form.addEventListener("htmx:afterRequest", () => {
    results.setAttribute("aria-busy", "false");
  });

  const initial = new URLSearchParams(window.location.search).get("q");
  if (initial) {
    query.value = initial;
    form.requestSubmit();
  }
}
