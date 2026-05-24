from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    whatsapp_number = db.Column(db.String(20), unique=True, nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    payments = db.relationship('Payment', backref='user', lazy=True)
    sessions = db.relationship('BotSession', backref='user', lazy=True)

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    icon = db.Column(db.String(10), default='📁')
    # type: 'folder', 'file', 'link'
    cat_type = db.Column(db.String(10), default='folder')
    price = db.Column(db.Float, default=0.0)
    file_path = db.Column(db.String(500), nullable=True)
    link = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    children = db.relationship('Category', backref=db.backref('parent', remote_side=[id]), lazy=True)
    payments = db.relationship('Payment', backref='category', lazy=True)

    def active_children(self):
        return sorted([c for c in self.children if c.is_active], key=lambda x: x.order_index)

    def is_folder(self):
        return self.cat_type == 'folder'

    def is_free(self):
        return self.price == 0.0

    def to_dict(self):
        return {
            'id': self.id,
            'parent_id': self.parent_id,
            'name': self.name,
            'icon': self.icon,
            'cat_type': self.cat_type,
            'price': self.price,
            'file_path': self.file_path,
            'link': self.link,
            'is_active': self.is_active,
            'order_index': self.order_index,
            'children_count': len(self.active_children())
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    mpesa_code = db.Column(db.String(20), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MpesaSMS(db.Model):
    """Stores forwarded Mpesa SMS from admin's phone"""
    __tablename__ = 'mpesa_sms'
    id = db.Column(db.Integer, primary_key=True)
    mpesa_code = db.Column(db.String(20), unique=True, nullable=False)
    amount = db.Column(db.Float, nullable=False)
    sender_phone = db.Column(db.String(20), nullable=True)
    raw_sms = db.Column(db.Text, nullable=False)
    used = db.Column(db.Boolean, default=False)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)

class BotSession(db.Model):
    __tablename__ = 'bot_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    whatsapp_number = db.Column(db.String(20), unique=True, nullable=False)
    state = db.Column(db.String(50), default='start')
    current_category_id = db.Column(db.Integer, nullable=True)
    pending_category_id = db.Column(db.Integer, nullable=True)
    breadcrumb = db.Column(db.Text, default='[]')  # JSON list of category ids
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class AdminUser(db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

class DailyQuote(db.Model):
    __tablename__ = 'daily_quotes'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
