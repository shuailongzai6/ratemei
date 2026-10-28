(() => {
  "use strict";

  const announcer = document.querySelector("[data-announcer]");
  const wait = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  function announce(message) {
    announcer.textContent = "";
    window.requestAnimationFrame(() => { announcer.textContent = message; });
  }

  // Fetch and decode the next pair before showing it, so it appears fully painted.
  function preload(arena) {
    return Promise.all([...arena.querySelectorAll(".pick img")].map((img) => {
      const image = new Image();
      image.src = img.getAttribute("src");
      return image.decode().catch(() => {});
    }));
  }

  async function submitRound(form, submitter) {
    const arena = form.closest("#arena");
    if (arena.hasAttribute("aria-busy")) return;
    const body = new FormData(form);
    if (submitter?.name) body.append(submitter.name, submitter.value);
    const picked = submitter?.matches(".pick");
    const error = arena.querySelector("[data-duel-error]");
    const buttons = arena.querySelectorAll("button");
    arena.setAttribute("aria-busy", "true");
    if (picked) submitter.setAttribute("data-picked", "");
    error.hidden = true;
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
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const html = await response.text();
      const next = new DOMParser().parseFromString(html, "text/html").getElementById("arena");
      if (!next) throw new Error("Missing arena");
      // Give the chosen card a moment to show its check mark, but never wait long on images.
      await Promise.all([Promise.race([preload(next), wait(4000)]), wait(picked ? 350 : 0)]);
      next.setAttribute("data-enter", "");
      arena.replaceWith(next);
      next.focus({ preventScroll: true });
      announce(next.querySelector("[data-status]")?.textContent.trim() ?? "");
    } catch {
      arena.removeAttribute("aria-busy");
      submitter?.removeAttribute("data-picked");
      buttons.forEach((button) => { button.disabled = false; });
      error.hidden = false;
      announce(error.textContent.trim());
    } finally {
      window.clearTimeout(timeout);
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.matches("[data-confirm]") && !window.confirm(form.dataset.confirm)) {
      event.preventDefault();
    } else if (form.matches("[data-duel-form]")) {
      event.preventDefault();
      submitRound(form, event.submitter);
    }
  });

  const shortcuts = { ArrowLeft: "left", 1: "left", ArrowRight: "right", 2: "right" };
  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey ||
        event.target.closest("input, textarea, select, [contenteditable='true']")) return;
    const arena = document.getElementById("arena");
    if (!arena || arena.hasAttribute("aria-busy")) return;
    const side = shortcuts[event.key];
    const button = side ? arena.querySelector(`[data-choice='${side}']`)
      : event.key.toLowerCase() === "s" && arena.querySelector("[data-skip]");
    if (button) {
      event.preventDefault();
      button.click();
    }
  });

  const dropzone = document.querySelector("[data-dropzone]");
  if (!dropzone) return;
  const form = dropzone.closest("form");
  const input = dropzone.querySelector("input[type='file']");
  const preview = dropzone.querySelector("[data-preview]");
  const fileName = dropzone.querySelector("[data-file-name]");
  const submit = form.querySelector("[type='submit']");
  let previewUrl;
  let selection = 0;

  // Shrink the photo to the 1600px the server keeps anyway, so phones upload far less. Re-encoding
  // through a canvas also leaves location and camera metadata on the device. Throws if undecodable.
  async function downscale(image, name) {
    await image.decode();
    const scale = Math.min(1, 1600 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(image.naturalWidth * scale);
    canvas.height = Math.round(image.naturalHeight * scale);
    const context = canvas.getContext("2d");
    context.fillStyle = "#fff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
    return blob && new File([blob], `${name.replace(/\.[^.]*$/, "")}.jpg`, { type: "image/jpeg" });
  }

  function setBusy(busy) {
    form.toggleAttribute("aria-busy", busy);
    submit.disabled = busy;
  }

  function showPreview(visible) {
    dropzone.toggleAttribute("data-has-image", visible);
    preview.hidden = !visible;
  }

  input.addEventListener("change", async () => {
    const current = ++selection;
    const file = input.files[0];
    URL.revokeObjectURL(previewUrl);
    showPreview(false);
    fileName.textContent = file?.name ?? "";
    fileName.hidden = !file;
    if (!file) return setBusy(false);
    previewUrl = URL.createObjectURL(file);
    preview.src = previewUrl;
    setBusy(true);
    try {
      const smaller = await downscale(preview, file.name);
      if (current !== selection) return;
      showPreview(true);
      if (smaller) {
        const files = new DataTransfer();
        files.items.add(smaller);
        input.files = files.files;
      }
    } catch {
      // The browser cannot read this file: send it as is, the server explains what went wrong.
    } finally {
      if (current === selection) setBusy(false);
    }
  });
  dropzone.addEventListener("dragenter", () => dropzone.setAttribute("data-dragging", ""));
  dropzone.addEventListener("dragleave", (event) => {
    if (!dropzone.contains(event.relatedTarget)) dropzone.removeAttribute("data-dragging");
  });
  dropzone.addEventListener("drop", () => dropzone.removeAttribute("data-dragging"));
  form.addEventListener("submit", () => setBusy(true));
  window.addEventListener("pageshow", () => setBusy(false));
})();
