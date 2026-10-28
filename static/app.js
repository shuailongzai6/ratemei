(() => {
  "use strict";

  document.addEventListener("submit", async (event) => {
    const form = event.target;
    if (form.matches("[data-delete-form]")) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      return;
    }
    if (!form.matches("[data-duel-form]")) return;
    event.preventDefault();
    const arena = document.getElementById("arena");
    if (arena.hasAttribute("data-busy")) return;

    const body = new FormData(form);
    const submitter = event.submitter;
    if (submitter?.name) body.append(submitter.name, submitter.value);
    arena.setAttribute("data-busy", "");
    arena.setAttribute("aria-busy", "true");
    arena.querySelector("[data-duel-error]").hidden = true;
    const buttons = arena.querySelectorAll("button");
    buttons.forEach((button) => { button.disabled = true; });
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        body,
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Request failed");
      const html = await response.text();
      const documentFragment = new DOMParser().parseFromString(html, "text/html");
      const nextArena = documentFragment.getElementById("arena");
      if (!nextArena) throw new Error("Missing arena");
      arena.replaceWith(nextArena);
      nextArena.focus({ preventScroll: true });
    } catch {
      arena.querySelector("[data-duel-error]").hidden = false;
      buttons.forEach((button) => { button.disabled = false; });
    } finally {
      window.clearTimeout(timeout);
      arena.removeAttribute("data-busy");
      arena.removeAttribute("aria-busy");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey ||
        event.target.closest("input, textarea, select, [contenteditable='true']")) return;
    const arena = document.getElementById("arena");
    if (!arena || arena.hasAttribute("data-busy")) return;
    let button;
    if (event.key === "ArrowLeft" || event.key === "1") button = arena.querySelector("[data-choice='left']");
    if (event.key === "ArrowRight" || event.key === "2") button = arena.querySelector("[data-choice='right']");
    if (event.key.toLowerCase() === "s") button = arena.querySelector("[data-skip]");
    if (button) {
      event.preventDefault();
      button.click();
    }
  });

  const dropzone = document.querySelector("[data-dropzone]");
  if (!dropzone) return;
  const input = dropzone.querySelector("input[type='file']");
  const preview = dropzone.querySelector("[data-upload-preview]");
  let previewUrl;

  function updatePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = input.files[0];
    const hasImage = Boolean(file && file.type.startsWith("image/"));
    preview.hidden = !hasImage;
    dropzone.toggleAttribute("data-has-image", hasImage);
    if (hasImage) {
      previewUrl = URL.createObjectURL(file);
      preview.querySelector("img").src = previewUrl;
    } else {
      preview.querySelector("img").removeAttribute("src");
    }
  }
  input.addEventListener("change", updatePreview);
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.setAttribute("data-dragging", "");
  });
  dropzone.addEventListener("dragleave", (event) => {
    if (!dropzone.contains(event.relatedTarget)) dropzone.removeAttribute("data-dragging");
  });
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.removeAttribute("data-dragging");
    if (!event.dataTransfer.files.length) return;
    const selection = new DataTransfer();
    selection.items.add(event.dataTransfer.files[0]);
    input.files = selection.files;
    updatePreview();
  });
})();
