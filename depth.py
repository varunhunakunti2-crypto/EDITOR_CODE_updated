"""Lightweight relative-depth assistant for room photos.

Uses ``depth-anything/Depth-Anything-V2-Small-hf`` (Apache 2.0, ~99 MB) via
``transformers``. It is deliberately separate from the inpainting generator:
it produces a colour preview and a short geometry hint, while the editable
mask and Stable Diffusion inpainting pipeline stay exactly as they were.

The output is *relative* depth (near/far), not a measured depth map in metres.
"""
import os
import threading
import uuid

import cv2
import numpy as np
import torch
from PIL import Image

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, 'static', 'uploads', 'depth')

_lock = threading.Lock()
_components = None
_error = None
_loading = False
_device = None


def resolve_device():
    """Use CUDA only when explicitly available; otherwise stay on CPU."""
    requested = (config.DEPTH_DEVICE or 'auto').lower()
    if requested == 'cpu':
        return 'cpu'
    return 'cuda' if torch.cuda.is_available() else 'cpu'


def _build_components(local_files_only=False):
    """Load the processor/model pair, preferring the online cache fallback."""
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    device = resolve_device()
    dtype = torch.float16 if device == 'cuda' else torch.float32
    processor = AutoImageProcessor.from_pretrained(
        config.DEPTH_MODEL_ID, local_files_only=local_files_only)
    try:
        model = AutoModelForDepthEstimation.from_pretrained(
            config.DEPTH_MODEL_ID, dtype=dtype,
            local_files_only=local_files_only)
    except TypeError:
        # Older transformers releases used torch_dtype instead of dtype.
        model = AutoModelForDepthEstimation.from_pretrained(
            config.DEPTH_MODEL_ID, torch_dtype=dtype,
            local_files_only=local_files_only)
    model.to(device)
    model.eval()
    return (processor, model), device


def get_components():
    """Return the cached depth model, loading it on first use if necessary."""
    global _components, _error, _loading, _device
    if _components is not None:
        return _components
    with _lock:
        if _components is not None:
            return _components
        _loading = True
        try:
            try:
                _components, _device = _build_components()
            except Exception as online_error:
                print('[WARN] Online depth model load failed (%s); '
                      'trying local cache...' % online_error)
                _components, _device = _build_components(local_files_only=True)
            _error = None
            print('[OK] Depth model loaded on %s' % _device)
        except Exception as exc:
            _error = str(exc)
            _components = None
            print('[ERROR] Error loading depth model: %s' % exc)
        finally:
            _loading = False
        return _components


def status():
    """Safe health-check payload (no secrets, no large objects)."""
    return {
        'enabled': config.DEPTH_ENABLED,
        'model': config.DEPTH_MODEL_ID,
        'loaded': _components is not None,
        'loading': _loading,
        'error': _error,
        'device': _device or resolve_device(),
    }


def depth_filename(input_filename):
    """Deterministic preview name so a result page can find it without a DB column."""
    stem = os.path.splitext(os.path.basename(input_filename or ''))[0]
    return 'depth_' + stem + '.png'


def compute_depth(image, max_size=None):
    """Return a 0..1 relative-depth array for a PIL image or a file path."""
    if isinstance(image, (str, bytes, os.PathLike)):
        image = Image.open(image).convert('RGB')
    else:
        image = image.convert('RGB')

    limit = int(max_size or config.DEPTH_MAX_SIZE)
    if max(image.size) > limit:
        scale = limit / float(max(image.size))
        image = image.resize((max(1, round(image.width * scale)),
                              max(1, round(image.height * scale))),
                             Image.Resampling.LANCZOS)

    components = get_components()
    if components is None:
        raise RuntimeError(_error or 'Depth model is not available yet.')
    processor, model = components
    device = _device or resolve_device()

    inputs = processor(images=image, return_tensors='pt')
    inputs = {key: value.to(device) if hasattr(value, 'to') else value
              for key, value in inputs.items()}
    with torch.inference_mode():
        predicted = model(**inputs).predicted_depth
        predicted = torch.nn.functional.interpolate(
            predicted.unsqueeze(1), size=image.size[::-1],
            mode='bicubic', align_corners=False)
        values = predicted.squeeze().float().cpu().numpy()

    low, high = np.percentile(values, (2, 98))
    if not np.isfinite(low) or not np.isfinite(high) or high - low < 1e-6:
        normalized = np.zeros(values.shape, dtype=np.float32)
    else:
        normalized = np.clip((values - low) / (high - low), 0.0, 1.0)
    return normalized.astype(np.float32), image.size


def describe_depth(normalized, mask=None):
    """Turn a depth array into one short, honest geometry hint."""
    values = np.asarray(normalized, dtype=np.float32)
    if values.ndim != 2 or values.size == 0:
        return 'Depth estimate: unavailable. Keep perspective and scale consistent.'

    relation = ''
    if mask is not None:
        resized = np.asarray(mask.convert('L').resize(
            (values.shape[1], values.shape[0])), dtype=np.uint8) > 127
        if resized.any() and (~resized).any():
            inside = float(values[resized].mean())
            outside = float(values[~resized].mean())
            difference = inside - outside
            if difference > 0.07:
                relation = 'the selected area is closer to the camera than its surroundings'
            elif difference < -0.07:
                relation = 'the selected area sits farther back than its surroundings'
            else:
                relation = 'the selected area is at a similar depth to its surroundings'

    near_share = float((values > 0.66).mean())
    far_share = float((values < 0.34).mean())
    parts = []
    if relation:
        parts.append(relation)
    if near_share > 0.35:
        parts.append('prominent foreground surfaces')
    elif far_share > 0.35:
        parts.append('open background depth')
    else:
        parts.append('mixed foreground and background')
    return ('Depth estimate: ' + '; '.join(parts) +
            '. Keep perspective, occlusion and furniture scale consistent.')


def save_preview(normalized, output_dir=None, filename=None):
    """Write a colourized depth PNG and return its filesystem path."""
    target_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(target_dir, exist_ok=True)
    gray = np.clip(np.asarray(normalized) * 255.0, 0, 255).astype(np.uint8)
    try:
        coloured = cv2.cvtColor(cv2.applyColorMap(gray, cv2.COLORMAP_MAGMA),
                                cv2.COLOR_BGR2RGB)
        preview = Image.fromarray(coloured)
    except Exception:
        preview = Image.fromarray(gray).convert('RGB')
    path = os.path.join(target_dir, filename or ('depth_' + uuid.uuid4().hex + '.png'))
    preview.save(path)
    return path


def estimate_depth(image, mask=None, output_dir=None, filename=None, max_size=None):
    """Compute, save and describe a relative-depth preview in one call."""
    normalized, size = compute_depth(image, max_size=max_size)
    preview_path = save_preview(normalized, output_dir=output_dir, filename=filename)
    return {
        'normalized': normalized,
        'size': size,
        'preview_path': preview_path,
        'hint': describe_depth(normalized, mask=mask),
        'stats': {
            'near_share': round(float((normalized > 0.66).mean()), 3),
            'far_share': round(float((normalized < 0.34).mean()), 3),
            'contrast': round(float(normalized.std()), 3),
        },
    }
