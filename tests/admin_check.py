"""Verify admin verification, moderation and reports against live DB counts.

Runs in-process with Flask's test client (no server or AI model needed):
    python tests/admin_check.py
"""
import atexit
import os
import re
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

import app as web
from database import db, User, Design, Product, ShopProfile, Enquiry, ROLES
from prompt_builder import ROOM_TYPES, STYLES

PASS, FAIL = [], []


def check(label, ok, detail=''):
    (PASS if ok else FAIL).append(label)
    print(('PASS ' if ok else 'FAIL ') + label +
          ((' | ' + str(detail)) if detail else ''), flush=True)


def pair(html, label, count):
    return bool(re.search(
        r'<dt>\s*' + re.escape(label) + r'\s*</dt>\s*<dd>\s*' +
        str(count) + r'\s*</dd>', html, re.S))


web.app.config['TESTING'] = True
client = web.app.test_client()
suffix = uuid.uuid4().hex[:8]
usernames = {'admin': 'adminchk_a_' + suffix, 'customer': 'adminchk_c_' + suffix,
             'shop': 'adminchk_s_' + suffix}
product_name = 'Admin Check Lamp ' + suffix
image_name = 'admin_check_' + suffix + '.jpg'
ids, product_id, design_id = {}, None, None
image_path = os.path.join(ROOT, 'static', 'uploads', 'products', image_name)


def login_as(user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def cleanup():
    with web.app.app_context():
        db.session.query(Enquiry).filter(
            db.or_(Enquiry.customer_id.in_(ids.values()),
                   Enquiry.shop_owner_id.in_(ids.values()))).delete(
                       synchronize_session=False)
        db.session.query(ShopProfile).filter(
            ShopProfile.owner_id.in_(ids.values())).delete(synchronize_session=False)
        db.session.query(Product).filter(
            Product.owner_id.in_(ids.values())).delete(synchronize_session=False)
        db.session.query(Design).filter(
            Design.user_id.in_(ids.values())).delete(synchronize_session=False)
        db.session.query(User).filter(User.username.in_(usernames.values())).delete(
            synchronize_session=False)
        db.session.commit()
    try:
        os.remove(image_path)
    except OSError:
        pass


atexit.register(cleanup)

with web.app.app_context():
    for key, role in (('admin', 'admin'), ('customer', 'customer'),
                      ('shop', 'shop_owner')):
        user = User(username=usernames[key], email=usernames[key] + '@t.local',
                    password='unused', role=role)
        db.session.add(user)
        db.session.flush()
        ids[key] = user.id
    db.session.add(ShopProfile(owner_id=ids['shop'], shop_name='Admin Check Shop',
                               city='Bengaluru', verified=False))
    db.session.add(Product(owner_id=ids['shop'], name=product_name, category='Lighting',
                           price=1999, image_file=image_name, availability='in_stock'))
    db.session.add(Design(user_id=ids['customer'], input_image='a.jpg',
                          mask_image='m.jpg', output_image='o.jpg',
                          prompt='admin check design', position='middle_center',
                          room_type='living_room', style='modern'))
    db.session.flush()
    product_id = Product.query.filter_by(name=product_name).first().id
    design_id = Design.query.filter_by(prompt='admin check design').first().id
    db.session.add(Enquiry(product_id=product_id, customer_id=ids['customer'],
                           shop_owner_id=ids['shop'], design_id=design_id,
                           message='Please confirm delivery', kind='enquiry',
                           status='new'))
    db.session.add(Enquiry(product_id=product_id, customer_id=ids['customer'],
                           shop_owner_id=ids['shop'], message='Order placed',
                           kind='order', status='responded'))
    db.session.commit()
with open(image_path, 'wb') as fh:
    fh.write(b'fake image bytes')

# --- guards -----------------------------------------------------------------
anon = web.app.test_client()
for path in ('/admin/reports', '/admin/products'):
    check(path + ' blocks anonymous', anon.get(path).status_code == 302)
login_as(ids['customer'])
for path in ('/admin/reports', '/admin/products'):
    res = client.get(path)
    check(path + ' blocks customer',
          res.status_code == 302 and res.headers.get('Location', '').endswith('/dashboard'))

# --- reports match the database --------------------------------------------
login_as(ids['admin'])
with web.app.app_context():
    expected = {
        'roles': {key: User.query.filter_by(role=key).count() for key in ROLES},
        'users': User.query.count(),
        'shops': User.query.filter_by(role='shop_owner').count(),
        'products': Product.query.count(),
        'public': Product.query.filter(db.or_(Product.hidden.is_(False),
                                              Product.hidden.is_(None))).count(),
        'flagged': Product.query.filter_by(flagged=True).count(),
        'hidden': Product.query.filter_by(hidden=True).count(),
        'designs': Design.query.count(),
        'living': Design.query.filter_by(room_type='living_room').count(),
        'modern': Design.query.filter_by(style='modern').count(),
        'enquiries': Enquiry.query.count(),
        'new': Enquiry.query.filter_by(status='new').count(),
        'responded': Enquiry.query.filter_by(status='responded').count(),
        'orders': Enquiry.query.filter_by(kind='order').count(),
    }
res = client.get('/admin/reports')
html = res.get_data(as_text=True)
check('reports page opens', res.status_code == 200 and 'Platform reports' in html,
      res.status_code)
check('reports user counts match DB', res.status_code == 200 and all(
    pair(html, label, expected['roles'][role])
    for role, label in ROLES.items()), expected['roles'])
wanted = [('Total users', expected['users']), ('Shop owners', expected['shops']),
          ('Products', expected['products']), ('Public products', expected['public']),
          ('Flagged products', expected['flagged']),
          ('Hidden products', expected['hidden']), ('Designs', expected['designs']),
          (ROOM_TYPES['living_room'], expected['living']),
          (STYLES['modern'], expected['modern']),
          ('Enquiries', expected['enquiries']), ('New', expected['new']),
          ('Responded', expected['responded']), ('Orders', expected['orders'])]
missing = [label for label, count in wanted if not pair(html, label, count)]
check('reports all section counts match DB', not missing,
      missing or 'all matched')
check('reports activity panel', all(text in html for text in
      ('Pending shops', 'Recent designs', 'Recent enquiries')))
check('dashboard activity panel', all(text in
      client.get('/admin').get_data(as_text=True) for text in
      ('Pending shops', 'Recent designs', 'Recent enquiries')))

# --- verification from the shops list --------------------------------------
list_html = client.get('/admin/shops').get_data(as_text=True)
check('verify button on shops list', 'Verify' in list_html and 'Admin Check Shop' in list_html)
res = client.post('/admin/shops/%d/verify' % ids['shop'],
                  data={'verified': '1', 'next': '/admin/shops'})
check('admin verifies from list', res.status_code == 302 and
      res.headers.get('Location') == '/admin/shops',
      (res.status_code, res.headers.get('Location')))
with web.app.app_context():
    check('profile marked verified', ShopProfile.query.filter_by(
        owner_id=ids['shop']).first().verified is True)
login_as(ids['customer'])
check('customer sees verified product', product_name in
      client.get('/products').get_data(as_text=True))
detail = client.get('/products/%d' % product_id).get_data(as_text=True)
check('flag control offered to customer', 'Report this listing' in detail)
res = client.post('/products/%d/flag' % product_id)
check('customer flags product', res.status_code == 302)
with web.app.app_context():
    check('flag persisted', Product.query.get(product_id).flagged is True)

# --- moderation -------------------------------------------------------------
login_as(ids['admin'])
html = client.get('/admin/products').get_data(as_text=True)
check('moderation queue shows flagged item', 'Flagged' in html and product_name in html)
res = client.post('/admin/products/%d/moderate' % product_id, data={'action': 'hide'})
check('admin hides product', res.status_code == 302)
with web.app.app_context():
    check('hidden persisted', Product.query.get(product_id).hidden is True)
login_as(ids['customer'])
check('hidden product not in catalogue', product_name not in
      client.get('/products').get_data(as_text=True))
check('hidden product detail 404', client.get('/products/%d' % product_id).status_code == 404)
login_as(ids['admin'])
client.post('/admin/products/%d/moderate' % product_id, data={'action': 'unhide'})
with web.app.app_context():
    restored = Product.query.get(product_id)
    check('unhide restores and clears flag',
          restored.hidden is False and restored.flagged is False)
login_as(ids['customer'])
check('restored product visible again', product_name in
      client.get('/products').get_data(as_text=True))
login_as(ids['admin'])
check('unknown moderation action rejected',
      client.post('/admin/products/%d/moderate' % product_id,
                  data={'action': 'bogus'}).status_code == 400)
res = client.post('/admin/products/%d/moderate' % product_id,
                  data={'action': 'remove'})
check('admin removes product', res.status_code == 302)
with web.app.app_context():
    check('product and enquiries removed',
          Product.query.get(product_id) is None and
          Enquiry.query.filter_by(product_id=product_id).count() == 0)
check('product image removed', not os.path.exists(image_path))

# Revoke verification once more to prove the list button works both ways.
res = client.post('/admin/shops/%d/verify' % ids['shop'],
                  data={'verified': '0', 'next': '/admin/shops'})
with web.app.app_context():
    check('admin can revoke verification', res.status_code == 302 and
          ShopProfile.query.filter_by(owner_id=ids['shop']).first().verified is False)

cleanup()
print('\nSUMMARY:', len(PASS), 'passed,', len(FAIL), 'failed')
if FAIL:
    print('FAILED:', FAIL)
    raise SystemExit(1)
