import os
import json
import time
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Category, Payment, MpesaSMS, BotSession, AdminUser, Settings, DailyQuote
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
# ─ MPESA SMS FORWARDING ──────────────────────────────────────────────
@app.route('/mpesa-sms', methods=['POST'])
def mpesa_sms():
    """Receives forwarded Mpesa SMS from admin's phone"""
    import re
    data = request.json or request.form.to_dict()
    raw = data.get('sms', '') or data.get('message', '') or data.get('body', '')
    if not raw:
        return jsonify({'status': 'error', 'message': 'No SMS body'}), 400

    # Parse the SMS
    code_match = re.search(r'\b([A-Z0-9]{10})\b', raw)
    amount_match = re.search(r'Ksh\s*([\d,]+\.?\d*)', raw, re.IGNORECASE)
    phone_match = re.search(r'from\s+(2547\d{8}|2541\d{8})', raw, re.IGNORECASE)

    if not code_match or not amount_match:
        return jsonify({'status': 'error', 'message': 'Could not parse SMS'}), 400

    code = code_match.group(1)
    amount = float(amount_match.group(1).replace(',', ''))
    phone = phone_match.group(1) if phone_match else None

    # Check duplicate
    existing = MpesaSMS.query.filter_by(mpesa_code=code).first()
    if existing:
        return jsonify({'status': 'duplicate', 'code': code})

    sms = MpesaSMS(mpesa_code=code, amount=amount, sender_phone=phone, raw_sms=raw)
    db.session.add(sms)
    db.session.commit()
    return jsonify({'status': 'ok', 'code': code, 'amount': amount})

# ── BROADCAST (from bridge) ───────────────────────────────────────────
@app.route('/broadcast-list', methods=['GET'])
def broadcast_list():
    """Returns list of user numbers for bridge to send to"""
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
    recent_sms = MpesaSMS.query.order_by(MpesaSMS.received_at.desc()).limit(5).all()
    return render_template('admin/dashboard.html',
        total_users=total_users, total_payments=total_payments,
        total_revenue=total_revenue, recent_payments=recent_payments,
        recent_sms=recent_sms)

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
            import requests as req
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

def get_setting_val(key, default=''):
    s = Settings.query.filter_by(key=key).first()
    return s.value if s else default

# ── SETTINGS ──────────────────────────────────────────────────────────
@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    if request.method == 'POST':
        for key in ['mpesa_number', 'bot_name', 'welcome_message', 'bridge_url']:
            val = request.form.get(key, '').strip()
            s = Settings.query.filter_by(key=key).first()
            if s:
                s.value = val
            elif val:
                db.session.add(Settings(key=key, value=val))
        # Banner upload
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
    mpesa_sms = MpesaSMS.query.order_by(MpesaSMS.received_at.desc()).limit(50).all()
    return render_template('admin/payments.html', payments=payments, mpesa_sms=mpesa_sms)

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
            'mpesa_number': '0700000000',
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
