"""Verify the new design API, prompt builder, whole-room mode and placement.

Runs in-process with a stubbed image pipeline, so no 30-60 s diffusion or API
keys are needed. Run from the project folder while the Flask server may or may
not be running:  python tests/backend_check.py
"""
import atexit
import io
import json
import os
import sys
import uuid
from types import SimpleNamespace

from PIL import Image
from sqlalchemy import inspect

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app as web
from database import db, User, Design, upgrade_schema
from masking import build_custom_mask, build_mask, parse_coords
from prompt_builder import build_prompt

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


class FakePipeline:
    """Stand-in for Stable Diffusion: returns the input image unchanged."""
    last_prompt = None

    def __call__(self, prompt, image, mask_image, **kwargs):
        FakePipeline.last_prompt = prompt
        return SimpleNamespace(images=[image.copy()])


web.get_pipe = lambda: FakePipeline()
web.app.config['TESTING'] = True
client = web.app.test_client()


def login_as(user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def room_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (640, 480), (232, 228, 222)).save(buf, 'JPEG')
    return buf.getvalue()


IMAGE = room_bytes()
OVERLAYS, DESIGN_IDS, DESIGN_FILES = [], [], []
suffix = uuid.uuid4().hex[:8]
created_usernames = []

FOLDERS = ('input', 'mask', 'output')


def white_box_ok(mask, box):
    """Check a mask saved as JPEG without depending on compression edges."""
    gray = mask.convert('L')
    width, height = gray.size
    x1, y1, x2, y2 = box
    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
    probes = [
        ((mx, my), True),
        ((max(0, x1 - 6), my), False),
        ((min(width - 1, x2 + 6), my), False),
        ((mx, max(0, y1 - 6)), False),
        ((mx, min(height - 1, y2 + 6)), False),
    ]
    return all((gray.getpixel(point) >= 180) == wanted
               for point, wanted in probes)


def cleanup():
    """Always remove this script's users, designs and uploaded files."""
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
        for folder, filename in zip(FOLDERS, triple):
            for base in (os.path.join(ROOT, 'uploads'),
                         os.path.join(ROOT, 'static', 'uploads')):
                try:
                    os.remove(os.path.join(base, folder, filename))
                except OSError:
                    pass
    for path in OVERLAYS:
        try:
            os.remove(path)
        except OSError:
            pass


atexit.register(cleanup)

with web.app.app_context():
    ids = {}
    for role in ('customer', 'other', 'admin'):
        username = 'api_test_%s_%s' % (role, suffix)
        created_usernames.append(username)
        user = User(username=username, email=username + '@t.local',
                    password='unused', role=role)
        db.session.add(user)
        db.session.flush()
        ids[role] = user.id
    db.session.commit()

# --- schema upgrades are idempotent ---------------------------------------
with web.app.app_context():
    before_columns = [c['name'] for c in inspect(db.engine).get_columns('design')]
    before_count = Design.query.count()
    upgrade_schema()
    upgrade_schema()
    after_columns = [c['name'] for c in inspect(db.engine).get_columns('design')]
    after_count = Design.query.count()
check('upgrade_schema is idempotent',
      before_columns == after_columns and before_count == after_count
      and 'mask_coords' in after_columns,
      (before_count, after_count, 'mask_coords' in after_columns))

# --- prompt builder -------------------------------------------------------
full = build_prompt('a walnut bookshelf', room_type='living_room', style='modern',
                    budget='₹50,000', preferences='pet friendly',
                    width_m=5.25, length_m=6.5, height_m=2.8)
check('prompt includes every field', all(part in full for part in (
    'walnut bookshelf', 'living room', 'modern', '₹50,000',
    'pet friendly', '5.25 m', '6.50 m', '2.80 m')), full)
check('whole-room prompt differs',
      'Redesign the entire visible room' in build_prompt('a cosy sofa', whole_room=True))
check('bare prompt stays short', build_prompt('a lamp') == 'a lamp.')
try:
    build_prompt('')
    check('empty prompt rejected', False)
except ValueError:
    check('empty prompt rejected', True)

# --- custom mask helpers ---------------------------------------------------
check('custom position is registered',
      'custom' in web.masking.POSITIONS and
      web.masking.normalize_position(' CUSTOM ') == 'custom' and
      web.masking.LABELS['custom'] == 'Custom area')
check('valid coords parse to fractions',
      parse_coords(' 25, 25, 75, 75 ') == (0.25, 0.25, 0.75, 0.75),
      parse_coords(' 25, 25, 75, 75 '))
check('parsed tuple is accepted again',
      parse_coords(parse_coords('25,25,75,75')) == (0.25, 0.25, 0.75, 0.75))
for label, value in [
    ('missing', None), ('empty', ''), ('partial', '25,25,75'),
    ('non numeric', 'a,25,75,75'), ('out of bounds', '-1,25,75,75'),
    ('above bounds', '25,25,175,75'), ('reversed', '75,25,25,75'),
    ('too small', '10,10,15,15'), ('too large', '2,2,98,98'),
]:
    check('coords rejected: ' + label, parse_coords(value) is None, value)

custom_mask = build_custom_mask('25,25,75,75', (512, 512))
check('custom mask has white box at coords',
      custom_mask.convert('L').getbbox() == (128, 128, 384, 384),
      custom_mask.convert('L').getbbox())
fallback = build_custom_mask('10,10,15,15', (512, 512))
check('invalid custom mask falls back to centre',
      fallback.tobytes() == build_mask('middle_center', (512, 512)).tobytes())

# --- /api/analyze-room ----------------------------------------------------
anon = web.app.test_client()
check('analyze-room requires login',
      anon.post('/api/analyze-room', data={'image': (io.BytesIO(IMAGE), 'room.jpg')},
                content_type='multipart/form-data').status_code == 302)

login_as(ids['customer'])
res = client.post('/api/analyze-room', data={
    'image': (io.BytesIO(IMAGE), 'room.jpg'), 'reference_pixels': '200',
}, content_type='multipart/form-data')
try:
    data = json.loads(res.data)
except ValueError:
    data = {}
check('analyze-room returns 200 JSON', res.status_code == 200 and 'width_m' in data,
      (res.status_code, data))
check('analyze-room dimensions plausible',
      1 < data.get('width_m', 0) < 20 and 1.5 < data.get('height_m', 0) < 8
      and 0.5 < data.get('length_m', 0) < 40,
      [data.get(k) for k in ('width_m', 'length_m', 'height_m')])
overlay_name = os.path.basename(data.get('overlay_url', ''))
overlay_path = os.path.join(ROOT, 'static', 'uploads', 'analysis', overlay_name)
OVERLAYS.append(overlay_path)
check('analyze-room overlay written',
      bool(overlay_name) and os.path.isfile(overlay_path) and
      os.path.getsize(overlay_path) > 1000, overlay_url if (overlay_url := data.get('overlay_url')) else '')

res = client.post('/api/analyze-room', data={
    'image': (io.BytesIO(b'not an image'), 'bad.txt')},
    content_type='multipart/form-data')
check('analyze-room rejects invalid file', res.status_code == 400, res.status_code)
res = client.post('/api/analyze-room', data={}, content_type='multipart/form-data')
check('analyze-room rejects missing image', res.status_code == 400, res.status_code)

# --- /design form ---------------------------------------------------------
res = client.get('/design')
html = res.get_data(as_text=True)
check('design form exposes new fields', res.status_code == 200 and all(
    text in html for text in ('name="room_type"', 'name="style"', 'name="budget"',
                              'name="preferences"', 'name="width_m"', 'name="length_m"',
                              'name="height_m"', 'name="detection_notes"',
                              'value="whole"', 'value="custom"', 'Custom area',
                               'name="coords"', 'api/analyze-room')))

res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'room.jpg'),
    'prompt': 'a walnut bookshelf', 'position': 'top_left', 'mode': 'zone',
    'room_type': 'living_room', 'style': 'modern', 'budget': '₹50,000',
    'preferences': 'pet friendly, warm colours',
    'width_m': '5.25', 'length_m': '6.5', 'height_m': '2.8',
    'detection_notes': 'Confidence: high. Walls detected.',
}, content_type='multipart/form-data')
check('design POST redirects to result', res.status_code == 302 and '/design/' in
      (res.headers.get('Location') or ''), (res.status_code, res.headers.get('Location')))

with web.app.app_context():
    d = Design.query.filter_by(prompt='a walnut bookshelf').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(d.id if d else None)
    if d:
        DESIGN_FILES.append((d.input_image, d.mask_image, d.output_image))
    row = (d.room_type, d.style, d.budget, d.preferences, d.width_m, d.length_m,
           d.height_m, d.detection_notes, d.position) if d else None
check('design row has all new fields', row == (
    'living_room', 'modern', '₹50,000', 'pet friendly, warm colours',
    5.25, 6.5, 2.8, 'Confidence: high. Walls detected.', 'top_left'), row)
check('generation prompt combines fields', FakePipeline.last_prompt and all(
    part in FakePipeline.last_prompt for part in (
        'walnut bookshelf', 'living room', 'modern', '₹50,000',
        'pet friendly', '5.25 m', '6.50 m', '2.80 m')), FakePipeline.last_prompt)

res = client.get('/design/%d' % d.id)
html = res.get_data(as_text=True)
wanted_page = ('a walnut bookshelf', 'Living room', '₹50,000',
               'pet friendly, warm colours', 'W 5.25 m',
               'Confidence: high', 'Save placement')
missing = [text for text in wanted_page if text not in html]
check('result page shows room details', res.status_code == 200 and not missing,
      missing or res.status_code)

# --- whole-room mode ------------------------------------------------------
res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'whole.jpg'),
    'prompt': 'a calm modern living room', 'mode': 'whole',
}, content_type='multipart/form-data')
with web.app.app_context():
    whole = Design.query.filter_by(prompt='a calm modern living room').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(whole.id if whole else None)
    if whole:
        DESIGN_FILES.append((whole.input_image, whole.mask_image, whole.output_image))
    mask_name = whole.mask_image if whole else None
check('whole-room design saved', res.status_code == 302 and bool(whole)
      and whole.position == 'whole_room', (res.status_code,
                                           whole.position if whole else None))
check('whole-room prompt flagged', FakePipeline.last_prompt and
      'Redesign the entire visible room' in FakePipeline.last_prompt,
      FakePipeline.last_prompt)
if mask_name:
    mask = Image.open(os.path.join(ROOT, 'static', 'uploads', 'mask', mask_name))
    check('whole-room mask is fully white',
          all(ext[0] == ext[1] == 255 for ext in mask.getextrema()),
          mask.getextrema())

# --- custom area design ---------------------------------------------------
res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'custom.jpg'),
    'prompt': 'a custom area bookshelf', 'position': 'custom',
    'coords': '25,25,75,75', 'mode': 'zone',
}, content_type='multipart/form-data')
with web.app.app_context():
    custom_design = Design.query.filter_by(prompt='a custom area bookshelf').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(custom_design.id if custom_design else None)
    if custom_design:
        DESIGN_FILES.append((custom_design.input_image, custom_design.mask_image,
                             custom_design.output_image))
check('custom design saved', res.status_code == 302 and bool(custom_design)
      and custom_design.position == 'custom',
      (res.status_code, custom_design.position if custom_design else None))
stored_coords = custom_design.mask_coords if custom_design else None
check('custom coords stored on design', stored_coords == '25,25,75,75', stored_coords)
if custom_design:
    mask = Image.open(os.path.join(ROOT, 'static', 'uploads', 'mask',
                                   custom_design.mask_image))
    check('custom design mask matches coords', white_box_ok(mask, (128, 128, 383, 383)))
    html = client.get('/design/%d' % custom_design.id).get_data(as_text=True)
    check('result page labels custom area', 'custom area' in html.lower())

res = client.post('/design', data={
    'image': (io.BytesIO(IMAGE), 'fallback.jpg'),
    'prompt': 'a fallback bookshelf', 'position': 'custom',
    'coords': '10,10,15,15', 'mode': 'zone',
}, content_type='multipart/form-data')
with web.app.app_context():
    fallback_design = Design.query.filter_by(prompt='a fallback bookshelf').order_by(
        Design.id.desc()).first()
    DESIGN_IDS.append(fallback_design.id if fallback_design else None)
    if fallback_design:
        DESIGN_FILES.append((fallback_design.input_image, fallback_design.mask_image,
                             fallback_design.output_image))
check('invalid custom coords fall back to centre',
      res.status_code == 302 and bool(fallback_design)
      and fallback_design.position == 'middle_center',
      (res.status_code, fallback_design.position if fallback_design else None))
check('invalid custom coords not stored',
      bool(fallback_design) and not fallback_design.mask_coords,
      fallback_design.mask_coords if fallback_design else None)
if fallback_design:
    mask = Image.open(os.path.join(ROOT, 'static', 'uploads', 'mask',
                                   fallback_design.mask_image))
    expected_box = web.masking.mask_box('middle_center', 512)
    check('fallback mask is centre zone', white_box_ok(mask, expected_box),
          expected_box)

# --- /design/<id>/placement ----------------------------------------------
url = '/design/%d/placement' % d.id
payload = {'items': [{
    'src': '/static/uploads/products/lamp.jpg', 'name': 'Lamp',
    'rx': 0.91, 'ry': 2.0, 'scale': 5, 'rotation': 725,
}]}
login_as(ids['other'])
check('placement rejects non-owner', client.post(url, json=payload).status_code == 403)
login_as(ids['customer'])
res = client.post(url, json=payload)
check('placement saves for owner', res.status_code == 200 and
      json.loads(res.data).get('count') == 1, (res.status_code, res.data[:120]))
with web.app.app_context():
    saved = json.loads(Design.query.get(d.id).placement_json)
check('placement values validated', saved['items'][0] == {
    'src': '/static/uploads/products/lamp.jpg', 'name': 'Lamp',
    'rx': 0.91, 'ry': 1.0, 'scale': 0.7, 'rotation': 5.0}, saved)
login_as(ids['admin'])
check('placement allows admin',
      client.post(url, json={'items': []}).status_code == 200)
check('placement rejects malformed JSON',
      client.post(url, data='not json', content_type='application/json').status_code == 400)
html = client.get('/design/%d' % d.id).get_data(as_text=True)
check('result page includes saved placement',
      'saved-placement' in html and '"items": []' in html,
      'empty after admin cleared')

# --- cleanup (also registered with atexit in case of an early failure) -----
cleanup()

print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
if FAIL:
    print('FAILED:', FAIL)
    raise SystemExit(1)
