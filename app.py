import os
import json
import tempfile
import threading
from functools import wraps
import torch
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from PIL import Image
from diffusers import StableDiffusionInpaintPipeline, DPMSolverMultistepScheduler
from database import (db, User, Design, Product, upgrade_schema,
                      ROLES, SIGNUP_ROLES, AVAILABILITY)
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
    return render_template('admin.html', counts=counts, users=users,
                           recent_designs=recent_designs,
                           total_designs=Design.query.count())


@app.route('/shop')
@role_required('shop_owner', 'admin')
def shop_dashboard():
    """Shop-owner overview: catalogue home and buying-interest activity."""
    query = Product.query
    if not current_user.is_admin:
        query = query.filter_by(owner_id=current_user.id)
    return render_template('shop.html',
                           total_designs=Design.query.count(),
                           designs_with_places=Design.query.filter(
                               Design.places_json != '').count(),
                           products=query.order_by(Product.created_at.desc()).all())


@app.route('/shop/products')
@role_required('shop_owner', 'admin')
def products():
    """Product catalogue for the current shop owner (all products for admin)."""
    query = Product.query
    if not current_user.is_admin:
        query = query.filter_by(owner_id=current_user.id)
    return render_template('products.html',
                           products=query.order_by(Product.created_at.desc()).all())


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
    db.session.delete(product)
    db.session.commit()
    try:
        os.remove(os.path.join(STATIC_UPLOADS, 'products', product.image_file))
    except OSError:
        pass
    flash('Product deleted.', 'success')
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
                           active_shops=sum(1 for s in shops if s.products))


@app.route('/admin/shops/<int:owner_id>')
@role_required('admin')
def admin_shop(owner_id):
    """One shop owner's catalogue, as seen by the admin."""
    owner = User.query.filter_by(id=owner_id, role='shop_owner').first_or_404()
    products = Product.query.filter_by(owner_id=owner.id).order_by(
        Product.created_at.desc()).all()
    return render_template('admin_shop.html', owner=owner, products=products)


@app.route('/products')
@login_required
def catalogue():
    """Browse every listed product (for customers, designers and admins)."""
    products = Product.query.order_by(Product.created_at.desc()).all()
    return render_template('catalogue.html', products=products)


@app.route('/products/<int:product_id>')
@login_required
def product_detail(product_id):
    """Full details for one catalogue item."""
    product = Product.query.get_or_404(product_id)
    latest_design = Design.query.filter_by(user_id=current_user.id).order_by(
        Design.created_at.desc()).first()
    return render_template('product_detail.html', product=product,
                           latest_design=latest_design)


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
                
                # One zone for an item, or a fully white mask for a whole-room redesign.
                mask_image = (masking.build_full_mask(init_image.size) if whole_room
                              else masking.build_mask(position, init_image.size))

                # Save mask
                mask_filename = f"mask_{filename}"
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
                
                # Get result image
                edited_image = result.images[0]
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
    furniture = Product.query.order_by(Product.created_at.desc()).all()
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