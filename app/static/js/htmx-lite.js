(function () {
  const processed = new WeakSet();

  const emit = (element, name, detail = {}) =>
    element.dispatchEvent(new CustomEvent(name, { bubbles: true, detail }));

  function targetFor(element) {
    const selector = element.getAttribute("hx-target");
    return selector ? document.querySelector(selector) : element;
  }

  function valuesFor(element, event) {
    const form = element.tagName === "FORM" ? element : element.closest("form");
    const data = new FormData(form || undefined);
    if (!form && element.name) data.set(element.name, element.value);

    const include = element.getAttribute("hx-include");
    if (include) {
      document.querySelectorAll(include).forEach(node => {
        if (node.name && !node.disabled) data.set(node.name, node.value);
        node.querySelectorAll?.("[name]").forEach(field => {
          if (!field.disabled) data.set(field.name, field.value);
        });
      });
    }

    const raw = element.getAttribute("hx-vals");
    if (raw) {
      try {
        const expression = raw.startsWith("js:") ? raw.slice(3) : raw;
        const extra = raw.startsWith("js:")
          ? Function("event", "return (" + expression + ")")(event)
          : JSON.parse(expression);
        Object.entries(extra).forEach(([key, value]) => data.set(key, String(value)));
      } catch (_error) {
        // Invalid declarative values are ignored, matching progressive enhancement.
      }
    }
    return data;
  }

  function selectedHtml(html, selector) {
    if (!selector) return html;
    const documentFragment = new DOMParser().parseFromString(html, "text/html");
    return documentFragment.querySelector(selector)?.innerHTML ?? html;
  }

  async function request(element, method, requestUrl, supplied, event) {
    if (element.getAttribute("hx-confirm") && !confirm(element.getAttribute("hx-confirm"))) return;

    const indicator = document.querySelector(element.getAttribute("hx-indicator"));
    indicator?.classList.add("htmx-request");
    emit(element, "htmx:beforeRequest");

    const headers = { "HX-Request": "true" };
    try { Object.assign(headers, JSON.parse(element.getAttribute("hx-headers") || "{}")); }
    catch (_error) { /* Invalid declarative headers are ignored. */ }

    const data = supplied ? new URLSearchParams(supplied) : valuesFor(element, event);
    const options = { method, headers };
    let url = requestUrl;
    if (method === "GET") {
      const query = new URLSearchParams(data);
      if ([...query].length) {
        const parsed = new URL(url, window.location.origin);
        query.forEach((value, key) => parsed.searchParams.set(key, value));
        url = parsed.toString();
      }
    } else if ((headers["Content-Type"] || "").includes("application/json")) {
      const payload = Object.fromEntries(
        [...data.entries()].map(([key, value]) => [
          key,
          value === "true" ? true : value === "false" ? false : value,
        ]),
      );
      options.body = JSON.stringify(payload);
    } else {
      options.body = new URLSearchParams(data);
      headers["Content-Type"] = "application/x-www-form-urlencoded;charset=UTF-8";
    }

    try {
      const response = await fetch(url, options);
      const responseText = await response.text();
      const target = targetFor(element);
      const swap = element.getAttribute("hx-swap") || "innerHTML";
      const html = selectedHtml(responseText, element.getAttribute("hx-select"));
      if (target && swap !== "none") {
        if (swap === "outerHTML") target.outerHTML = html;
        else if (swap === "beforeend") target.insertAdjacentHTML("beforeend", html);
        else target.innerHTML = html;
        process(document);
      }
      if (element.getAttribute("hx-push-url") === "true") {
        history.pushState({}, "", response.url);
      }
      const detail = {
        successful: response.ok,
        xhr: { status: response.status, responseText, responseURL: response.url },
      };
      emit(element, "htmx:afterRequest", detail);
      const handler = element.getAttribute("hx-on::after-request");
      if (handler) Function("event", handler).call(element, { target: element, detail });
    } catch (error) {
      emit(element, "htmx:afterRequest", { successful: false, error });
    } finally {
      indicator?.classList.remove("htmx-request");
    }
  }

  function bind(element) {
    if (processed.has(element)) return;
    processed.add(element);
    const method = ["get", "post", "patch", "delete"].find(name => element.hasAttribute("hx-" + name));
    if (!method) return;
    const url = element.getAttribute("hx-" + method);
    const declaredTrigger = element.getAttribute("hx-trigger");
    if (declaredTrigger !== null && !declaredTrigger.trim()) return;
    const trigger = declaredTrigger || (element.tagName === "FORM" ? "submit" : "click");
    const run = event => { event?.preventDefault(); request(element, method.toUpperCase(), url, null, event); };

    if (trigger.startsWith("load")) {
      const delay = /delay:(\d+(?:\.\d+)?)s/.exec(trigger);
      setTimeout(run, delay ? Number(delay[1]) * 1000 : 0);
      return;
    }
    if (trigger.includes("keyup")) {
      let timer;
      let previous = element.value;
      element.addEventListener("keyup", event => {
        if (trigger.includes("changed") && element.value === previous) return;
        previous = element.value;
        clearTimeout(timer);
        const delay = /delay:(\d+)ms/.exec(trigger);
        timer = setTimeout(() => run(event), delay ? Number(delay[1]) : 0);
      });
      return;
    }
    element.addEventListener(
      trigger.includes("change") ? "change" : trigger.includes("submit") ? "submit" : "click",
      run,
    );
  }

  function process(root) {
    root.querySelectorAll?.("[hx-get],[hx-post],[hx-patch],[hx-delete]").forEach(bind);
  }

  window.htmx = {
    process,
    ajax(method, url, options = {}) {
      const proxy = document.createElement("div");
      if (options.target) proxy.setAttribute("hx-target", options.target);
      if (options.swap) proxy.setAttribute("hx-swap", options.swap);
      return request(proxy, method.toUpperCase(), url, options.values);
    },
  };
  document.addEventListener("DOMContentLoaded", () => process(document));
})();
