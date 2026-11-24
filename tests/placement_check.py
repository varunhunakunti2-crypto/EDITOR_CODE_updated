"""Browser verification for rotated furniture placement.

Run from the project folder while the server is up:
    python tests/placement_check.py

Uses the same temporary demo data as browser_check.py. It places, moves,
resizes and rotates an item, saves it, reloads the design, and checks that the
restored layout produces the same downloaded PNG.
"""
import json
import os
import sqlite3
import sys
import tempfile

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

from browser_check import cleanup, setup_demo, login
from smoke_test import BASE, DB

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


def read_state(page):
    return page.locator('.placed-item').first.evaluate("""el => ({
        rx: parseFloat(el.dataset.rx),
        ry: parseFloat(el.dataset.ry),
        scale: parseFloat(el.dataset.scale),
        rotation: parseFloat(el.dataset.rotation),
        transform: el.style.transform,
    })""")


def near(a, b, tol=0.0002):
    return abs(float(a) - float(b)) <= tol


def main():
    demo = setup_demo()
    errors, bad = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000},
                                    accept_downloads=True)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)

            login(page, demo['cust'])
            page.goto(BASE + '/design/' + str(demo['design_id']))
            page.wait_for_selector('[data-placement]')
            page.locator('.palette-item[data-src]').first.click()
            page.wait_for_selector('.placed-item')
            item = page.locator('.placed-item').first
            check('place adds a rotated-capable item',
                  item.locator('.rotate-left').count() == 1 and
                  item.locator('.rotate-right').count() == 1)

            # Move the item away from the centre.
            canvas_box = page.locator('[data-canvas]').bounding_box()
            box = item.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(canvas_box['x'] + canvas_box['width'] * 0.62,
                            canvas_box['y'] + canvas_box['height'] * 0.58,
                            steps=15)
            page.mouse.up()

            # Resize with the wheel, then rotate with buttons and Shift+wheel.
            box = item.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            for _ in range(3):
                page.mouse.wheel(0, -120)
            item.locator('.rotate-right').click()
            item.locator('.rotate-right').click()
            box = item.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.keyboard.down('Shift')
            page.mouse.wheel(0, -120)
            page.keyboard.up('Shift')

            before = read_state(page)
            check('item moved', near(before['rx'], 0.62, 0.03) and
                  near(before['ry'], 0.58, 0.03), before)
            check('item resized', before['scale'] > 0.18 + 0.02, before['scale'])
            check('item rotated by buttons and Shift+wheel',
                  near(before['rotation'], 45, 0.01) and
                  'rotate(45deg)' in before['transform'], before)
            os.makedirs(os.path.join('docs', 'screenshots'), exist_ok=True)
            page.screenshot(path=os.path.join('docs', 'screenshots',
                                              '17-result-rotated.png'),
                            full_page=True)

            page.click('[data-save-placement]')
            page.wait_for_function(
                "document.querySelector('[data-placement-status]').textContent.includes('Saved')",
                timeout=10000)
            check('rotated arrangement saved in browser',
                  'Saved 1 placed item(s).' in
                  page.locator('[data-placement-status]').inner_text())
            with sqlite3.connect(DB) as con:
                raw = con.execute('SELECT placement_json FROM design WHERE id=?',
                                  (demo['design_id'],)).fetchone()[0]
                output_image = con.execute('SELECT output_image FROM design WHERE id=?',
                                           (demo['design_id'],)).fetchone()[0]
            stored = json.loads(raw)['items']
            check('rotation persisted in DB', len(stored) == 1 and
                  near(stored[0]['rotation'], 45, 0.01) and
                  near(stored[0]['scale'], before['scale']) and
                  near(stored[0]['rx'], before['rx']) and
                  near(stored[0]['ry'], before['ry']), stored)

            with tempfile.TemporaryDirectory() as tmp:
                first_png = os.path.join(tmp, 'before.png')
                with page.expect_download() as info:
                    page.click('[data-download-placement]')
                info.value.save_as(first_png)
                page.wait_for_function(
                    "document.querySelector('[data-placement-status]').textContent.includes('Downloaded')",
                    timeout=15000)

                # Reopen the design; the saved rotation must come back too.
                page.reload()
                page.wait_for_load_state('networkidle')
                page.wait_for_selector('.placed-item')
                after = read_state(page)
                check('layout restored after reload',
                      all(near(after[key], before[key]) for key in
                          ('rx', 'ry', 'scale', 'rotation')) and
                      'rotate(45deg)' in after['transform'], after)

                second_png = os.path.join(tmp, 'after.png')
                with page.expect_download() as info:
                    page.click('[data-download-placement]')
                info.value.save_as(second_png)
                page.wait_for_function(
                    "document.querySelector('[data-placement-status]').textContent.includes('Downloaded')",
                    timeout=15000)

                with Image.open(first_png) as a, Image.open(second_png) as b:
                    same = (a.size == b.size and
                            a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes())
                    size = a.size
                check('downloaded PNG matches restored layout', same, size)

                with Image.open(second_png) as rendered, Image.open(
                        os.path.join('static', 'uploads', 'output', output_image)) as base:
                    changed = (rendered.size == base.size and
                               ImageChops.difference(rendered.convert('RGB'),
                                                     base.convert('RGB')).getbbox() is not None)
                check('download includes the placed item', changed)

            # Remove and clear still work on rotated items.
            page.locator('.placed-item .remove').click()
            check('remove works on rotated item', page.locator('.placed-item').count() == 0)
            page.locator('.palette-item[data-src]').first.click()
            page.locator('.placed-item .rotate-right').click()
            page.locator('.palette-item[data-src]').first.click()
            check('two rotated items placed', page.locator('.placed-item').count() == 2)
            page.click('[data-clear-placement]')
            check('clear removes rotated items',
                  page.locator('.placed-item').count() == 0 and
                  'Placement cleared' in page.locator('[data-placement-status]').inner_text())

            check('no browser errors', not errors, errors[:3])
            check('no failed resources', not bad, bad[:3])
            browser.close()
    finally:
        cleanup(demo)

    print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
    if FAIL:
        print('FAILED:', FAIL)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
