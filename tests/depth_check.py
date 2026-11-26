"""Check the optional depth-assistant layer without loading the real model.

Runs in-process with stubbed depth estimation and image generation, so it is
fast and deterministic. Run from the project folder: python tests/depth_check.py
"""
import atexit
import io
import json
import os
import sys
import uuid
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw
from sqlalchemy import inspect

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app as web
import config
import depth
from database import db, User, Design
from prompt_builder import build_prompt

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


class FakePipeline:
    last_prompt = None

    def __call__(self, prompt, image, mask_image, **kwargs):
        FakePipeline.last_prompt = prompt
        return SimpleNamespace(images=[image.copy()])


web.get_pipe = lambda: FakePipeline()
web.app.config['TESTING'] = True
client = web.app.test_client()

DESIGN_IDS = []
DESIGN_FILES = []
DEPTH_FILES = []
created_usernames = []
suffix = uuid.uuid4().hex[:8]


def room_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (640, 480), (232, 228, 222)).save(buf, 'JPEG')
    return buf.getvalue()


IMAGE = room_bytes()


def fake_estimate(image, mask=None, output_dir=None, filename=None, max_size=None):
    """Stand-in for the depth model: a simple foreground/background gradient."""
    grid = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    normalized = np.repeat(grid[None, :], 64, axis=0)
    if mask is not None:
        small = np.asarray(mask.convert('L').resize((64, 64))) > 127
        if small.any():
            normalized = normalized.copy()
            normalized[small] = np.clip(normalized[small] + 0.4, 0, 1)
    preview_path = depth.save_preview(normalized, output_dir=output_dir,
                                      filename=filename)
    DEPTH_FILES.append(preview_path)
    return {
        'normalized': normalized,
        'size': (64, 64),
        'preview_path': preview_path,
        'hint': depth.describe_depth(normalized, mask=mask),
        'stats': {'near_share': 0.4, 'far_share': 0.3, 'contrast': 0.29},
    }


web.depth.estimate_depth = fake_estimate


def login_as(user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def cleanup():
    files = list(DESIGN_FILES)
    with web.app.app_context():
        rows = Design.query.filter(Design.id.in_([i for i in DESIGN_IDS if i])).all()
        files += [(r.input_image, r.mask_image, r.output_image) for r in rows]
        db.session.query(Design).filter(Design.id.in_([r.id for r in rows])).delete(
            synchronize_session=False)
        db.session.query(User).filter(User.username.in_(created_usernames)).delete(
            synchronize_session=False)
        db.session.commit()
    for triple in files:
        for folder, filename in zip(('input', 'mask', 'output'), triple):
            for base in (os.path.join(ROOT, 'uploads'),
                         os.path.join(ROOT, 'static', 'uploads')):
                try:
                    os.remove(os.path.join(base, folder, filename))
                except OSError:
                    pass
    for path in DEPTH_FILES:
        try:
            os.remove(path)
        except OSError:
            pass


atexit.register(cleanup)

with web.app.app_context():
    username = 'depth_test_%s' % suffix
    created_usernames.append(username)
    user = User(username=username, email=username + '@t.local',
                password='unused', role='customer')
    db.session.add(user)
    db.session.commit()
    user_id = user.id

# --- configuration and prompt helper ---------------------------------------
check('depth model is the small Apache checkpoint',
      config.DEPTH_MODEL_ID == 'depth-anything/Depth-Anything-V2-Small-hf'
      and config.DEPTH_ENABLED, config.DEPTH_MODEL_ID)
check('depth filename derives from input',
      depth.depth_filename('photo.JPG') == 'depth_photo.png')
near = np.zeros((32, 32), dtype=np.float32)
near[:, :8] = 1.0
far = np.zeros((32, 32), dtype=np.float32)
far[:, :8] = 1.0
mask = Image.new('L', (32, 32), 0)
ImageDraw.Draw(mask).rectangle((0, 0, 7, 31), fill=255)
check('mask-aware near hint', 'closer to the camera' in
      depth.describe_depth(near, mask), depth.describe_depth(near, mask))
check('mask-aware far hint', 'farther back' in
      depth.describe_depth(far, Image.eval(mask, lambda v: 255 - v)),
      depth.describe_depth(far, Image.eval(mask, lambda v: 255 - v)))
check('bare prompt is unchanged without depth hint',
      build_prompt('a lamp') == 'a lamp.')
check('depth hint is appended only to the generation prompt',
      'depth cues: keep scale' in build_prompt('a lamp', depth_hint='keep scale')
      and build_prompt('a lamp').count('depth cues') == 0)

# --- status and preview API -------------------------------------------------
res = client.get('/depth-status')
state = json.loads(res.data)
check('depth-status endpoint', res.status_code == 200 and all(
    key in state for key in ('enabled', 'model', 'loaded', 'loading',
                             'error', 'device')), state)

anon = web.app.test_client()
res = anon.post('/api/estimate-depth', data={
    'image': (io.BytesIO(IMAGE), 'room.jpg')}, content_type='multipart/form-data')
check('estimate-depth requires login', res.status_code == 302, res.status_code)

login_as(user_id)
res = client.post('/api/estimate-depth', data={
    'image': (io.BytesIO(b'not an image'), 'bad.txt')},
    content_type='multipart/form-data')
check('estimate-depth rejects bad file', res.status_code == 400, res.status_code)
res = client.post('/api/estimate-depth', data={}, content_type='multipart/form-data')
check('estimate-depth rejects missing image', res.status_code == 400, res.status_code)

res = client.post('/api/estimate-depth', data={
    'image': (io.BytesIO(IMAGE), 'room.jpg')}, content_type='multipart/form-data')
data = json.loads(res.data)
preview_name = os.path.basename(data.get('preview_url', ''))
preview_path = os.path.join(ROOT, 'static', 'uploads', 'depth', preview_name)
check('estimate-depth returns preview and hint',
      res.status_code == 200 and data.get('preview_url', '').startswith(
          '/static/uploads/depth/') and 'hint' in data and 'stats' in data, data)
check('depth preview PNG is written', os.path.isfile(preview_path), preview_path)

# --- design form and end-to-end depth cue ----------------------------------
res = client.get('/design')
html = res.get_data(as_text=True)
check('design form exposes depth controls', res.status_code == 200 and all(
    text in html for text in ('name="use_depth"', 'id="depthBtn"',
                              'id="depthPreview"', 'id="depthStatus"',
                              'api/estimate-depth')))

res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'depth_design.jpg'),
    'prompt': 'a depth-aware bookshelf', 'position': 'custom',
    'mask_coords': '25,25,75,75', 'mode': 'zone',
    'detection_notes': 'Confidence: high.',
    'use_depth': '1',
}, content_type='multipart/form-data')
with web.app.app_context():
    design = Design.query.filter_by(prompt='a depth-aware bookshelf').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(design.id if design else None)
    if design:
        DESIGN_FILES.append((design.input_image, design.mask_image,
                             design.output_image))
check('depth-enabled design still saves',
      res.status_code == 302 and bool(design)
      and design.position == 'custom' and design.mask_coords == '25,25,75,75',
      (res.status_code, design.position if design else None))
check('raw prompt stays untouched',
      design.prompt == 'a depth-aware bookshelf' if design else False,
      design.prompt if design else None)
check('depth note is appended, not replaced',
      bool(design) and design.detection_notes.startswith('Confidence: high.')
      and 'Depth estimate:' in design.detection_notes,
      design.detection_notes if design else None)
check('generation prompt includes depth cue',
      FakePipeline.last_prompt and 'depth cues:' in FakePipeline.last_prompt,
      FakePipeline.last_prompt)

if design:
    expected_url = '/static/uploads/depth/' + depth.depth_filename(design.input_image)
    html = client.get('/design/%d' % design.id).get_data(as_text=True)
    check('result page shows depth preview without a DB column',
          expected_url in html and 'Relative depth preview' in html, expected_url)
    check('existing custom mask UI still present',
          'Custom area edited' in html and 'mask-overlay' in html
          and 'id="toggleMask"' in html)

# --- depth is opt-in --------------------------------------------------------
res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'no_depth.jpg'),
    'prompt': 'a plain bookshelf', 'position': 'middle_center', 'mode': 'zone',
    'detection_notes': 'Confidence: medium.',
}, content_type='multipart/form-data')
with web.app.app_context():
    plain = Design.query.filter_by(prompt='a plain bookshelf').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(plain.id if plain else None)
    if plain:
        DESIGN_FILES.append((plain.input_image, plain.mask_image, plain.output_image))
check('depth is opt-in',
      res.status_code == 302 and bool(plain)
      and plain.detection_notes == 'Confidence: medium.'
      and FakePipeline.last_prompt and 'depth cues:' not in FakePipeline.last_prompt,
      (plain.detection_notes if plain else None, FakePipeline.last_prompt))
if plain:
    html = client.get('/design/%d' % plain.id).get_data(as_text=True)
    check('no depth preview without opt-in', 'Relative depth preview' not in html)

# --- schema unchanged -------------------------------------------------------
with web.app.app_context():
    columns = [col['name'] for col in inspect(db.engine).get_columns('design')]
check('no depth column was added to design',
      'depth_map' not in columns and 'depth_hint' not in columns
      and 'detection_notes' in columns)

print('=' * 60)
print('DEPTH CHECK: %d passed, %d failed' % (len(PASS), len(FAIL)))
if FAIL:
    print('FAILURES:', FAIL)
print('=' * 60)
sys.exit(1 if FAIL else 0)
