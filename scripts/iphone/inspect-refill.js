/* Shortcuts: Run JavaScript on Web Page. Read-only; no network or clicks. */
(() => {
  const host = location.hostname.toLowerCase();
  if (!["alditalk-kundenportal.de", "www.alditalk-kundenportal.de"].includes(host)) {
    completion(JSON.stringify({version: 1, status: "wrong_page"}));
    return;
  }
  const roots = [document];
  const candidates = [];
  let elements = 0;
  let shadowRoots = 0;
  let truncated = false;
  for (let index = 0; index < roots.length; index++) {
    for (const node of roots[index].querySelectorAll("*")) {
      if (++elements > 30000) { truncated = true; break; }
      if (node.shadowRoot) { roots.push(node.shadowRoot); shadowRoots++; }
      if (!node.matches("button,a,input[type=button],input[type=submit],[role=button]")) continue;
      const label = (node.innerText || node.value || node.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim();
      if (!/(?:\+\s*1\s*GB|\b1\s*GB\b|nachbuch)/i.test(label)) continue;
      const rect = node.getBoundingClientRect();
      candidates.push({
        tag: node.tagName.toLowerCase(),
        label_kind: /\+\s*1\s*GB/i.test(label) ? "plus_one_gb" : "refill_related",
        visible: rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== "hidden",
        disabled: node.matches(":disabled") || node.getAttribute("aria-disabled") === "true" || node.hasAttribute("inert"),
        has_link: node.hasAttribute("href"),
        has_inline_handler: node.hasAttribute("onclick"),
        inside_form: Boolean(node.closest("form")),
        inside_shadow_root: node.getRootNode() !== document
      });
    }
    if (truncated) break;
  }
  const report = {
    version: 1,
    status: "inspection_only",
    ready: document.readyState === "complete",
    candidate_count: candidates.length,
    candidates: candidates.slice(0, 20),
    shadow_roots: shadowRoots,
    frame_count: document.querySelectorAll("iframe").length,
    truncated,
    provider_action: false
  };
  completion(JSON.stringify(report, null, 2));
})();
