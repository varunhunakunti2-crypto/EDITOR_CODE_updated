"""Full Step 2 -> 3 -> 4 browser flow: analyze a room, generate, review result.

Run from the project folder while the server is up:
    python tests/flow_check.py

Uses a real browser and the real inpainting model (12 steps by default), so it
takes longer than the other suites. All demo data is removed on exit.
"""
import atexit
import os
import re
import sqlite3
import sys
import time
import uuid

from playwright.sync_api import sync_playwright

from smoke_test import BASE, DB, openers, post

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


def register_customer():
    follow, strict = openers()
    username = 'flow_' + uuid.uuid4().hex[:8]
    post(follow, '/register', {'username': username, 'email': username + '@t.local',
                               'password': 'pass123', 'role': 'customer'})
    post(strict, '/login', {'username': username, 'password': 'pass123'})
    with sqlite3.connect(DB) as con:
        user_id = con.execute('SELECT id FROM user WHERE username=?', (username,)).fetchone()[0]
    return username, user_id


def login(page, username):
    page.goto(BASE + '/login', timeout=30000)
    page.fill('#username', username)
    page.fill('#password', 'pass123')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')


username, user_id = register_customer()
state = {'design_id': None, 'overlay': None}


def cleanup():
    files = []
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            'SELECT input_image, mask_image, output_image FROM design WHERE user_id=?',
            (user_id,)).fetchall()
        files.extend(rows)
        con.execute('DELETE FROM design WHERE user_id=?', (user_id,))
        con.execute('DELETE FROM user WHERE id=?', (user_id,))
        con.commit()
    for triple in files:
        for folder, name in zip(('input', 'mask', 'output'), triple):
            for base in ('uploads', os.path.join('static', 'uploads')):
                try:
                    os.remove(os.path.join(base, folder, name))
                except OSError:
                    pass
    if state['overlay']:
        try:
            os.remove(os.path.join('static', 'uploads', 'analysis',
                                   os.path.basename(state['overlay'].split('?')[0])))
        except OSError:
            pass


atexit.register(cleanup)


def main():
    for _ in range(40):
        try:
            open(BASE + '/model-status').read()
            break
        except Exception:
            time.sleep(1)

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)

        login(page, username)
        page.goto(BASE + '/design', timeout=30000)
        page.wait_for_selector('#designForm')
        check('room type choices present', all(page.locator(
            'select[name=room_type] option[value="%s"]' % value).count() == 1
            for value in ('bedroom', 'kitchen', 'living_room', 'other')))
        check('style, budget, preferences fields present', all(page.locator(sel).count() == 1
              for sel in ('select[name=style]', 'input[name=budget]',
                          'textarea[name=preferences]')))
        check('Analyze room control present',
              page.locator('#referencePixels').count() == 1 and
              'Analyze room' in page.locator('#measureBtn').inner_text())

        # Step 2: room analysis from a photo with a known reference length.
        page.set_input_files('#imageInput', 'sample.jpg')
        page.fill('#referencePixels', '200')
        page.click('#measureBtn')
        page.wait_for_function("document.getElementById('widthM').value !== ''",
                               timeout=90000)
        dims = page.evaluate("['widthM','lengthM','heightM'].map(id => document.getElementById(id).value)")
        summary = page.locator('#detectedSummary').inner_text()
        state['overlay'] = page.locator('#analysisOverlay').get_attribute('src')
        check('detected dimensions displayed',
              len(dims) == 3 and all(float(v) > 0 for v in dims) and 'Detected:' in summary,
              (dims, summary[:90]))
        check('analysis overlay displayed', page.locator('#analysisOverlay').is_visible())

        # Step 3: fill the room brief and generate a design.
        page.fill('#prompt', 'a walnut bookshelf')
        page.select_option('select[name=room_type]', 'living_room')
        page.select_option('select[name=style]', 'modern')
        page.fill('input[name=budget]', '50000 INR')
        page.fill('textarea[name=preferences]', 'pet friendly, warm colours')
        page.check('input[name=position][value=top_left]')
        page.click('#submitBtn', no_wait_after=True)
        page.wait_for_url(re.compile(r'/design/\d+$'), timeout=300000)
        state['design_id'] = int(page.url.rstrip('/').split('/')[-1])
        check('design generated and result opened', state['design_id'] > 0, page.url)

        # Step 4: verify the persisted fields and accuracy disclaimer.
        body = page.locator('body').inner_text()
        expected_dims = ['W %.2f m' % float(dims[0]), 'L %.2f m' % float(dims[1]),
                         'H %.2f m' % float(dims[2])]
        check('result shows detected dimensions', all(v in body for v in expected_dims),
              [v for v in expected_dims if v not in body])
        check('result shows style and budget',
              'Style: Modern' in body and 'Budget: 50000 INR' in body)
        check('result shows accuracy disclaimer',
              'approximate' in body and 'Verify important measurements' in body)
        check('result shows save placement control',
              page.locator('[data-save-placement]').count() == 1)

        page.click('[data-save-placement]')
        page.wait_for_function(
            "document.querySelector('[data-placement-status]').textContent.includes('Saved')",
            timeout=10000)
        check('placement saved from browser',
              'Saved 0 placed item(s).' in page.locator('[data-placement-status]').inner_text(),
              page.locator('[data-placement-status]').inner_text())
        check('no browser errors', not errors, errors[:3])
        browser.close()

    print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
    if FAIL:
        print('FAILED:', FAIL)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
