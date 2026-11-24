"""Verify room_analysis.py: three known-geometry photos, real photos, overrides.

Run from the project folder:  python tests/room_analysis_check.py
No Flask server or API keys are needed.
"""
import glob
import json
import os
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from room_analysis import analyze_room

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


def make_room(path, size, wall, door_px):
    """Render a room with a door of known pixel height (2 m) and clear walls."""
    width, height = size
    x1, x2, y1, y2 = wall
    img = np.full((height, width, 3), 235, np.uint8)
    img[y2:, :] = (170, 165, 160)
    img[:y1, :] = (225, 225, 225)
    img[:, :x1] = (210, 210, 210)
    img[:, x2:] = (200, 200, 200)
    cv2.rectangle(img, (x1, y1), (x2, y2), (40, 40, 40), 3)
    cv2.line(img, (0, y2), (width, y2), (60, 60, 60), 3)
    cv2.line(img, (0, y1), (width, y1), (80, 80, 80), 2)
    door_x = (x1 + x2) // 2 - 50
    cv2.rectangle(img, (door_x, y2 - door_px), (door_x + 100, y2), (30, 30, 30), 3)
    cv2.rectangle(img, (door_x + 3, y2 - door_px + 3), (door_x + 97, y2 - 3),
                  (120, 120, 120), -1)
    noise = np.clip(img.astype(np.int16) +
                    np.random.normal(0, 2.5, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(path, noise)
    scale = door_px / 2.0
    return {'width_m': (x2 - x1) / scale, 'height_m': (y2 - y1) / scale}


tmp = tempfile.mkdtemp(prefix='room-analysis-test-')
cases = [
    ('room_a.jpg', (800, 600), (150, 650, 120, 400), 200),
    ('room_b.jpg', (900, 700), (180, 720, 100, 420), 240),
    ('room_c.jpg', (1000, 700), (200, 800, 90, 450), 180),
]
for name, size, wall, door_px in cases:
    path = os.path.join(tmp, name)
    expected = make_room(path, size, wall, door_px)
    try:
        result = analyze_room(path, reference_length_m=2.0,
                              reference_pixels=door_px, output_dir=tmp)
    except Exception as exc:
        check('%s analyses without crash' % name, False, repr(exc))
        continue
    check('%s analyses without crash' % name, True)
    check('%s width plausible' % name,
          abs(result['width_m'] - expected['width_m']) / expected['width_m'] < 0.12,
          'got %.2f m, expected %.2f m' % (result['width_m'], expected['width_m']))
    check('%s height plausible' % name,
          abs(result['height_m'] - expected['height_m']) / expected['height_m'] < 0.12,
          'got %.2f m, expected %.2f m' % (result['height_m'], expected['height_m']))
    check('%s length + confidence' % name,
          2 <= result['length_m'] <= 20 and result['confidence'] == 'high',
          '%.2f m / %s' % (result['length_m'], result['confidence']))
    overlay = os.path.join(tmp, os.path.basename(result['overlay_path']))
    check('%s overlay written' % name,
          os.path.isfile(overlay) and os.path.getsize(overlay) > 1000,
          result['overlay_path'])
    print('   ', name, json.dumps({key: result[key] for key in
          ('width_m', 'length_m', 'height_m', 'confidence')}), flush=True)

override = analyze_room(os.path.join(tmp, 'room_a.jpg'), reference_length_m=2,
                        reference_pixels=200,
                        manual={'width_m': 5.5, 'length_m': 6.0, 'height_m': 3.0},
                        output_dir=tmp)
check('manual override applied',
      (override['width_m'], override['length_m'], override['height_m']) ==
      (5.5, 6.0, 3.0) and override['confidence'] == 'manual')
check('override note explains', 'Manual override' in override['note'])

real = sorted(glob.glob(os.path.join('static', 'uploads', 'input', '*.jpg')))[:3]
if real:
    for path in real:
        try:
            result = analyze_room(path, output_dir=tmp)
            ok = (0.5 < result['width_m'] < 30 and 1.5 < result['height_m'] < 8
                  and 0.5 < result['length_m'] < 40
                  and os.path.isfile(os.path.join(
                      tmp, os.path.basename(result['overlay_path']))))
            check('real photo %s' % os.path.basename(path)[:12], ok,
                  '%.2f x %.2f x %.2f m / %s' % (
                      result['width_m'], result['length_m'], result['height_m'],
                      result['confidence']))
        except Exception as exc:
            check('real photo %s' % os.path.basename(path)[:12], False, repr(exc))
else:
    print('SKIP real photos (none uploaded yet)', flush=True)

try:
    analyze_room(os.path.join(tmp, 'missing.jpg'), output_dir=tmp)
    check('missing image raises clear error', False)
except ValueError as exc:
    check('missing image raises clear error', 'Could not read image' in str(exc))

print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
if FAIL:
    print('FAILED:', FAIL)
    raise SystemExit(1)
