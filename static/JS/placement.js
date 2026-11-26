(function () {
  const panel = document.querySelector('[data-placement]');
  if (!panel) return;

  const canvas = panel.querySelector('[data-canvas]');
  const palette = panel.querySelector('[data-palette]');
  const status = panel.querySelector('[data-placement-status]');
  const resultUrl = panel.dataset.resultImage;
  const DEFAULT_SCALE = 0.18;
  const ROTATE_STEP = 15;
  let items = [];

  // Parse CV-detected frame box (rx, ry = center ratios; scale = width ratio; height_ratio = height ratio)
  let frameBox = null;
  if (panel.dataset.detectedFrame) {
    try {
      frameBox = JSON.parse(panel.dataset.detectedFrame);
    } catch (_) {}
  }

  // Fallback: parse mask_coords "x1,y1,x2,y2" in percentages
  if (!frameBox && panel.dataset.maskCoords) {
    const parts = panel.dataset.maskCoords.split(',').map(n => parseFloat(n.trim()));
    if (parts.length === 4 && !parts.some(isNaN)) {
      const [x1, y1, x2, y2] = parts;
      frameBox = {
        rx: ((x1 + x2) / 2) / 100,
        ry: ((y1 + y2) / 2) / 100,
        scale: Math.abs(x2 - x1) / 100,
        height_ratio: Math.abs(y2 - y1) / 100,
      };
    }
  }

  /**
   * Calculate the best-fit scale (width fraction of canvas) so that the image
   * with naturalWidth x naturalHeight fits INSIDE the frame using "contain" logic:
   * - Both width and height of the item must not exceed the frame dimensions.
   * - The item keeps its own aspect ratio.
   *
   * canvasW / canvasH = current pixel size of the placement canvas.
   * frameBox.scale     = frame width  as fraction of canvas width
   * frameBox.height_ratio = frame height as fraction of canvas height
   */
  function fitScale(imgW, imgH) {
    if (!frameBox || !imgW || !imgH) return DEFAULT_SCALE;
    const canvasRect = canvas.getBoundingClientRect();
    const canvasW = canvasRect.width  || 800;
    const canvasH = canvasRect.height || 600;

    const framePixW = frameBox.scale       * canvasW;
    const framePixH = (frameBox.height_ratio || frameBox.scale * canvasH / canvasW) * canvasH;

    // "Contain": scale the item so it fits inside the frame without cropping
    const scaleByW = framePixW / imgW;          // pixel scale if width-limited
    const scaleByH = framePixH / imgH;          // pixel scale if height-limited
    const bestPixScale = Math.min(scaleByW, scaleByH);  // contain = smaller of two

    // Convert back to canvas-width fraction
    return clamp((bestPixScale * imgW) / canvasW, 0.05, 0.95);
  }

  /**
   * Snap el to the frame center and size it to fit the frame.
   * Waits for the image to load so we know its natural dimensions.
   */
  function snapToFrame(el) {
    if (!frameBox) return;
    el.dataset.rx = frameBox.rx;
    el.dataset.ry = frameBox.ry;
    el.dataset.rotation = 0;

    const img = el._image;
    const apply = () => {
      el.dataset.scale = fitScale(img.naturalWidth, img.naturalHeight);
      position(el);
    };

    if (img.complete && img.naturalWidth) {
      apply();
    } else {
      img.addEventListener('load', apply, { once: true });
    }
  }

  /**
   * Returns coords for auto-placement:
   * - If frameBox exists → snap to frame center with fitted scale.
   * - Otherwise → use the drop point with DEFAULT_SCALE.
   */
  function getAutoCoords(rx, ry) {
    if (frameBox) {
      return { rx: frameBox.rx, ry: frameBox.ry, scale: frameBox.scale, snapFrame: true };
    }
    return { rx, ry, scale: DEFAULT_SCALE, snapFrame: false };
  }

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  // Keep angles in -180..180 so saved arrangements round-trip cleanly.
  function normalizeRotation(value) {
    const n = Number(value) || 0;
    return ((n + 180) % 360 + 360) % 360 - 180;
  }

  function position(el) {
    const rotation = normalizeRotation(el.dataset.rotation);
    el.dataset.rotation = rotation;
    el.style.left = (parseFloat(el.dataset.rx) * 100) + '%';
    el.style.top  = (parseFloat(el.dataset.ry) * 100) + '%';
    el.style.width = (parseFloat(el.dataset.scale) * 100) + '%';
    el.style.transform = 'translate(-50%, -50%) rotate(' + rotation + 'deg)';
  }

  function refreshHint() {
    canvas.classList.toggle('has-items', items.length > 0);
  }

  function ready(img) {
    if (img.complete && img.naturalWidth) return Promise.resolve(img);
    return new Promise((resolve, reject) => {
      img.addEventListener('load',  () => resolve(img), { once: true });
      img.addEventListener('error', () => reject(img),  { once: true });
    });
  }

  function controlButton(className, label, text, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = text;
    button.setAttribute('aria-label', label);
    button.addEventListener('click', e => {
      e.stopPropagation();
      onClick();
    });
    return button;
  }

  function addItem(src, rx, ry, name, scale, rotation, autoSnap) {
    const el = document.createElement('div');
    el.className = 'placed-item';
    el.dataset.src  = src;
    el.dataset.name = name || 'Furniture';
    el.dataset.rx   = rx;
    el.dataset.ry   = ry;
    el.dataset.scale    = clamp(Number(scale) || DEFAULT_SCALE, 0.05, 0.95);
    el.dataset.rotation = normalizeRotation(rotation || 0);

    const img = document.createElement('img');
    img.src = src;
    img.alt = el.dataset.name;
    img.draggable = false;
    el._image = img;

    const remove = controlButton('remove', 'Remove ' + el.dataset.name,
      '\u00d7', () => {
        el.remove();
        items = items.filter(x => x !== el);
        refreshHint();
      });

    const rotateLeft = controlButton('rotate rotate-left',
      'Rotate ' + el.dataset.name + ' left', '\u21ba', () => {
        el.dataset.rotation = normalizeRotation(
          normalizeRotation(el.dataset.rotation) - ROTATE_STEP);
        position(el);
      });

    const rotateRight = controlButton('rotate rotate-right',
      'Rotate ' + el.dataset.name + ' right', '\u21bb', () => {
        el.dataset.rotation = normalizeRotation(
          normalizeRotation(el.dataset.rotation) + ROTATE_STEP);
        position(el);
      });

    el.appendChild(img);
    el.appendChild(remove);
    el.appendChild(rotateLeft);
    el.appendChild(rotateRight);
    canvas.appendChild(el);
    items.push(el);

    // Auto-snap: when frameBox is detected, fit the item into the frame immediately.
    if (autoSnap && frameBox) {
      snapToFrame(el);
      status.textContent = 'Snapped to frame. Drag to reposition or use Fit to frame.';
    } else {
      position(el);
    }

    attachMove(el);
    refreshHint();
    return el;
  }

  // Restore an arrangement saved earlier via POST /design/<id>/placement.
  function restore(saved) {
    (saved || []).forEach(item => {
      if (!item || !item.src) return;
      addItem(item.src,
        clamp(Number(item.rx) || 0, 0, 1),
        clamp(Number(item.ry) || 0, 0, 1),
        item.name || 'Furniture',
        item.scale,
        item.rotation !== undefined ? item.rotation : item.rot,
        false);  // don't re-snap saved items
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
      if (e.target.closest('.remove, .rotate')) return;
      dragging = true;
      el.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    el.addEventListener('pointermove', e => {
      if (!dragging) return;
      const rect = canvas.getBoundingClientRect();
      el.dataset.rx = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      el.dataset.ry = clamp((e.clientY - rect.top)  / rect.height, 0, 1);
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
      if (e.shiftKey || e.altKey) {
        const delta = e.deltaY < 0 ? ROTATE_STEP : -ROTATE_STEP;
        el.dataset.rotation = normalizeRotation(
          normalizeRotation(el.dataset.rotation) + delta);
      } else {
        const step = e.deltaY < 0 ? 0.01 : -0.01;
        el.dataset.scale = clamp(parseFloat(el.dataset.scale) + step, 0.05, 0.95);
      }
      position(el);
    }, { passive: false });
  }

  function pointInCanvas(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      rx: clamp((e.clientX - rect.left) / rect.width, 0, 1),
      ry: clamp((e.clientY - rect.top)  / rect.height, 0, 1),
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
    item.addEventListener('click', () => {
      const target = getAutoCoords(0.5, 0.5);
      addItem(item.dataset.src, target.rx, target.ry, item.dataset.name, target.scale,
              0, target.snapFrame);
    });
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
    const pt = pointInCanvas(e);
    const target = getAutoCoords(pt.rx, pt.ry);
    const raw = e.dataTransfer.getData('text/plain');
    if (raw) {
      try {
        const data = JSON.parse(raw);
        if (data.src) {
          addItem(data.src, target.rx, target.ry, data.name, target.scale, 0, target.snapFrame);
          return;
        }
      } catch (_) { /* not our payload */ }
    }
    const file = Array.from(e.dataTransfer.files).find(f => f.type.startsWith('image/'));
    if (file) {
      readFile(file, src =>
        addItem(src, target.rx, target.ry, file.name, target.scale, 0, target.snapFrame));
    }
  });

  const fileInput = panel.querySelector('[data-custom-image]');
  if (fileInput) fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (file) {
      const target = getAutoCoords(0.5, 0.5);
      readFile(file, src =>
        addItem(src, target.rx, target.ry, file.name, target.scale, 0, target.snapFrame));
    }
    fileInput.value = '';
  });

  // "Fit to frame" button — snaps the last placed item to the frame with correct scale.
  const snapBtn = panel.querySelector('[data-snap-frame]');
  if (snapBtn) {
    // Show button only when a frame was detected
    if (!frameBox) snapBtn.style.display = 'none';
    snapBtn.addEventListener('click', () => {
      if (!items.length) {
        status.textContent = 'Add an item first, then click Fit to frame.';
        return;
      }
      const last = items[items.length - 1];
      snapToFrame(last);
      status.textContent = 'Fitted "' + last.dataset.name + '" to the frame.';
    });
  }

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
        rotation: normalizeRotation(el.dataset.rotation),
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
      const base = await ready(Object.assign(new Image(), { src: resultUrl, crossOrigin: 'anonymous' }));
      await Promise.all(items.map(el => ready(el._image)));

      const out = document.createElement('canvas');
      out.width  = base.naturalWidth;
      out.height = base.naturalHeight;
      const ctx = out.getContext('2d');
      ctx.drawImage(base, 0, 0);

      items.forEach(el => {
        const img = el._image;
        const w = parseFloat(el.dataset.scale) * out.width;
        const h = w * img.naturalHeight / img.naturalWidth;
        const x = parseFloat(el.dataset.rx) * out.width  - w / 2;
        const y = parseFloat(el.dataset.ry) * out.height - h / 2;
        const rotation = normalizeRotation(el.dataset.rotation) * Math.PI / 180;
        ctx.save();
        ctx.translate(x + w / 2, y + h / 2);
        ctx.rotate(rotation);
        ctx.drawImage(img, -w / 2, -h / 2, w, h);
        ctx.restore();
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
