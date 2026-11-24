"""Browser verification of the shop verification and catalogue workflow.

Run from the project folder while the server is up:
    python tests/shop_flow_check.py

Covers: register shop -> pending -> admin verifies -> product visible, then
editing, availability and the enquiry inbox. Demo data is removed on exit.
"""
import atexit
import os
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


def make_user(prefix, role):
    follow, strict = openers()
    username = prefix + uuid.uuid4().hex[:6]
    post(follow, '/register', {'username': username, 'email': username + '@t.local',
                               'password': 'pass123', 'role': role})
    post(strict, '/login', {'username': username, 'password': 'pass123'})
    return username


def login(page, username):
    page.goto(BASE + '/login', timeout=30000)
    page.fill('#username', username)
    page.fill('#password', 'pass123')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')


suffix = uuid.uuid4().hex[:6]
admin_u = make_user('shopflow_admin_', 'customer')
shop_u = make_user('shopflow_shop_', 'shop_owner')
cust_u = make_user('shopflow_cust_', 'customer')
shop_name = 'Flow Interiors ' + suffix
product_name = 'Flow Lamp ' + suffix
state = {'product_id': None, 'images': []}

with sqlite3.connect(DB) as con:
    admin_id = con.execute('SELECT id FROM user WHERE username=?', (admin_u,)).fetchone()[0]
    shop_id = con.execute('SELECT id FROM user WHERE username=?', (shop_u,)).fetchone()[0]
    con.execute("UPDATE user SET role='admin' WHERE id=?", (admin_id,))
_, admin_strict = openers()
post(admin_strict, '/login', {'username': admin_u, 'password': 'pass123'})


def cleanup():
    with sqlite3.connect(DB) as con:
        ids = [con.execute('SELECT id FROM user WHERE username=?', (u,)).fetchone()[0]
               for u in (admin_u, shop_u, cust_u)]
        marks = ','.join('?' * len(ids))
        con.execute(f'DELETE FROM enquiry WHERE customer_id IN ({marks}) '
                    f'OR shop_owner_id IN ({marks})', ids + ids)
        con.execute(f'DELETE FROM shop_profile WHERE owner_id IN ({marks})', ids)
        con.execute(f'DELETE FROM product WHERE owner_id IN ({marks})', ids)
        con.execute(f'DELETE FROM design WHERE user_id IN ({marks})', ids)
        con.execute(f'DELETE FROM user WHERE id IN ({marks})', ids)
        con.commit()
    for name in state['images']:
        try:
            os.remove(os.path.join('static', 'uploads', 'products', name))
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

    errors, bad = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 else None)

        # 1. Shop registers -> pending.
        login(page, shop_u)
        page.goto(BASE + '/shop/profile')
        page.fill('#shop_name', shop_name)
        page.fill('#city', 'Bengaluru')
        page.fill('#phone', '9876543210')
        page.fill('#address', '12 Test Street, Bengaluru')
        page.click('button[type=submit]')
        page.wait_for_url(BASE + '/shop')
        check('shop profile submitted as pending',
              'Pending verification' in page.locator('body').inner_text())

        # 2. Product added while pending is visible only to its owner.
        page.goto(BASE + '/shop/products/add')
        page.fill('#name', product_name)
        page.fill('#category', 'Lighting')
        page.fill('#price', '2499')
        page.fill('#description', 'A warm brass floor lamp.')
        page.set_input_files('input[name=image]', 'sample.jpg')
        page.click('button[type=submit]')
        page.wait_for_url(BASE + '/shop/products')
        check('owner sees pending product', product_name in page.locator('body').inner_text())
        with sqlite3.connect(DB) as con:
            row = con.execute('SELECT id, image_file FROM product WHERE name=?',
                              (product_name,)).fetchone()
        state['product_id'], image_file = row
        state['images'].append(image_file)

        login(page, cust_u)
        page.goto(BASE + '/products')
        check('pending product hidden from customers',
              product_name not in page.locator('body').inner_text())

        # 3. Admin verifies the shop.
        login(page, admin_u)
        page.goto(BASE + '/admin/shops')
        row = page.locator('tr', has_text=shop_name)
        check('admin sees pending shop', 'Pending' in row.inner_text(), row.inner_text()[:90])
        row.get_by_role('link', name='View catalogue →').click()
        page.wait_for_selector('button:has-text("Verify shop")')
        page.click('button:has-text("Verify shop")')
        page.wait_for_load_state('networkidle')
        check('admin verified shop', 'Verified' in page.locator('body').inner_text())

        # 4. Product is now publicly listed; customer sends an enquiry.
        login(page, cust_u)
        page.goto(BASE + '/products')
        body = page.locator('body').inner_text()
        check('verified product visible', product_name in body)
        check('catalogue shows verified shop', shop_name in body and 'Bengaluru' in body)
        page.goto(BASE + '/products/' + str(state['product_id']))
        body = page.locator('body').inner_text()
        check('detail shows verified shop contact', all(text in body for text in
              (shop_name, 'Bengaluru', '9876543210', shop_u + '@t.local')))
        check('ask shop owner form present', 'Ask shop owner' in body)
        page.fill('#message', 'Do you deliver this week?')
        page.check('input[name=kind][value=order]')
        page.click('button:has-text("Send to shop")')
        page.wait_for_load_state('networkidle')
        check('customer enquiry sent',
              'Your order was sent' in page.locator('body').inner_text())
        page.goto(BASE + '/my/enquiries')
        body = page.locator('body').inner_text()
        check('customer sees new enquiry',
              'Do you deliver this week?' in body and 'New' in body)
        with sqlite3.connect(DB) as con:
            enq = con.execute('SELECT id, kind, status FROM enquiry WHERE product_id=?',
                              (state['product_id'],)).fetchone()
        check('order stored as new', enq and enq[1] == 'order' and enq[2] == 'new', enq)

        # 5. Owner replies in the inbox.
        login(page, shop_u)
        page.goto(BASE + '/shop/enquiries')
        check('owner inbox shows message',
              'Do you deliver this week?' in page.locator('body').inner_text())
        page.select_option('select[name=status]', 'responded')
        page.click('button:has-text("Update")')
        page.wait_for_load_state('networkidle')
        with sqlite3.connect(DB) as con:
            status = con.execute('SELECT status FROM enquiry WHERE id=?', (enq[0],)).fetchone()[0]
        check('enquiry status updated', status == 'responded', status)

        login(page, cust_u)
        page.goto(BASE + '/my/enquiries')
        body = page.locator('body').inner_text()
        check('customer sees responded status',
              'Do you deliver this week?' in body and 'Responded' in body)

        # 6. Owner edits the product and changes availability.
        login(page, shop_u)
        page.goto(BASE + '/shop/products')
        card = page.locator('.product-card', has_text=product_name)
        card.get_by_role('link', name='Edit details').click()
        page.fill('#description', 'Updated: matte black finish.')
        page.fill('#price', '2799')
        page.click('button:has-text("Save changes")')
        page.wait_for_url(BASE + '/shop/products')
        check('product edit saved in browser',
              'Updated: matte black finish.' in page.locator('body').inner_text() and
              '2799.00' in page.locator('body').inner_text())
        card = page.locator('.product-card', has_text=product_name)
        card.locator('select[name=availability]').select_option('out_of_stock')
        card.get_by_role('button', name='Update').click()
        page.wait_for_load_state('networkidle')
        check('availability toggled in browser',
              'Out of stock' in page.locator('.product-card', has_text=product_name).inner_text())
        with sqlite3.connect(DB) as con:
            availability = con.execute('SELECT availability FROM product WHERE id=?',
                                       (state['product_id'],)).fetchone()[0]
        check('availability persisted', availability == 'out_of_stock', availability)

        check('no browser errors', not errors, errors[:3])
        check('no failed resources', not bad, bad[:3])
        browser.close()

    print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
    if FAIL:
        print('FAILED:', FAIL)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
