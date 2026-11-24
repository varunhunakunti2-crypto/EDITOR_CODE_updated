/* Custom-area drag selector for the design preview.
 *
 * Stores normalized 0-1 coordinates ("x1,y1,x2,y2") in a hidden form field.
 * The legacy static/JS/mask.js is intentionally left untouched.
 */
(function () {
  'use strict';

  const MIN_SIDE = 0.02;   // ignore hairline drags
  const MIN_AREA = 0.01;   // 1% of the image, matches masking.py
  const MAX_AREA = 0.85;   // keep 15% of the room visible, matches masking.py

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  function round(value) {
    return Math.round(value * 10000) / 10000;
  }

  function format(coords) {
    return coords.map(round).join(',');
  }

  class RegionMask {
    constructor(options) {
      this.canvas = options.canvas;
      this.field = options.field;
      this.readout = options.readout;
      this.status = options.status;
      this.clearButton = options.clearButton;
      this.stage = options.stage;
      this.onChange = options.onChange || function () {};
      this.onReset = options.onReset || function () {};
      this.ctx = this.canvas.getContext('2d');
      this.enabled = false;
      this.dragging = false;
      this.start = null;
      this.current = null;
      this.coords = null;

      this.canvas.addEventListener('pointerdown', this.onPointerDown.bind(this));
      this.canvas.addEventListener('pointermove', this.onPointerMove.bind(this));
      this.canvas.addEventListener('pointerup', this.onPointerUp.bind(this));
      this.canvas.addEventListener('pointercancel', this.onPointerCancel.bind(this));
      this.clearButton.addEventListener('click', this.clear.bind(this));
      window.addEventListener('resize', this.resize.bind(this));
    }

    setEnabled(enabled) {
      this.enabled = !!enabled;
      this.canvas.classList.toggle('region-active', this.enabled);
      if (this.enabled) this.resize();
      else this.dragging = false;
    }

    resize() {
      const rect = this.canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      if (this.canvas.width !== width || this.canvas.height !== height) {
        this.canvas.width = width;
        this.canvas.height = height;
      }
      this.repaint();
    }

    point(event) {
      const rect = this.canvas.getBoundingClientRect();
      return {
        x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
        y: clamp((event.clientY - rect.top) / rect.height, 0, 1)
      };
    }

    boxFrom(a, b) {
      return [
        Math.min(a.x, b.x), Math.min(a.y, b.y),
        Math.max(a.x, b.x), Math.max(a.y, b.y)
      ];
    }

    onPointerDown(event) {
      if (!this.enabled || !this.stage.classList.contains('has-image')) return;
      event.preventDefault();
      this.resize();
      this.dragging = true;
      this.start = this.point(event);
      this.current = this.start;
      if (this.canvas.setPointerCapture) this.canvas.setPointerCapture(event.pointerId);
      this.repaint();
      this.onChange(this.boxFrom(this.start, this.current));
    }

    onPointerMove(event) {
      if (!this.dragging) return;
      event.preventDefault();
      this.current = this.point(event);
      this.repaint();
      this.onChange(this.boxFrom(this.start, this.current));
    }

    onPointerUp(event) {
      if (!this.dragging) return;
      this.current = this.point(event);
      this.dragging = false;

      const box = this.boxFrom(this.start, this.current);
      const width = box[2] - box[0];
      const height = box[3] - box[1];
      const area = width * height;
      if (width < MIN_SIDE || height < MIN_SIDE ||
          area < MIN_AREA || area > MAX_AREA) {
        this.clear('That box is too small. Drag a larger area (at least 1% of the photo).');
        return;
      }

      this.coords = box.map(round);
      this.field.value = format(this.coords);
      this.readout.textContent = format(this.coords);
      this.status.textContent = 'Custom area selected. Only this box will be edited.';
      this.status.classList.remove('err');
      this.onChange(this.coords);
      this.repaint();
    }

    onPointerCancel() {
      this.dragging = false;
    }

    repaint() {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      const box = this.dragging ? this.boxFrom(this.start, this.current) : this.coords;
      if (!box) return;
      const x = box[0] * this.canvas.width;
      const y = box[1] * this.canvas.height;
      const width = (box[2] - box[0]) * this.canvas.width;
      const height = (box[3] - box[1]) * this.canvas.height;
      ctx.fillStyle = 'rgba(185,139,62,.25)';
      ctx.fillRect(x, y, width, height);
      ctx.strokeStyle = '#b98b3e';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(x, y, width, height);
      ctx.setLineDash([]);
    }

    clear(message) {
      this.coords = null;
      this.dragging = false;
      this.start = null;
      this.current = null;
      this.field.value = '';
      this.readout.textContent = 'None — drag on the photo to choose an area.';
      if (message) {
        this.status.textContent = message;
        this.status.classList.add('err');
      } else {
        this.status.textContent = 'No custom area selected; the centre zone will be used.';
        this.status.classList.remove('err');
      }
      this.repaint();
      this.onReset();
    }
  }

  window.RegionMask = RegionMask;
})();
