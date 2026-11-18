"use strict";
/* Presentation only. No effect on bot state, trace reproducibility or network traffic. */
(function () {
  const key = "pybot-live-lab:theme";
  const button = document.getElementById("themeToggle");
  const meta = document.querySelector('meta[name="theme-color"]');
  if (!button) return;
  let stored = null;
  try {
    const candidate = window.localStorage.getItem(key);
    if (candidate === "light" || candidate === "dark") stored = candidate;
  } catch (_) {
    // Privacy settings may disable localStorage; switching still works for this tab.
  }
  const media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  function preferred() {
    return media && media.matches ? "light" : "dark";
  }
  function apply(next) {
    const mode = next === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", mode);
    document.documentElement.style.colorScheme = mode;
    const toLight = mode === "dark";
    button.textContent = toLight ? "☀ ライトへ" : "☾ ダークへ";
    button.setAttribute("aria-label", toLight ? "ライトモードに切り替える" : "ダークモードに切り替える");
    button.setAttribute("title", toLight ? "ライトモードに切り替える" : "ダークモードに切り替える");
    button.setAttribute("aria-pressed", mode === "light" ? "true" : "false");
    if (meta) meta.setAttribute("content", mode === "light" ? "#f3f8f9" : "#0a1322");
  }
  apply(stored || preferred());
  button.addEventListener("click", function () {
    stored = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    apply(stored);
    try { window.localStorage.setItem(key, stored); } catch (_) {}
  });
  if (media) {
    const onMediaChange = function () { if (!stored) apply(preferred()); };
    if (typeof media.addEventListener === "function") media.addEventListener("change", onMediaChange);
    else if (typeof media.addListener === "function") media.addListener(onMediaChange);
  }
})();
