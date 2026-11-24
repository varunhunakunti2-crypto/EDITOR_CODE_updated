import os
import json
import tempfile
import threading
from datetime import datetime
from functools import wraps
import torch
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
from diffusers import StableDiffusionInpaintPipeline, DPMSolverMultistepScheduler
from sqlalchemy import or_
from database import (db, User, Design, Product, ShopProfile, Enquiry,
                      upgrade_schema, ROLES, SIGNUP_ROLES, AVAILABILITY,
                      ENQUIRY_KINDS, ENQUIRY_STATUSES)
import uuid
import config
import masking
import places
import room_analysis
from prompt_builder import build_prompt, describe_room, ROOM_TYPES, STYLES

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///interior_design.db'
app.config['UPLOAD_FOLDER'] = os.path.join(config.BASE_DIR, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


def role_required(*roles):
    """Require login plus one of the given roles. Admins can access everything."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not (current_user.has_role(*roles) or current_user.is_admin):
                flash('You do not have access to that page.', 'error')
                return redirect(url_for('dashboard'))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def verified_shop_ids():
    """Owner IDs whose shop profile has been approved by an admin."""
    return [row[0] for row in db.session.query(ShopProfile.owner_id).filter_by(
        verified=True).all()]


def visible_products():
    """Catalogue query: verified shops only, plus the owner's own pending items."""
    query = Product.query.filter(or_(Product.hidden.is_(False),
                                     Product.hidden.is_(None)))
    if current_user.is_admin:
        return query
    ids = verified_shop_ids()
    if current_user.is_authenticated and current_user.role == 'shop_owner':
        return query.filter(or_(Product.owner_id == current_user.id,
                                Product.owner_id.in_(ids)))
    return query.filter(Product.owner_id.in_(ids))


def shop_profile_for(owner_id):
    return ShopProfile.query.filter_by(owner_id=owner_id).first()


def shop_snapshot(owner_id):
    """Public-facing shop identity and contact details for a product owner."""
    profile = shop_profile_for(owner_id)
    owner = db.session.get(User, owner_id)
    return {
        'profile': profile,
        'owner': owner,
        'name': (profile.shop_name if profile and profile.shop_name else
                 (owner.username if owner else '')),
        'city': profile.city if profile else '',
        'address': profile.address if profile else '',
        'phone': profile.phone if profile else '',
        'email': owner.email if owner else '',
        'verified': bool(profile and profile.verified),
    }


def safe_next(fallback):
    """Only allow local redirect targets supplied by a form."""
    target = request.form.get('next', '')
    return target if target.startswith('/') and not target.startswith('//') \
        else fallback


def delete_product(product):
    """Remove a product with its enquiries and uploaded image."""
    Enquiry.query.filter_by(product_id=product.id).delete(synchronize_session=False)
    db.session.delete(product)
    db.session.commit()
    try:
        os.remove(os.path.join(STATIC_UPLOADS, 'products', product.image_file))
    except OSError:
        pass


def safe_print(message):
    """Print user-supplied text without crashing on cp1252 consoles."""
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode('ascii', 'backslashreplace').decode('ascii'))


def landing_for(user):
    """Where each role lands after logging in."""
    if user.is_admin:
        return 'admin_dashboard'
    if user.role == 'shop_owner':
        return 'shop_dashboard'
    return 'dashboard'


@app.template_filter('date')
def format_date(value, fmt='%d %b %Y'):
    """Format a timestamp without crashing on older rows with NULL dates."""
    return value.strftime(fmt) if value else '—'

# Create upload directories
STATIC_UPLOADS = os.path.join(config.BASE_DIR, 'static', 'uploads')
for folder in ['input', 'mask', 'output', 'products', 'analysis']:
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], folder), exist_ok=True)
    os.makedirs(os.path.join(STATIC_UPLOADS, folder), exist_ok=True)

# --- AI (Stable Diffusion inpainting) model ---------------------------------
# Loading used to happen once, synchronously, at import time. If that single
# attempt failed (offline, Hugging Face hiccup, corrupt cache) the app stayed
# broken until a full restart. It is now lazy, thread-safe and retryable.
_model_lock = threading.Lock()
_pipe = None
_model_error = None
_model_loading = False
_model_device = None


def _resolve_device():
    requested = (config.SD_DEVICE or "auto").lower()
    if requested == "cpu":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _build_pipeline(local_files_only=False):
    device = _resolve_device()
    torch_dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"[AI] Loading AI Model ({config.SD_MODEL_ID}) on {device} ...")
    pipeline = StableDiffusionInpaintPipeline.from_pretrained(
        config.SD_MODEL_ID,
        torch_dtype=torch_dtype,
        local_files_only=local_files_only,
    )
    # Use fast DPM-Solver++ scheduler for 2-3x faster inference at high quality
    pipeline.scheduler = DPMSolverMultistepScheduler.from_config(pipeline.scheduler.config)
    pipeline = pipeline.to(device)
    try:
        pipeline.set_progress_bar_config(disable=True)
    except AttributeError:
        pass
    return pipeline, device


def get_pipe():
    """Return the inpainting pipeline, loading it on first use.

    A failed load is never cached, so the next request tries again. The lock
    makes sure concurrent Flask requests do not download/load it twice.
    """
    global _pipe, _model_error, _model_loading, _model_device
    if _pipe is not None:
        return _pipe
    with _model_lock:
        if _pipe is not None:
            return _pipe
        _model_loading = True
        try:
            try:
                _pipe, _model_device = _build_pipeline()
            except Exception as online_error:
                # Fall back to an already-downloaded copy when the network is down.
                print(f"[WARN] Online model load failed ({online_error}); trying local cache...")
                _pipe, _model_device = _build_pipeline(local_files_only=True)
            _model_error = None
            print("[OK] Model loaded successfully!")
            print(f"[AI] Using device: {_model_device}")
        except Exception as e:
            _model_error = str(e)
            _pipe = None
            print(f"[ERROR] Error loading model: {e}")
        finally:
            _model_loading = False
        return _pipe


def preload_model():
    """Start loading in the background so web startup stays instant."""
    threading.Thread(target=get_pipe, name="ai-model-loader", daemon=True).start()


def model_status():
    return {
        "loaded": _pipe is not None,
        "loading": _model_loading,
        "error": _model_error,
        "model": config.SD_MODEL_ID,
        "device": _model_device or _resolve_device(),
    }


# Backwards-compatible name for anything that imported the old helper.
load_model = get_pipe

# Make sure tables exist (and older databases get the new columns)
with app.app_context():
    db.create_all()
    upgrade_schema()

# Warm the model up without blocking the server; requests can still trigger it.
preload_model()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/model-status')
def model_status_route():
    """Small health check for the local inpainting model (no secrets exposed)."""
    return jsonify(model_status())


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'error')
            return redirect(url_for('register'))
        
        role = request.form.get('role', 'customer')
        if role not in SIGNUP_ROLES:
            role = 'customer'
        # The very first account manages the whole platform.
        if User.query.count() == 0:
            role = 'admin'

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html', roles=SIGNUP_ROLES, role_labels=ROLES)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash('Login successful!', 'success')
            return redirect(url_for(landing_for(user)))
        else:
            flash('Invalid credentials!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    designs = Design.query.filter_by(user_id=current_user.id).order_by(Design.created_at.desc()).all()
    return render_template('dashboard.html', designs=designs)


@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    """Admin overview: people, roles and platform activity."""
    counts = {key: User.query.filter_by(role=key).count() for key in ROLES}
    users = User.query.order_by(User.created_at.desc()).all()
    recent_designs = Design.query.order_by(Design.created_at.desc()).limit(8).all()
    recent_enquiries = Enquiry.query.order_by(Enquiry.created_at.desc()).limit(8).all()
    pending_shops = [s for s in User.query.filter_by(role='shop_owner').all()
                     if not s.shop_profile or not s.shop_profile.verified]
    return render_template('admin.html', counts=counts, users=users,
                           recent_designs=recent_designs,
                           recent_enquiries=recent_enquiries,
                           pending_shops=pending_shops,
                           total_designs=Design.query.count())


@app.route('/shop')
@role_required('shop_owner', 'admin')
def shop_dashboard():
    """Shop-owner overview: catalogue home and buying-interest activity."""
    query = Product.query
    if not current_user.is_admin:
        query = query.filter_by(owner_id=current_user.id)
    enquiries = Enquiry.query
    if not current_user.is_admin:
        enquiries = enquiries.filter_by(shop_owner_id=current_user.id)
    return render_template('shop.html',
                           total_designs=Design.query.count(),
                           designs_with_places=Design.query.filter(
                               Design.places_json != '').count(),
                           profile=shop_profile_for(current_user.id),
                           enquiry_count=enquiries.count(),
                           new_enquiries=enquiries.filter_by(status='new').count(),
                           products=query.order_by(Product.created_at.desc()).all())


@app.route('/shop/profile', methods=['GET', 'POST'])
@role_required('shop_owner', 'admin')
def shop_profile_view():
    """Register or update this owner's shop details (resets verification)."""
    profile = shop_profile_for(current_user.id)
    if request.method == 'POST':
        shop_name = (request.form.get('shop_name') or '').strip()[:120]
        if not shop_name:
            flash('Please enter your shop name.', 'error')
            return redirect(request.url)
        if profile is None:
            profile = ShopProfile(owner_id=current_user.id)
            db.session.add(profile)
        profile.shop_name = shop_name
        profile.city = (request.form.get('city') or '').strip()[:100]
        profile.address = (request.form.get('address') or '').strip()[:500]
        profile.phone = (request.form.get('phone') or '').strip()[:40]
        profile.verified = False
        profile.submitted_at = datetime.utcnow()
        db.session.commit()
        flash('Shop details submitted. Products will appear in the public '
              'catalogue once an admin verifies the shop.', 'success')
        return redirect(url_for('shop_dashboard'))
    return render_template('shop_profile.html', profile=profile)


@app.route('/shop/products')
@role_required('shop_owner', 'admin')
def products():
    """Product catalogue for the current shop owner (all products for admin)."""
    query = Product.query
    if not current_user.is_admin:
        query = query.filter_by(owner_id=current_user.id)
    return render_template('products.html', availability=AVAILABILITY,
                           products=query.order_by(Product.created_at.desc()).all(),
                           shop=shop_snapshot(current_user.id))


@app.route('/shop/products/add', methods=['GET', 'POST'])
@role_required('shop_owner', 'admin')
def product_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()[:60]
        description = request.form.get('description', '').strip()[:1000]
        dimensions = request.form.get('dimensions', '').strip()[:60]
        availability = request.form.get('availability', 'in_stock')
        if availability not in AVAILABILITY:
            availability = 'in_stock'
        image = request.files.get('image')

        if not name:
            flash('Please enter a product name.', 'error')
            return redirect(request.url)
        try:
            price = round(float(request.form.get('price', '')), 2)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('Please enter a valid price.', 'error')
            return redirect(request.url)
        if image is None or image.filename == '':
            flash('Please choose a product image.', 'error')
            return redirect(request.url)
        if not allowed_file(image.filename):
            flash('Invalid image type! Please upload PNG, JPG, or JPEG.', 'error')
            return redirect(request.url)

        extension = os.path.splitext(image.filename)[1].lower()
        image_file = str(uuid.uuid4()) + extension
        image.save(os.path.join(STATIC_UPLOADS, 'products', image_file))

        db.session.add(Product(
            owner_id=current_user.id,
            name=name[:120], category=category, price=price,
            description=description, dimensions=dimensions,
            availability=availability, image_file=image_file,
        ))
        db.session.commit()
        flash('Product added to your catalogue!', 'success')
        return redirect(url_for('products'))

    return render_template('product_add.html', availability=AVAILABILITY)


@app.route('/shop/products/<int:product_id>/delete', methods=['POST'])
@role_required('shop_owner', 'admin')
def product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    if not current_user.is_admin and product.owner_id != current_user.id:
        abort(403)
    # Enquiries point at the product with a non-nullable FK; remove them too.
    delete_product(product)
    flash('Product deleted.', 'success')
    return redirect(url_for('products'))


def _owned_product(product_id):
    """Fetch a product the current user may change, or abort with 403/404."""
    product = Product.query.get_or_404(product_id)
    if not current_user.is_admin and product.owner_id != current_user.id:
        abort(403)
    return product


@app.route('/shop/products/<int:product_id>/edit', methods=['GET', 'POST'])
@role_required('shop_owner', 'admin')
def product_edit(product_id):
    """Edit an existing catalogue item; the image can be left unchanged."""
    product = _owned_product(product_id)
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        if not name:
            flash('Please enter a product name.', 'error')
            return redirect(request.url)
        try:
            price = round(float(request.form.get('price', '')), 2)
            if price < 0:
                raise ValueError
        except ValueError:
            flash('Please enter a valid price.', 'error')
            return redirect(request.url)
        availability = request.form.get('availability', 'in_stock')
        if availability not in AVAILABILITY:
            availability = product.availability

        image = request.files.get('image')
        if image and image.filename:
            if not allowed_file(image.filename):
                flash('Invalid image type! Please upload PNG, JPG, or JPEG.', 'error')
                return redirect(request.url)
            extension = os.path.splitext(image.filename)[1].lower()
            image_file = str(uuid.uuid4()) + extension
            image.save(os.path.join(STATIC_UPLOADS, 'products', image_file))
            old_image = product.image_file
            product.image_file = image_file
            try:
                os.remove(os.path.join(STATIC_UPLOADS, 'products', old_image))
            except OSError:
                pass

        product.name = name[:120]
        product.category = (request.form.get('category') or '').strip()[:60]
        product.price = price
        product.description = (request.form.get('description') or '').strip()[:1000]
        product.dimensions = (request.form.get('dimensions') or '').strip()[:60]
        product.availability = availability
        db.session.commit()
        flash('Product updated.', 'success')
        return redirect(url_for('products'))
    return render_template('product_add.html', product=product,
                           availability=AVAILABILITY)


@app.route('/shop/products/<int:product_id>/availability', methods=['POST'])
@role_required('shop_owner', 'admin')
def product_availability(product_id):
    """Set a product's stock state (or cycle to the next one if omitted)."""
    product = _owned_product(product_id)
    payload = request.get_json(silent=True) if request.is_json else None
    value = (request.form.get('availability') or
             (payload.get('availability') if isinstance(payload, dict) else None))
    if value not in AVAILABILITY:
        states = list(AVAILABILITY)
        value = states[(states.index(product.availability) + 1) % len(states)] \
            if product.availability in states else states[0]
    product.availability = value
    db.session.commit()
    if request.is_json:
        return jsonify(id=product.id, availability=value,
                       label=product.availability_label)
    flash('Availability set to ' + product.availability_label + '.', 'success')
    return redirect(url_for('products'))


@app.route('/admin/users')
@role_required('admin')
def admin_users():
    """Full account list for the admin."""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/shops')
@role_required('admin')
def admin_shops():
    """All shop owners and how much each has listed."""
    shops = User.query.filter_by(role='shop_owner').order_by(User.created_at.desc()).all()
    return render_template('admin_shops.html', shops=shops,
                           total_products=Product.query.count(),
                           active_shops=sum(1 for s in shops if s.products),
                           verified_shops=sum(1 for s in shops if s.shop_profile
                                              and s.shop_profile.verified))


@app.route('/admin/shops/<int:owner_id>')
@role_required('admin')
def admin_shop(owner_id):
    """One shop owner's catalogue, as seen by the admin."""
    owner = User.query.filter_by(id=owner_id, role='shop_owner').first_or_404()
    products = Product.query.filter_by(owner_id=owner.id).order_by(
        Product.created_at.desc()).all()
    return render_template('admin_shop.html', owner=owner, products=products,
                           profile=shop_profile_for(owner.id))


@app.route('/admin/shops/<int:owner_id>/verify', methods=['POST'])
@role_required('admin')
def admin_shop_verify(owner_id):
    """Approve or revoke a shop, controlling public catalogue visibility."""
    owner = User.query.filter_by(id=owner_id, role='shop_owner').first_or_404()
    profile = shop_profile_for(owner.id)
    if profile is None:
        profile = ShopProfile(owner_id=owner.id, shop_name=owner.username)
        db.session.add(profile)
    verified = (request.form.get('verified', '1') or '1') != '0'
    profile.verified = verified
    db.session.commit()
    flash(('Shop verified. Its products are now publicly listed.'
           if verified else 'Shop verification revoked. Products are hidden.'),
          'success')
    return redirect(safe_next(url_for('admin_shop', owner_id=owner.id)))


@app.route('/admin/products')
@role_required('admin')
def admin_products():
    """Moderation queue: flagged products first, then newest."""
    products = Product.query.order_by(Product.flagged.desc(),
                                      Product.created_at.desc()).all()
    return render_template('admin_products.html', products=products,
                           availability=AVAILABILITY)


@app.route('/admin/products/<int:product_id>/moderate', methods=['POST'])
@role_required('admin')
def admin_product_moderate(product_id):
    """Hide, unhide or permanently remove a flagged product."""
    product = Product.query.get_or_404(product_id)
    action = request.form.get('action')
    if action == 'hide':
        product.hidden = True
        db.session.commit()
        flash('Product hidden from the public catalogue.', 'success')
    elif action == 'unhide':
        product.hidden = False
        product.flagged = False
        db.session.commit()
        flash('Product restored and flag cleared.', 'success')
    elif action == 'remove':
        name = product.name
        delete_product(product)
        flash('Removed product: ' + name, 'success')
    else:
        abort(400)
    return redirect(safe_next(url_for('admin_products')))


@app.route('/admin/reports')
@role_required('admin')
def admin_reports():
    """Platform counts for users, shops, products, designs and enquiries."""
    users = User.query.all()
    shops = [u for u in users if u.role == 'shop_owner']
    profiles = ShopProfile.query.all()
    products = Product.query.all()
    designs = Design.query.all()
    enquiries = Enquiry.query.all()

    def counts(values, key, keys):
        found = {}
        for value in values:
            name = getattr(value, key, None) or ''
            found[name] = found.get(name, 0) + 1
        result = {k: found.get(k, 0) for k in keys}
        result.update({k: v for k, v in found.items() if k not in result})
        return result

    room_counts = counts(designs, 'room_type', list(ROOM_TYPES))
    style_counts = counts(designs, 'style', list(STYLES))
    return render_template(
        'admin_reports.html',
        user_counts={role: sum(1 for u in users if u.role == role) for role in ROLES},
        total_users=len(users),
        shop_counts={
            'total': len(shops),
            'verified': sum(1 for s in shops if s.shop_profile and s.shop_profile.verified),
            'pending': sum(1 for s in shops if not s.shop_profile or
                           not s.shop_profile.verified),
            'without_products': sum(1 for s in shops if not s.products),
        },
        product_counts={
            'total': len(products),
            'flagged': sum(1 for p in products if p.flagged),
            'hidden': sum(1 for p in products if p.hidden),
            'public': sum(1 for p in products if not p.hidden),
        },
        availability_counts=counts(products, 'availability', list(AVAILABILITY)),
        availability_labels=AVAILABILITY,
        design_counts={
            'total': len(designs),
            'room': room_counts, 'style': style_counts,
        },
        room_labels=ROOM_TYPES, style_labels=STYLES,
        enquiry_counts={
            'total': len(enquiries),
            'kind': counts(enquiries, 'kind', list(ENQUIRY_KINDS)),
            'status': counts(enquiries, 'status', list(ENQUIRY_STATUSES)),
        },
        enquiry_labels={'kind': ENQUIRY_KINDS, 'status': ENQUIRY_STATUSES},
        pending_shops=[s for s in shops if not s.shop_profile or
                       not s.shop_profile.verified],
        recent_designs=Design.query.order_by(Design.created_at.desc()).limit(8).all(),
        recent_enquiries=Enquiry.query.order_by(Enquiry.created_at.desc()).limit(8).all(),
        total_profiles=len(profiles),
    )


@app.route('/products')
@login_required
def catalogue():
    """Browse every listed product (for customers, designers and admins)."""
    products = visible_products().order_by(Product.created_at.desc()).all()
    shops = {}
    for product in products:
        if product.owner_id not in shops:
            shops[product.owner_id] = shop_snapshot(product.owner_id)
    return render_template('catalogue.html', products=products, shops=shops)


@app.route('/products/<int:product_id>')
@login_required
def product_detail(product_id):
    """Full details for one catalogue item from a verified shop."""
    product = visible_products().filter_by(id=product_id).first_or_404()
    designs = Design.query.filter_by(user_id=current_user.id).order_by(
        Design.created_at.desc()).all()
    return render_template('product_detail.html', product=product,
                           shop=shop_snapshot(product.owner_id),
                           latest_design=designs[0] if designs else None,
                           designs=designs, enquiry_kinds=ENQUIRY_KINDS)


@app.route('/products/<int:product_id>/enquire', methods=['POST'])
@login_required
def product_enquire(product_id):
    """Send an enquiry or order about a product to its shop owner."""
    product = visible_products().filter_by(id=product_id).first_or_404()
    message = (request.form.get('message') or '').strip()[:1000]
    if not message:
        flash('Please write a message for the shop owner.', 'error')
        return redirect(url_for('product_detail', product_id=product_id))
    kind = request.form.get('kind', 'enquiry')
    if kind not in ENQUIRY_KINDS:
        kind = 'enquiry'
    design_id = None
    raw_id = (request.form.get('design_id') or '').strip()
    if raw_id.isdigit():
        candidate = Design.query.get(int(raw_id))
        if candidate and (current_user.is_admin or
                          candidate.user_id == current_user.id):
            design_id = candidate.id
    db.session.add(Enquiry(
        product_id=product.id, customer_id=current_user.id,
        shop_owner_id=product.owner_id, design_id=design_id,
        message=message, kind=kind, status='new',
    ))
    db.session.commit()
    shop = shop_snapshot(product.owner_id)
    flash('Your ' + kind + ' was sent to ' + shop['name'] + '.', 'success')
    return redirect(url_for('product_detail', product_id=product_id))


@app.route('/products/<int:product_id>/flag', methods=['POST'])
@login_required
def product_flag(product_id):
    """Flag a listing for admin review (owner and admin cannot flag their own)."""
    product = visible_products().filter_by(id=product_id).first_or_404()
    if current_user.is_admin or current_user.id == product.owner_id:
        abort(403)
    product.flagged = True
    db.session.commit()
    flash('Thanks — this product was flagged for admin review.', 'success')
    return redirect(url_for('product_detail', product_id=product_id))


@app.route('/my/enquiries')
@login_required
def my_enquiries():
    """Enquiries and orders the current customer sent, with live status."""
    enquiries = Enquiry.query.filter_by(customer_id=current_user.id).order_by(
        Enquiry.created_at.desc()).all()
    shops = {}
    for enquiry in enquiries:
        if enquiry.shop_owner_id not in shops:
            shops[enquiry.shop_owner_id] = shop_snapshot(enquiry.shop_owner_id)
    return render_template('my_enquiries.html', enquiries=enquiries,
                           shops=shops, kinds=ENQUIRY_KINDS,
                           statuses=ENQUIRY_STATUSES)


@app.route('/shop/enquiries')
@role_required('shop_owner', 'admin')
def shop_enquiries():
    """Inbox of customer enquiries and orders for this shop."""
    query = Enquiry.query
    if not current_user.is_admin:
        query = query.filter_by(shop_owner_id=current_user.id)
    enquiries = query.order_by(Enquiry.created_at.desc()).all()
    return render_template('enquiries.html', enquiries=enquiries,
                           statuses=ENQUIRY_STATUSES, kinds=ENQUIRY_KINDS)


@app.route('/shop/enquiries/<int:enquiry_id>/status', methods=['POST'])
@role_required('shop_owner', 'admin')
def enquiry_status(enquiry_id):
    """Move an enquiry/order to new, responded or closed."""
    enquiry = Enquiry.query.get_or_404(enquiry_id)
    if not current_user.is_admin and enquiry.shop_owner_id != current_user.id:
        abort(403)
    status = request.form.get('status', '')
    if status not in ENQUIRY_STATUSES:
        abort(400)
    enquiry.status = status
    db.session.commit()
    flash('Enquiry marked as ' + enquiry.status_label.lower() + '.', 'success')
    return redirect(url_for('shop_enquiries'))


@app.context_processor
def inject_roles():
    return {
        'role_labels': ROLES,
        'home_endpoint': landing_for(current_user) if current_user.is_authenticated else 'index',
    }


def _form_float(form, key, low=0.0, high=1000.0):
    """Return a bounded float from a form field, or None when absent/invalid."""
    raw = (form.get(key) or '').strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if low <= value <= high else None


@app.route('/api/analyze-room', methods=['POST'])
@login_required
def api_analyze_room():
    """Measure an uploaded room photo and return dimensions as JSON."""
    image = request.files.get('image')
    if image is None or image.filename == '':
        return jsonify(error='Please choose a room photo.'), 400
    if not allowed_file(image.filename):
        return jsonify(error='Please upload a PNG, JPG or JPEG image.'), 400

    manual = {}
    reference_pixels = _form_float(request.form, 'reference_pixels', 1, 100000)
    reference_length = _form_float(request.form, 'reference_length_m', 0.1, 100)
    if reference_pixels is not None:
        manual['reference_pixels'] = reference_pixels
    if reference_length is not None:
        manual['reference_length_m'] = reference_length
    for key in ('width_m', 'length_m', 'height_m'):
        value = _form_float(request.form, key, 0.1, 100)
        if value is not None:
            manual[key] = value

    tmp_dir = tempfile.mkdtemp(prefix='room-api-')
    extension = os.path.splitext(image.filename)[1].lower()
    tmp_path = os.path.join(tmp_dir, 'photo' + extension)
    try:
        image.save(tmp_path)
        analysis = room_analysis.analyze_room(
            tmp_path,
            reference_length_m=reference_length or room_analysis.DEFAULT_REFERENCE_M,
            manual=manual,
            output_dir=os.path.join(STATIC_UPLOADS, 'analysis'),
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception as exc:
        print('[ERROR] Room analysis failed:', exc)
        return jsonify(error='Room analysis failed. Please try another photo.'), 500
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return jsonify(
        width_m=analysis['width_m'], length_m=analysis['length_m'],
        height_m=analysis['height_m'], confidence=analysis['confidence'],
        note=analysis['note'], reference=analysis['reference'],
        detected=analysis['detected'], image_size=analysis['image_size'],
        overlay_url=url_for('static', filename='uploads/analysis/' +
                            os.path.basename(analysis['overlay_path'])),
    )


@app.route('/design', methods=['GET', 'POST'])
@login_required
def design():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('No image selected!', 'error')
            return redirect(request.url)
        
        file = request.files['image']
        prompt = request.form.get('prompt', '').strip()
        whole_room = request.form.get('mode') == 'whole'
        position = ('whole_room' if whole_room else
                    masking.normalize_position(request.form.get('position')))
        # ``coords`` is kept as a fallback for older form posts.
        custom_coords = masking.parse_coords(
            request.form.get('mask_coords') or request.form.get('coords'))
        mask_coords = ''
        if position == 'custom' and custom_coords is None:
            flash('Custom area was invalid; using the centre zone instead.', 'info')
            position = masking.DEFAULT_POSITION
        if position == 'custom':
            mask_coords = ','.join(f'{part * 100:g}' for part in custom_coords)
        location = request.form.get('location', '').strip()[:200]

        room_type = request.form.get('room_type', '').strip().lower()
        style = request.form.get('style', '').strip().lower()
        room_type = room_type if room_type in ROOM_TYPES else ''
        style = style if style in STYLES else ''
        budget = request.form.get('budget', '').strip()[:80]
        preferences = request.form.get('preferences', '').strip()[:500]
        width_m = _form_float(request.form, 'width_m', 0.1, 100)
        length_m = _form_float(request.form, 'length_m', 0.1, 100)
        height_m = _form_float(request.form, 'height_m', 0.1, 100)
        detection_notes = request.form.get('detection_notes', '').strip()[:1000]

        if not prompt:
            flash('Please type or speak what you want to add.', 'error')
            return redirect(request.url)

        if file.filename == '':
            flash('No image selected!', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            try:
                # Generate unique filename
                file_extension = os.path.splitext(file.filename)[1].lower()
                filename = str(uuid.uuid4()) + file_extension
                input_path = os.path.join(app.config['UPLOAD_FOLDER'], 'input', filename)
                
                # Save input image
                file.save(input_path)
                
                # [OK] EXACTLY LIKE YOUR WORKING CODE
                # Load input image
                init_image = Image.open(input_path).convert("RGB").resize((512, 512))
                
                # One zone, a validated custom box, or a fully white mask.
                if whole_room:
                    mask_image = masking.build_full_mask(init_image.size)
                elif position == 'custom':
                    mask_image = masking.build_custom_mask(custom_coords, init_image.size)
                else:
                    mask_image = masking.build_mask(position, init_image.size)

                # Save the binary mask as PNG so the white box stays exact.
                mask_filename = "mask_" + os.path.splitext(filename)[0] + ".png"
                mask_path = os.path.join(app.config['UPLOAD_FOLDER'], 'mask', mask_filename)
                mask_image.save(mask_path)
                
                print("[OK] Mask created and saved")
                
                # Load on demand (and retry automatically if an earlier attempt failed)
                pipeline = get_pipe()
                if pipeline is None:
                    detail = f" ({_model_error})" if _model_error else ""
                    flash('AI model is still loading or unavailable. Please refresh and try again'
                          + detail + '.', 'error')
                    return redirect(request.url)

                generation_prompt = build_prompt(
                    prompt, room_type=room_type, style=style, budget=budget,
                    preferences=preferences, width_m=width_m, length_m=length_m,
                    height_m=height_m, whole_room=whole_room,
                )
                safe_print(f"[AI] Generating image with prompt: {generation_prompt}")

                with torch.inference_mode():
                    result = pipeline(
                        prompt=generation_prompt,
                        image=init_image,
                        mask_image=mask_image,
                        guidance_scale=7.5,
                        num_inference_steps=config.SD_STEPS,
                    )
                
                # Get result image. The VAE decoder can drift outside the white
                # mask, so paste only the generated pixels back onto the original
                # photo; everything outside the box stays pixel-identical.
                generated = result.images[0].convert("RGB")
                if generated.size != init_image.size:
                    generated = generated.resize(init_image.size)
                edited_image = init_image.copy()
                edited_image.paste(generated, (0, 0), mask_image.convert("L"))
                output_filename = f"output_{filename}"
                output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'output', output_filename)
                edited_image.save(output_path)
                
                print("[OK] Output image generated and saved")
                
                # Save copies for web display
                static_input_path = os.path.join(STATIC_UPLOADS, 'input', filename)
                static_mask_path = os.path.join(STATIC_UPLOADS, 'mask', mask_filename)
                static_output_path = os.path.join(STATIC_UPLOADS, 'output', output_filename)
                
                init_image.save(static_input_path)
                mask_image.save(static_mask_path)
                edited_image.save(static_output_path)
                
                # Ask Gemini where the item can be bought nearby
                nearby = places.find_nearby_places(prompt, location)

                # Save to database
                new_design = Design(
                    user_id=current_user.id,
                    input_image=filename,
                    mask_image=mask_filename,
                    output_image=output_filename,
                    prompt=prompt,
                    position=position,
                    mask_coords=mask_coords,
                    location=location,
                    places_json=json.dumps(nearby),
                    room_type=room_type,
                    style=style,
                    budget=budget,
                    preferences=preferences,
                    width_m=width_m,
                    length_m=length_m,
                    height_m=height_m,
                    detection_notes=detection_notes,
                )
                db.session.add(new_design)
                db.session.commit()
                
                flash('Design created successfully!', 'success')
                return redirect(url_for('result', design_id=new_design.id))
                
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
                import traceback
                print("[ERROR] ERROR DETAILS:")
                print(traceback.format_exc())
                return redirect(request.url)
        else:
            flash('Invalid file type! Please upload PNG, JPG, or JPEG.', 'error')
    
    return render_template('design.html', positions=masking.LABELS,
                           default_position=masking.DEFAULT_POSITION,
                           room_types=ROOM_TYPES, styles=STYLES)


@app.route('/design/<int:design_id>')
@login_required
def result(design_id):
    query = Design.query.filter_by(id=design_id)
    if not current_user.is_admin:
        query = query.filter_by(user_id=current_user.id)
    d = query.first()
    if d is None:
        abort(404)
    try:
        nearby = json.loads(d.places_json) if d.places_json else None
    except ValueError:
        nearby = None
    try:
        placement = json.loads(d.placement_json) if d.placement_json else {}
        if not isinstance(placement, dict):
            placement = {}
    except ValueError:
        placement = {}
    # Furniture from the shop catalogue is available to drag onto the result.
    furniture = visible_products().order_by(Product.created_at.desc()).all()
    return render_template('result.html', d=d, nearby=nearby, placement=placement,
                           room_summary=describe_room(
                               d.room_type, d.style, d.budget,
                               d.width_m, d.length_m, d.height_m),
                           room_types=ROOM_TYPES, styles=STYLES,
                           position_label=masking.LABELS.get(d.position, 'Centre'),
                           furniture=furniture)


@app.route('/design/<int:design_id>/placement', methods=['POST'])
@login_required
def save_placement(design_id):
    """Persist the furniture arrangement (design owner or admin only)."""
    d = Design.query.get_or_404(design_id)
    if not (current_user.is_admin or d.user_id == current_user.id):
        abort(403)

    payload = request.get_json(silent=True)
    if payload is None:
        raw = request.form.get('placement_json') or request.form.get('items')
        try:
            payload = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get('items'), list):
        return jsonify(error='Expected JSON with an items list.'), 400
    if len(payload['items']) > 100:
        return jsonify(error='Too many placed items (maximum 100).'), 400

    def bounded(value, low, high, default):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return round(min(high, max(low, number)), 4)

    def angle(value):
        """Normalise a rotation to -180..180 degrees, like the browser editor."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        return round(((number + 180) % 360) - 180, 2)

    cleaned = []
    for item in payload['items']:
        if not isinstance(item, dict):
            continue
        src = str(item.get('src') or '')[:200000]
        if not src:
            continue
        cleaned.append({
            'src': src,
            'name': str(item.get('name') or 'Furniture')[:120],
            'rx': bounded(item.get('rx'), 0, 1, 0.5),
            'ry': bounded(item.get('ry'), 0, 1, 0.5),
            'scale': bounded(item.get('scale'), 0.05, 0.7, 0.18),
            'rotation': angle(item.get('rotation', item.get('rot'))),
        })

    d.placement_json = json.dumps({'items': cleaned}, separators=(',', ':'))
    db.session.commit()
    return jsonify(ok=True, count=len(cleaned))


@app.route('/transcribe', methods=['POST'])
@login_required
def transcribe():
    """Receive a WAV recording from the browser and return the recognised text."""
    audio = request.files.get('audio')
    if audio is None:
        return jsonify(error='No audio received.'), 400
    language = request.form.get('language', 'en-IN')
    if not all(ch.isalnum() or ch == '-' for ch in language) or len(language) > 10:
        language = 'en-IN'
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    try:
        audio.save(tmp)
        tmp.close()
        from voice import transcribe_wav, VoiceError
        try:
            return jsonify(text=transcribe_wav(tmp.name, language))
        except VoiceError as exc:
            return jsonify(error=str(exc)), 422
    except ImportError:
        return jsonify(error='SpeechRecognition is not installed. Run: pip install SpeechRecognition'), 500
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        upgrade_schema()
    print("[Flask] Starting Flask Application...")
    app.run(debug=True, host='0.0.0.0', port=5000)