(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const readJSON = (id) => {
    const el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  };
  // Persian pages show Persian digits; English pages are left alone.
  const FA = document.documentElement.lang === "fa";
  const n = (v) => (FA ? String(v).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]).replace(".", "٫") : String(v));
  const pct = (v) => n(v) + (FA ? "٪" : "%");
  const IMAGE_EXT = ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"];
  const VIDEO_EXT = ["mp4", "mov", "mkv", "webm", "avi", "m4v"];

  // Widths that come from the server (CSP forbids inline style attributes).
  $$("[data-width]").forEach((el) => { el.style.width = Math.min(100, parseFloat(el.dataset.width) || 0) + "%"; });

  // Mobile menu
  const toggle = $("[data-nav-toggle]");
  if (toggle) toggle.addEventListener("click", () => $("[data-nav]").classList.toggle("open"));

  // Confirmation for dangerous forms
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => { if (!confirm(form.dataset.confirm)) e.preventDefault(); });
  });

  // Copy referral link
  $$("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = $("[data-copy-source]");
      input.select();
      try { await navigator.clipboard.writeText(input.value); } catch (e) { document.execCommand("copy"); }
      const old = btn.textContent;
      btn.textContent = btn.dataset.copiedText;
      setTimeout(() => { btn.textContent = old; }, 1500);
    });
  });

  // ------------------------------------------------------------------ upload form
  const form = $("#job-form");
  if (form) initUploadForm(form);

  function initUploadForm(form) {
    const prices = readJSON("prices");
    const text = readJSON("i18n-dashboard");
    const input = $("#file-input");
    const dropzone = $("[data-dropzone]");
    const fpsToggle = $("[data-video-only]");
    const costBox = $("[data-cost]");
    const costValue = $("[data-cost-value]");
    const costNote = $("[data-cost-note]");
    const submit = $("[data-submit]");
    const errorBox = $("[data-form-error]");
    let mediaType = null;
    let duration = 0;
    let previewUrl = null;

    const ext = (name) => (name.split(".").pop() || "").toLowerCase();
    const formatSize = (b) => (b > 1048576 ? n((b / 1048576).toFixed(1)) + " MB" : n(Math.ceil(b / 1024)) + " KB");

    function showError(msg) {
      errorBox.textContent = msg;
      errorBox.hidden = !msg;
    }

    function updateCost() {
      const fpsInput = $("input[name=fps_boost]");
      fpsToggle.classList.toggle("disabled", mediaType === "image");
      fpsInput.disabled = mediaType === "image";
      if (!mediaType) { costValue.textContent = "—"; costNote.textContent = ""; return; }
      const high = $("input[name=quality]:checked").value === "high";
      const x4 = $("input[name=scale]:checked").value === "4";
      const face = $("input[name=face_enhance]").checked;
      const fps = fpsInput.checked && mediaType === "video";
      const p = prices[mediaType];
      let cost;
      if (mediaType === "image") {
        cost = (high ? p.high : p.fast) + (x4 ? p.x4 : 0) + (face ? p.face : 0);
        costNote.textContent = "";
      } else {
        const units = Math.max(1, Math.ceil(duration / 10));
        cost = ((high ? p.high : p.fast) + (x4 ? p.x4 : 0) + (face ? p.face : 0) + (fps ? p.fps : 0)) * units;
        costNote.textContent = duration ? text.perUnits.replace("%s", n(units)) : "";
      }
      costValue.textContent = n(cost);
      const tooExpensive = cost > prices.coins;
      costBox.classList.toggle("insufficient", tooExpensive);
      showError(tooExpensive ? text.notEnough : "");
    }

    function setFile(file) {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      const e = ext(file.name);
      mediaType = IMAGE_EXT.includes(e) ? "image" : VIDEO_EXT.includes(e) ? "video" : null;
      duration = 0;
      $("[data-dz-empty]").hidden = true;
      $("[data-dz-file]").hidden = false;
      $("[data-dz-name]").textContent = file.name;
      const meta = $("[data-dz-meta]");
      meta.textContent = formatSize(file.size);
      const box = $("[data-dz-preview]");
      box.textContent = "";
      previewUrl = URL.createObjectURL(file);
      if (mediaType === "image") {
        const img = new Image();
        img.onload = () => { meta.textContent = formatSize(file.size) + " · " + n(img.naturalWidth) + "×" + n(img.naturalHeight); };
        img.src = previewUrl;
        box.appendChild(img);
      } else if (mediaType === "video") {
        const v = document.createElement("video");
        v.muted = true;
        v.preload = "metadata";
        v.onloadedmetadata = () => {
          duration = v.duration || 0;
          meta.textContent = formatSize(file.size) + " · " + n(v.videoWidth) + "×" + n(v.videoHeight) + " · " + n(Math.round(duration)) + " " + text.seconds;
          updateCost();
        };
        v.src = previewUrl;
        box.appendChild(v);
      }
      updateCost();
    }

    input.addEventListener("change", () => { if (input.files[0]) setFile(input.files[0]); });
    ["dragenter", "dragover"].forEach((ev) => dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); }));
    ["dragleave", "drop"].forEach((ev) => dropzone.addEventListener(ev, () => dropzone.classList.remove("drag")));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        setFile(input.files[0]);
      }
    });
    $$("input[name=quality], input[name=scale], input[name=face_enhance], input[name=fps_boost]", form)
      .forEach((el) => el.addEventListener("change", updateCost));
    updateCost();

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!input.files.length) { showError(text.chooseFile); return; }
      showError("");
      submit.disabled = true;
      const progress = $("[data-upload-progress]");
      const bar = $("[data-upload-bar]");
      const label = $("[data-upload-text]");
      progress.hidden = false;

      const xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
      xhr.upload.addEventListener("progress", (ev) => {
        if (!ev.lengthComputable) return;
        const done = Math.round((ev.loaded / ev.total) * 100);
        bar.style.width = done + "%";
        label.textContent = done < 100 ? text.uploading.replace("%s%", pct(done)).replace("%s", n(done)) : text.processing;
      });
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (err) { /* not JSON */ }
        if (data && data.ok) { window.location.href = data.redirect; return; }
        progress.hidden = true;
        submit.disabled = false;
        showError((data && data.error) || text.failed);
      };
      xhr.onerror = () => { progress.hidden = true; submit.disabled = false; showError(text.failed); };
      xhr.send(new FormData(form));
    });
  }

  // ------------------------------------------------------------------ job status polling
  const statusBox = $("[data-job-status-url]");
  if (statusBox) {
    const url = statusBox.dataset.jobStatusUrl;
    const formatTime = (s) => {
      const m = Math.floor(s / 60), sec = s % 60, h = Math.floor(m / 60);
      return n(h ? h + ":" + String(m % 60).padStart(2, "0") + ":" + String(sec).padStart(2, "0") : m + ":" + String(sec).padStart(2, "0"));
    };
    const poll = async () => {
      try {
        const res = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, cache: "no-store" });
        if (!res.ok) throw new Error(res.status);
        const s = await res.json();
        if (s.finished) { window.location.reload(); return; }
        $("[data-progress-bar]").style.width = s.progress + "%";
        $("[data-progress-text]").textContent = pct(s.progress);
        $("[data-stage]").textContent = s.stage || s.status_display;
        $("[data-status-badge]").textContent = s.status_display;
        $("[data-status-badge]").className = "badge badge-lg badge-" + s.status;
        const q = $("[data-queue]");
        q.hidden = !s.queue_position;
        $("[data-queue-pos]").textContent = n(s.queue_position);
        const eta = $("[data-eta]");
        eta.hidden = s.eta_seconds == null;
        if (s.eta_seconds != null) $("[data-eta-value]").textContent = formatTime(s.eta_seconds);
      } catch (e) { /* network hiccup, try again */ }
      setTimeout(poll, 2000);
    };
    setTimeout(poll, 1500);
  }

  // ------------------------------------------------------------------ before / after slider
  $$("[data-compare]").forEach((box) => {
    const after = $("[data-compare-after]", box);
    const handle = $("[data-compare-handle]", box);
    const range = $("[data-compare-range]", box);
    const set = (v) => {
      after.style.clipPath = "inset(0 0 0 " + v + "%)";
      handle.style.left = v + "%";
    };
    range.addEventListener("input", () => set(range.value));
    set(range.value);
  });
})();
