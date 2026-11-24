(function () {
  const panel = document.querySelector('[data-placement]');
  if (!panel) return;

  const canvas = panel.querySelector('[data-canvas]');
  const palette = panel.querySelector('[data-palette]');
  const status = panel.querySelector('[data-placement-status]');
  const resultUrl = panel.dataset.resultImage;
  const DEFAULT_SCALE = 0.18;
  let items = [];

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function position(el) {
    el.style.left = (parseFloat(el.dataset.rx) * 100) + '%';
    el.style.top = (parseFloat(el.dataset.ry) * 100) + '%';
    el.style.width = (parseFloat(el.dataset.scale) * 100) + '%';
  }

  function refreshHint() {
    canvas.classList.toggle('has-items', items.length > 0);
  }

  function ready(img) {
    if (img.complete && img.naturalWidth) return Promise.resolve(img);
    return new Promise((resolve, reject) => {
      img.addEventListener('load', () => resolve(img), { once: true });
      img.addEventListener('error', () => reject(img), { once: true });
    });
  }

  function addItem(src, rx, ry, name) {
    const el = document.createElement('div');
    el.className = 'placed-item';
    el.dataset.src = src;
    el.dataset.name = name || 'Furniture';
    el.dataset.rx = rx;
    el.dataset.ry = ry;
    el.dataset.scale = DEFAULT_SCALE;

    const img = document.createElement('img');
    img.src = src;
    img.alt = el.dataset.name;
    img.draggable = false;
    el._image = img;

    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'remove';
    remove.textContent = '\u00d7';
    remove.setAttribute('aria-label', 'Remove ' + el.dataset.name);
    remove.addEventListener('click', e => {
      e.stopPropagation();
      el.remove();
      items = items.filter(x => x !== el);
      refreshHint();
    });

    el.appendChild(img);
    el.appendChild(remove);
    canvas.appendChild(el);
    items.push(el);
    position(el);
    attachMove(el);
    refreshHint();
    return el;
  }

  // Restore an arrangement saved earlier via POST /design/<id>/placement.
  function restore(saved) {
    (saved || []).forEach(item => {
      if (!item || !item.src) return;
      const el = addItem(item.src,
        clamp(Number(item.rx) || 0, 0, 1),
        clamp(Number(item.ry) || 0, 0, 1),
        item.name || 'Furniture');
      el.dataset.scale = clamp(Number(item.scale) || DEFAULT_SCALE, 0.05, 0.7);
      position(el);
    });
  }

  const savedNode = document.getElementById('saved-placement');
  if (savedNode) {
    try { restore(JSON.parse(savedNode.textContent).items || []); }
    catch (_) { /* ignore malformed saved data */ }
  }

  function attachMove(el) {
    let dragging = false;
    el.addEventListener('pointerdown', e => {
      if (e.target.closest('.remove')) return;
      dragging = true;
      el.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    el.addEventListener('pointermove', e => {
      if (!dragging) return;
      const rect = canvas.getBoundingClientRect();
      el.dataset.rx = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      el.dataset.ry = clamp((e.clientY - rect.top) / rect.height, 0, 1);
      position(el);
    });
    const end = e => {
      if (!dragging) return;
      dragging = false;
      try { el.releasePointerCapture(e.pointerId); } catch (_) { /* already released */ }
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    el.addEventListener('wheel', e => {
      e.preventDefault();
      const step = e.deltaY < 0 ? 0.01 : -0.01;
      el.dataset.scale = clamp(parseFloat(el.dataset.scale) + step, 0.05, 0.7);
      position(el);
    }, { passive: false });
  }

  function pointInCanvas(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      rx: clamp((e.clientX - rect.left) / rect.width, 0, 1),
      ry: clamp((e.clientY - rect.top) / rect.height, 0, 1),
    };
  }

  function readFile(file, cb) {
    const reader = new FileReader();
    reader.onload = () => cb(reader.result);
    reader.readAsDataURL(file);
  }

  // Palette: HTML5 drag plus click-to-place for touch devices.
  palette.querySelectorAll('[data-src]').forEach(item => {
    item.addEventListener('dragstart', e => {
      e.dataTransfer.setData('text/plain', JSON.stringify({
        src: item.dataset.src, name: item.dataset.name,
      }));
      e.dataTransfer.effectAllowed = 'copy';
    });
    item.addEventListener('click', () => addItem(item.dataset.src, 0.5, 0.5, item.dataset.name));
  });

  // Drop items from the palette, or image files straight from the desktop.
  canvas.addEventListener('dragover', e => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    canvas.classList.add('drag-over');
  });
  canvas.addEventListener('dragleave', e => {
    if (!canvas.contains(e.relatedTarget)) canvas.classList.remove('drag-over');
  });
  canvas.addEventListener('drop', e => {
    e.preventDefault();
    canvas.classList.remove('drag-over');
    const { rx, ry } = pointInCanvas(e);
    const raw = e.dataTransfer.getData('text/plain');
    if (raw) {
      try {
        const data = JSON.parse(raw);
        if (data.src) {
          addItem(data.src, rx, ry, data.name);
          return;
        }
      } catch (_) { /* not our payload */ }
    }
    const file = Array.from(e.dataTransfer.files).find(f => f.type.startsWith('image/'));
    if (file) readFile(file, src => addItem(src, rx, ry, file.name));
  });

  const fileInput = panel.querySelector('[data-custom-image]');
  if (fileInput) fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (file) readFile(file, src => addItem(src, 0.5, 0.5, file.name));
    fileInput.value = '';
  });

  panel.querySelector('[data-clear-placement]').addEventListener('click', () => {
    items.forEach(el => el.remove());
    items = [];
    refreshHint();
    status.textContent = 'Placement cleared. Drag an item from the palette to start again.';
  });

  const saveButton = panel.querySelector('[data-save-placement]');
  if (saveButton) saveButton.addEventListener('click', async () => {
    saveButton.disabled = true;
    status.textContent = 'Saving placement...';
    const payload = {
      items: items.map(el => ({
        src: el.dataset.src, name: el.dataset.name,
        rx: parseFloat(el.dataset.rx), ry: parseFloat(el.dataset.ry),
        scale: parseFloat(el.dataset.scale),
      })),
    };
    try {
      const res = await fetch(panel.dataset.saveUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) throw new Error(data.error || 'Could not save placement.');
      status.textContent = 'Saved ' + data.count + ' placed item(s).';
    } catch (err) {
      status.textContent = err.message || 'Could not save placement.';
    } finally {
      saveButton.disabled = false;
    }
  });

  // Flatten the arranged items onto the original result and download a PNG.
  panel.querySelector('[data-download-placement]').addEventListener('click', async () => {
    const button = panel.querySelector('[data-download-placement]');
    button.disabled = true;
    status.textContent = 'Preparing your image...';
    try {
      const base = await ready(Object.assign(new Image(), { src: resultUrl }));
      await Promise.all(items.map(el => ready(el._image)));

      const out = document.createElement('canvas');
      out.width = base.naturalWidth;
      out.height = base.naturalHeight;
      const ctx = out.getContext('2d');
      ctx.drawImage(base, 0, 0);

      items.forEach(el => {
        const img = el._image;
        const w = parseFloat(el.dataset.scale) * out.width;
        const h = w * img.naturalHeight / img.naturalWidth;
        const x = parseFloat(el.dataset.rx) * out.width - w / 2;
        const y = parseFloat(el.dataset.ry) * out.height - h / 2;
        ctx.drawImage(img, x, y, w, h);
      });

      out.toBlob(blob => {
        button.disabled = false;
        if (!blob) {
          status.textContent = 'Could not create the image. Please try again.';
          return;
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'ai-interior-design.png';
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        status.textContent = 'Downloaded ' + items.length + ' placed item(s) with your design.';
      }, 'image/png');
    } catch (err) {
      button.disabled = false;
      status.textContent = 'An image failed to load. Please try again.';
    }
  });
})();
