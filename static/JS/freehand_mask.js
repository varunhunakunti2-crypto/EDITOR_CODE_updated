/* Freehand paint mask for the design preview.
 *
 * Pointer strokes (mouse, touch or pen) are drawn as translucent white on the
 * visible preview canvas. A hidden 512x512 canvas keeps an exact black/white
 * version; its PNG data URL is written to the hidden form field on every stroke
 * and again on submit. The legacy static/JS/mask.js is intentionally untouched.
 */
(function () {
  'use strict';

  const EXPORT_SIZE = 512;

  function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
  }

  class FreehandMask {
    constructor(options) {
      this.canvas = options.canvas;
      this.exportCanvas = options.exportCanvas;
      this.field = options.field;
      this.slider = options.slider;
      this.brushValue = options.brushValue;
      this.brushButton = options.brushButton;
      this.eraserButton = options.eraserButton;
      this.clearButton = options.clearButton;
      this.status = options.status;
      this.stage = options.stage;
      this.form = options.form;

      this.ctx = this.canvas.getContext('2d');
      this.exportCtx = this.exportCanvas.getContext('2d');
      this.exportCanvas.width = EXPORT_SIZE;
      this.exportCanvas.height = EXPORT_SIZE;

      this.strokes = [];
      this.current = null;
      this.enabled = false;
      this.tool = 'brush';
      this.brush = this.readBrush();
      this.resetExport();

      this.canvas.addEventListener('pointerdown', this.onPointerDown.bind(this));
      this.canvas.addEventListener('pointermove', this.onPointerMove.bind(this));
      this.canvas.addEventListener('pointerup', this.onPointerUp.bind(this));
      this.canvas.addEventListener('pointercancel', this.onPointerCancel.bind(this));
      this.slider.addEventListener('input', () => {
        this.brush = this.readBrush();
        if (this.brushValue) this.brushValue.textContent = this.brush + ' px';
      });
      this.brushButton.addEventListener('click', () => this.setTool('brush'));
      this.eraserButton.addEventListener('click', () => this.setTool('eraser'));
      this.clearButton.addEventListener('click', () => this.clear());
      this.form.addEventListener('submit', () => this.export());
      window.addEventListener('resize', this.resize.bind(this));
    }

    readBrush() {
      const value = parseInt(this.slider.value, 10);
      return Number.isFinite(value) ? clamp(value, 8, 96) : 36;
    }

    setTool(tool) {
      this.tool = tool === 'eraser' ? 'eraser' : 'brush';
      const brush = this.tool === 'brush';
      this.brushButton.setAttribute('aria-pressed', String(brush));
      this.eraserButton.setAttribute('aria-pressed', String(!brush));
      if (this.status) {
        this.status.textContent = brush
          ? 'Brush: drag on the photo to paint the area to edit.'
          : 'Eraser: drag over white paint to remove it.';
      }
    }

    setEnabled(enabled) {
      this.enabled = !!enabled;
      this.canvas.classList.toggle('paint-active', this.enabled);
      if (this.enabled) this.resize();
      else this.current = null;
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
      if (!rect.width || !rect.height) return [0, 0];
      return [
        clamp((event.clientX - rect.left) / rect.width, 0, 1),
        clamp((event.clientY - rect.top) / rect.height, 0, 1)
      ];
    }

    events(event) {
      const coalesced = typeof event.getCoalescedEvents === 'function'
        ? event.getCoalescedEvents() : [];
      return coalesced.length ? coalesced : [event];
    }

    onPointerDown(event) {
      if (!this.enabled || !this.stage.classList.contains('has-image')) return;
      event.preventDefault();
      this.resize();
      this.current = {
        tool: this.tool,
        brush: this.brush,
        points: [this.point(event)]
      };
      this.strokes.push(this.current);
      try {
        if (this.canvas.setPointerCapture) this.canvas.setPointerCapture(event.pointerId);
      } catch (ignore) {
        // Synthetic pointer events (tests) have no capture target; ignore.
      }
      this.repaint();
    }

    onPointerMove(event) {
      if (!this.current) return;
      event.preventDefault();
      this.events(event).forEach(sample => this.current.points.push(this.point(sample)));
      this.repaint();
    }

    onPointerUp(event) {
      if (!this.current) return;
      event.preventDefault();
      this.events(event).forEach(sample => this.current.points.push(this.point(sample)));
      this.current = null;
      this.export();
      if (this.status) {
        this.status.textContent = 'Painted area saved. Only the white strokes will be edited.';
      }
    }

    onPointerCancel() {
      this.current = null;
      this.export();
    }

    hasStrokes() {
      return this.strokes.length > 0;
    }

    drawStroke(ctx, stroke, width, height, preview) {
      if (!stroke.points.length) return;
      const brush = stroke.brush;
      const lineWidth = preview ? brush * (width / EXPORT_SIZE) : brush;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (preview && stroke.tool === 'eraser') {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.strokeStyle = 'rgba(0,0,0,1)';
        ctx.fillStyle = 'rgba(0,0,0,1)';
      } else {
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = preview ? 'rgba(255,255,255,.72)' :
          (stroke.tool === 'eraser' ? '#000' : '#fff');
        ctx.fillStyle = ctx.strokeStyle;
      }

      const first = stroke.points[0];
      if (stroke.points.length === 1) {
        ctx.beginPath();
        ctx.arc(first[0] * width, first[1] * height, lineWidth / 2, 0, Math.PI * 2);
        ctx.fill();
        return;
      }
      ctx.beginPath();
      ctx.moveTo(first[0] * width, first[1] * height);
      stroke.points.slice(1).forEach(point => ctx.lineTo(point[0] * width, point[1] * height));
      ctx.stroke();
    }

    repaint() {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this.strokes.forEach(stroke =>
        this.drawStroke(ctx, stroke, this.canvas.width, this.canvas.height, true));
      ctx.globalCompositeOperation = 'source-over';
    }

    resetExport() {
      const ctx = this.exportCtx;
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
      this.field.value = '';
    }

    export() {
      const ctx = this.exportCtx;
      ctx.globalCompositeOperation = 'source-over';
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, EXPORT_SIZE, EXPORT_SIZE);
      this.strokes.forEach(stroke =>
        this.drawStroke(ctx, stroke, EXPORT_SIZE, EXPORT_SIZE, false));
      ctx.globalCompositeOperation = 'source-over';
      this.field.value = this.hasStrokes()
        ? this.exportCanvas.toDataURL('image/png') : '';
    }

    clear() {
      this.strokes = [];
      this.current = null;
      this.resetExport();
      this.repaint();
      if (this.status) {
        this.status.textContent = 'Painting cleared. Choose a preset to use its normal zone.';
      }
    }
  }

  window.FreehandMask = FreehandMask;
})();
