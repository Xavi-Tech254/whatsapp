import os
import json
import time
import uuid
import hmac
import hashlib
import requests as req
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Category, Payment, BotSession, AdminUser, Settings, DailyQuote
from bot.handler import handle_message
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'devclin2024secret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///devclin.db').replace('postgresql://', 'postgresql+psycopg2://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
app.config['BANNER_FOLDER'] = os.path.join(os.path.dirname(__file__), 'static', 'banners')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['BANNER_FOLDER'], exist_ok=True)

db.init_app(app)

from template_helpers import register_template_helpers
register_template_helpers(app)

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'mp4', 'mp3', 'jpg', 'jpeg', 'png', 'zip'}
ALLOWED_IMG = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', 'sk_live_YOUR_SECRET_KEY')
PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', 'pk_live_38050a39fbcd3b3b4b946448253478c78993bda8')

def allowed_file(filename, img=False):
    exts = ALLOWED_IMG if img else ALLOWED_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in exts

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def save_file(file, folder):
    filename = secure_filename(file.filename)
    filename = f"{int(time.time())}_{filename}"
    path = os.path.join(folder, filename)
    file.save(path)
    return filename

def get_setting_val(key, default=''):
    s = Settings.query.filter_by(key=key).first()
    return s.value if s else default

def deliver_product(user, cat, paystack_ref):
    """Send product to user via bridge after confirmed payment"""
    bridge_url = get_setting_val('bridge_url', '')
    if not bridge_url:
        return
    msg = f"✅ Payment confirmed! Thank you, *{user.username}*! 🎉\n\n📦 *{cat.icon} {cat.name}*\n\nHappy studying! 🎓"
    try:
        if cat.file_path:
            flask_url = os.environ.get('FLASK_URL', '')
            file_url = f"{flask_url}{cat.file_path}"
            req.post(f"{bridge_url}/send-file", json={
                'number': user.whatsapp_number,
                'message': msg,
                'file_url': file_url
            }, timeout=10)
        else:
            if cat.link:
                msg += f"\n\n🔗 {cat.link}"
            req.post(f"{bridge_url}/send", json={
                'number': user.whatsapp_number,
                'message': msg
            }, timeout=10)
    except Exception as e:
        print(f"Delivery error: {e}")

# ── WHATSAPP WEBHOOK ──────────────────────────────────────────────────
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({'status': 'error'}), 400
    number = str(data.get('from', '')).replace('+', '').replace(' ', '')
    text = str(data.get('message', '')).strip()
    if not number or not text:
        return jsonify({'status': 'ignored'}), 200
    with app.app_context():
        reply = handle_message(number, text)
    if isinstance(reply, dict):
        return jsonify({'status': 'ok', **reply})
    return jsonify({'status': 'ok', 'reply': reply})

# ── PAYMENT PAGE ──────────────────────────────────────────────────────
@app.route('/pay/<int:cat_id>/<number>')
def pay_page(cat_id, number):
    cat = Category.query.get_or_404(cat_id)
    user = User.query.filter_by(whatsapp_number=number).first_or_404()
    flask_url = os.environ.get('FLASK_URL', '')
    ref = f"DCLIN-{cat_id}-{number[-6:]}-{uuid.uuid4().hex[:8].upper()}"
    callback_url = f"{flask_url}/paystack/callback"
    try:
        resp = req.post(
            'https://api.paystack.co/transaction/initialize',
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
            json={
                'email': f'user{number}@devclinstudies.com',
                'amount': int(cat.price * 100),
                'currency': 'KES',
                'reference': ref,
                'callback_url': callback_url,
                'channels': ['mobile_money'],
                'metadata': {
                    'custom_fields': [
                        {'display_name': 'WhatsApp', 'variable_name': 'whatsapp', 'value': number},
                        {'display_name': 'Category', 'variable_name': 'category_id', 'value': str(cat_id)}
                    ]
                }
            },
            timeout=15
        )
        result = resp.json()
        if result.get('status') and result['data'].get('authorization_url'):
            return redirect(result['data']['authorization_url'])
    except Exception as e:
        print(f"Paystack init error: {e}")
    return render_template("pay.html", category=cat, user_number=number, bot_name=get_setting_val("bot_name","Dev Clin Studies"), paystack_public_key=PAYSTACK_PUBLIC_KEY, ref=ref, flask_url=flask_url)

# ── PAYSTACK CALLBACK (redirect after payment) ────────────────────────
@app.route('/paystack/callback')
def paystack_callback():
    reference = request.args.get('reference', '')
    if not reference:
        return redirect('/')
    try:
        resp = req.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'},
            timeout=15
        )
        result = resp.json()
    except:
        return render_template('pay_result.html', success=False, message='Could not verify payment.')

    if not result.get('status') or result['data']['status'] != 'success':
        return render_template('pay_result.html', success=False, message='Payment not successful.')

    tx = result['data']
    meta = tx.get('metadata', {})
    custom = {f['variable_name']: f['value'] for f in meta.get('custom_fields', [])}
    whatsapp_number = str(custom.get('whatsapp', ''))
    cat_id = custom.get('category_id', '')
    amount_paid = tx['amount'] / 100
    phone = tx.get('authorization', {}).get('mobile_number') or whatsapp_number

    existing = Payment.query.filter_by(paystack_ref=reference).first()
    if existing:
        return render_template('pay_result.html', success=True, message='Payment already processed!')

    user = User.query.filter_by(whatsapp_number=whatsapp_number).first()
    cat = Category.query.get(int(cat_id)) if cat_id else None

    if user and cat:
        payment = Payment(user_id=user.id, category_id=cat.id, paystack_ref=reference,
                         amount=amount_paid, phone_number=str(phone), verified=True)
        db.session.add(payment)
        sess = BotSession.query.filter_by(whatsapp_number=whatsapp_number).first()
        if sess:
            sess.state = 'menu'
        db.session.commit()
        deliver_product(user, cat, reference)

    return render_template('pay_result.html', success=True, message='Payment successful! Go back to WhatsApp to get your product. 🎉')

# ── PAYSTACK VERIFY (called by pay.html after payment) ────────────────
@app.route('/paystack/verify', methods=['POST'])
def paystack_verify():
    data = request.json or {}
    reference = data.get('reference', '')
    if not reference:
        return jsonify({'status': 'error', 'message': 'No reference provided'}), 400

    # Check not already used
    existing = Payment.query.filter_by(paystack_ref=reference).first()
    if existing:
        return jsonify({'status': 'error', 'message': 'Reference already used'}), 400

    # Verify with Paystack
    try:
        resp = req.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'},
            timeout=15
        )
        result = resp.json()
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Could not reach Paystack'}), 500

    if not result.get('status') or result['data']['status'] != 'success':
        return jsonify({'status': 'error', 'message': 'Payment not successful'}), 400

    tx = result['data']
    meta = tx.get('metadata', {})
    custom = {f['variable_name']: f['value'] for f in meta.get('custom_fields', [])}
    whatsapp_number = custom.get('whatsapp', '')
    cat_id = custom.get('category_id', '')
    amount_paid = tx['amount'] / 100  # convert from kobo back to KES
    phone = tx.get('authorization', {}).get('mobile_number') or whatsapp_number

    user = User.query.filter_by(whatsapp_number=str(whatsapp_number)).first()
    cat = Category.query.get(int(cat_id)) if cat_id else None

    if not user or not cat:
        return jsonify({'status': 'error', 'message': 'User or item not found'}), 400

    # Save payment
    payment = Payment(
        user_id=user.id,
        category_id=cat.id,
        paystack_ref=reference,
        amount=amount_paid,
        phone_number=str(phone),
        verified=True
    )
    db.session.add(payment)

    # Reset session state
    sess = BotSession.query.filter_by(whatsapp_number=whatsapp_number).first()
    if sess:
        sess.state = 'menu'
        sess.pending_category_id = None

    db.session.commit()

    # Deliver product
    deliver_product(user, cat, reference)

    return jsonify({'status': 'ok'})

# ── BROADCAST (from bridge) ───────────────────────────────────────────
@app.route('/broadcast-list', methods=['GET'])
def broadcast_list():
    users = User.query.all()
    return jsonify({'numbers': [u.whatsapp_number for u in users]})

# ── ADMIN LOGIN ───────────────────────────────────────────────────────
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = AdminUser.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'error')
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_payments = Payment.query.filter_by(verified=True).count()
    total_revenue = db.session.query(db.func.sum(Payment.amount)).filter_by(verified=True).scalar() or 0
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html',
        total_users=total_users, total_payments=total_payments,
        total_revenue=total_revenue, recent_payments=recent_payments,
        recent_sms=[])

# ── CATEGORIES ────────────────────────────────────────────────────────
@app.route('/admin/categories')
@admin_required
def admin_categories():
    roots = Category.query.filter_by(parent_id=None).order_by(Category.order_index).all()
    return render_template('admin/categories.html', categories=roots)

@app.route('/admin/categories/add', methods=['POST'])
@admin_required
def add_category():
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'Name required'}), 400
    parent_id = request.form.get('parent_id') or None
    cat_type = request.form.get('cat_type', 'folder')
    icon = request.form.get('icon', '📁').strip() or '📁'
    price = float(request.form.get('price', 0))
    link = request.form.get('link', '').strip() or None
    order_index = int(request.form.get('order_index', 0))
    file_path = None
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename and allowed_file(f.filename):
            fname = save_file(f, app.config['UPLOAD_FOLDER'])
            file_path = f"/static/uploads/{fname}"
    cat = Category(name=name, parent_id=int(parent_id) if parent_id else None,
                   cat_type=cat_type, icon=icon, price=price,
                   file_path=file_path, link=link, order_index=order_index)
    db.session.add(cat)
    db.session.commit()
    return jsonify({'success': True, 'id': cat.id, 'category': cat.to_dict()})

@app.route('/admin/categories/<int:cat_id>/edit', methods=['POST'])
@admin_required
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    cat.name = request.form.get('name', cat.name).strip()
    cat.icon = request.form.get('icon', cat.icon).strip() or cat.icon
    cat.cat_type = request.form.get('cat_type', cat.cat_type)
    cat.price = float(request.form.get('price', cat.price))
    cat.link = request.form.get('link', '').strip() or None
    cat.is_active = request.form.get('is_active', 'true') == 'true'
    cat.order_index = int(request.form.get('order_index', cat.order_index))
    if 'file' in request.files:
        f = request.files['file']
        if f and f.filename and allowed_file(f.filename):
            fname = save_file(f, app.config['UPLOAD_FOLDER'])
            cat.file_path = f"/static/uploads/{fname}"
    db.session.commit()
    return jsonify({'success': True, 'category': cat.to_dict()})

@app.route('/admin/categories/<int:cat_id>/delete', methods=['POST'])
@admin_required
def delete_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    cat.is_active = False
    db.session.commit()
    return jsonify({'success': True})

# ── BROADCAST ─────────────────────────────────────────────────────────
@app.route('/admin/broadcast', methods=['GET', 'POST'])
@admin_required
def admin_broadcast():
    if request.method == 'POST':
        message = request.form.get('message', '').strip()
        bridge_url = get_setting_val('bridge_url', '')
        if message and bridge_url:
            users = User.query.all()
            sent = 0
            for user in users:
                try:
                    req.post(f"{bridge_url}/send", json={
                        'number': user.whatsapp_number,
                        'message': message
                    }, timeout=5)
                    sent += 1
                except:
                    pass
            flash(f'Broadcast sent to {sent} users!', 'success')
        else:
            flash('Message or bridge URL missing', 'error')
    return render_template('admin/broadcast.html')

# ── SETTINGS ──────────────────────────────────────────────────────────
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for key in ['bot_name', 'welcome_message', 'bridge_url']:
            val = request.form.get(key, '').strip()
            s = Settings.query.filter_by(key=key).first()
            if s:
                s.value = val
            elif val:
                db.session.add(Settings(key=key, value=val))
        if 'banner' in request.files:
            f = request.files['banner']
            if f and f.filename and allowed_file(f.filename, img=True):
                fname = save_file(f, app.config['BANNER_FOLDER'])
                banner_path = f"/static/banners/{fname}"
                s = Settings.query.filter_by(key='banner_path').first()
                if s:
                    s.value = banner_path
                else:
                    db.session.add(Settings(key='banner_path', value=banner_path))
        db.session.commit()
        flash('Settings saved!', 'success')
    settings = {s.key: s.value for s in Settings.query.all()}
    return render_template('admin/settings.html', settings=settings)

# ── USERS ─────────────────────────────────────────────────────────────
@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

# ── PAYMENTS ──────────────────────────────────────────────────────────
@app.route('/admin/payments')
@admin_required
def admin_payments():
    payments = Payment.query.order_by(Payment.created_at.desc()).all()
    return render_template('admin/payments.html', payments=payments)

# ── QUOTES ────────────────────────────────────────────────────────────
@app.route('/admin/quotes', methods=['GET', 'POST'])
@admin_required
def admin_quotes():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            text = request.form.get('text', '').strip()
            author = request.form.get('author', '').strip()
            if text:
                db.session.add(DailyQuote(text=text, author=author or None))
                db.session.commit()
                flash('Quote added!', 'success')
        elif action == 'delete':
            qid = request.form.get('quote_id')
            q = DailyQuote.query.get(qid)
            if q:
                db.session.delete(q)
                db.session.commit()
                flash('Quote deleted!', 'success')
    quotes = DailyQuote.query.order_by(DailyQuote.created_at.desc()).all()
    return render_template('admin/quotes.html', quotes=quotes)

# ── FILE SERVING ──────────────────────────────────────────────────────
@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/static/banners/<filename>')
def banner_file(filename):
    return send_from_directory(app.config['BANNER_FOLDER'], filename)

# ── INIT ──────────────────────────────────────────────────────────────
def init_db():
    with app.app_context():
        db.create_all()
        if not AdminUser.query.filter_by(username='admin').first():
            db.session.add(AdminUser(username='admin', password=generate_password_hash('admin123')))
        defaults = {
            'bot_name': 'Dev Clin Studies',
            'welcome_message': 'Welcome!',
            'bridge_url': 'http://localhost:3000',
            'banner_path': ''
        }
        for k, v in defaults.items():
            if not Settings.query.filter_by(key=k).first():
                db.session.add(Settings(key=k, value=v))
        db.session.commit()
        print("✅ DB ready! Admin: admin / admin123")

if __name__ == '__main__':
    init_db()
    try:
        from scheduler import init_scheduler
        init_scheduler(app)
    except Exception as e:
        print(f"Scheduler error: {e}")
    app.run(debug=True, port=5000)
