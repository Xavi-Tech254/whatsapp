import re
import json
import os
from datetime import datetime, date
from models import db, User, Category, Payment, BotSession, Settings

def get_setting(key, default=''):
    s = Settings.query.filter_by(key=key).first()
    return s.value if s else default

def get_session(number):
    sess = BotSession.query.filter_by(whatsapp_number=number).first()
    if not sess:
        sess = BotSession(whatsapp_number=number, state='start', breadcrumb='[]')
        db.session.add(sess)
        db.session.commit()
    return sess

def get_user(number):
    return User.query.filter_by(whatsapp_number=number).first()

def get_breadcrumb(sess):
    try:
        return json.loads(sess.breadcrumb or '[]')
    except:
        return []

def set_breadcrumb(sess, crumbs):
    sess.breadcrumb = json.dumps(crumbs)

def make_response(reply, buttons=None, banner=None, file_path=None):
    resp = {'reply': reply}
    if buttons:
        resp['buttons'] = buttons
    if banner:
        resp['banner'] = banner
    if file_path:
        resp['file_path'] = file_path
    return resp

def menu_buttons(cats, include_back=False):
    buttons = []
    for cat in cats:
        price_str = f" — Ksh {int(cat.price)}" if cat.price > 0 else (" — FREE" if not cat.is_folder() else "")
        buttons.append({'id': str(cat.id), 'text': f"{cat.icon} {cat.name}{price_str}"})
    if include_back:
        buttons.append({'id': '0', 'text': ' Back to Main Menu'})
    return buttons

def numbered_list(cats):
    lines = []
    for i, cat in enumerate(cats, 1):
        price_str = f" — Ksh {int(cat.price)}" if cat.price > 0 else (" — FREE" if not cat.is_folder() else "")
        lines.append(f"{i}. {cat.icon} {cat.name}{price_str}")
    lines.append("\n0. Main Menu")
    return '\n'.join(lines)

def handle_message(number, text):
    if len(number) > 20 or 'newsletter' in number or 'broadcast' in number:
        return None
    text = text.strip()
    sess = get_session(number)
    user = get_user(number)
    bot_name = get_setting('bot_name', 'Dev Clin Studies')
    banner_path = get_setting('banner_path', '')
    flask_url = os.environ.get('FLASK_URL', '')
    banner_url = f"{flask_url}{banner_path}" if banner_path and flask_url else None

    if text.lower() in ['menu', 'hi', 'hello', 'hey', 'start', 'home', '0'] or text == 'MAIN_MENU':
        sess.state = 'menu'
        sess.current_category_id = None
        sess.pending_category_id = None
        set_breadcrumb(sess, [])
        db.session.commit()
        return show_main_menu(user, bot_name, banner_url)

    if not user:
        if sess.state in ['start', 'register']:
            if sess.state == 'start':
                sess.state = 'register'
                db.session.commit()
                return make_response(
                    f"👋 Welcome to *{bot_name}*!\n\n"
                    "Create your account to continue.\n\n"
                    "Send your details as:\n"
                    "*USERNAME#PASSWORD*\n\n"
                    "Example: John254#mypass123"
                )
            if '#' not in text:
                return make_response("❌ Wrong format. Use:\n*USERNAME#PASSWORD*\n\nExample: John254#mypass123")
            uname, pwd = text.split('#', 1)
            uname, pwd = uname.strip(), pwd.strip()
            if len(uname) < 3:
                return make_response("❌ Username must be at least 3 characters.")
            if len(pwd) < 4:
                return make_response("❌ Password must be at least 4 characters.")
            if User.query.filter_by(username=uname).first():
                return make_response(f"❌ Username *{uname}* is taken. Try another.")
            new_user = User(whatsapp_number=number, username=uname, password=pwd)
            db.session.add(new_user)
            sess.state = 'menu'
            db.session.commit()
            user = new_user
            return show_main_menu(user, bot_name, banner_url, welcome=True)
        sess.state = 'register'
        db.session.commit()
        return make_response(f"👋 Welcome to *{bot_name}*!\n\nSend your details as:\n*USERNAME#PASSWORD*")

    if sess.state in ['menu', 'browsing']:
        if sess.state == 'menu' or not sess.current_category_id:
            cats = Category.query.filter_by(parent_id=None, is_active=True).order_by(Category.order_index).all()
            title = f"🎓 *{bot_name}*\n\nWhat do you need today?"
            include_back = False
        else:
            current = Category.query.get(sess.current_category_id)
            cats = current.active_children() if current else []
            crumbs = get_breadcrumb(sess)
            path = ' › '.join([Category.query.get(c).name for c in crumbs if Category.query.get(c)])
            title = f"📂 *{current.name}*" + (f"\n_{path}_" if path else "")
            include_back = True

        if text.isdigit() or text in [str(c.id) for c in cats]:
            choice_num = int(text)

            if choice_num == 0:
                crumbs = get_breadcrumb(sess)
                if crumbs:
                    crumbs.pop()
                    set_breadcrumb(sess, crumbs)
                    sess.current_category_id = crumbs[-1] if crumbs else None
                    sess.state = 'browsing' if crumbs else 'menu'
                else:
                    sess.state = 'menu'
                    sess.current_category_id = None
                db.session.commit()
                return show_main_menu(user, bot_name, banner_url)

            selected = next((c for c in cats if c.id == choice_num), None)
            if not selected:
                idx = choice_num - 1
                if 0 <= idx < len(cats):
                    selected = cats[idx]

            if not selected:
                return make_response(
                    f"❌ Invalid choice. Please pick 1-{len(cats)}.\n\n{numbered_list(cats)}",
                    buttons=menu_buttons(cats, include_back)
                )

            if selected.is_folder():
                crumbs = get_breadcrumb(sess)
                if sess.current_category_id:
                    crumbs.append(sess.current_category_id)
                set_breadcrumb(sess, crumbs)
                sess.current_category_id = selected.id
                sess.state = 'browsing'
                db.session.commit()
                children = selected.active_children()
                path_parts = [Category.query.get(c).name for c in crumbs if Category.query.get(c)]
                path_str = ' › '.join(path_parts)
                header = f"📂 *{selected.name}*" + (f"\n_{path_str}_" if path_str else "")
                full_text = header + f"\n\n{numbered_list(children)}"
                return make_response(full_text, buttons=menu_buttons(children, include_back=True))

            if selected.is_free():
                file_path = None
                resp_text = f"🆓 *{selected.icon} {selected.name}*\n\n"
                if selected.link:
                    resp_text += f"🔗 {selected.link}"
                elif selected.file_path:
                    file_path = selected.file_path
                    resp_text += "📎 Your file is attached."
                resp_text += "\n\nSend *menu* to go back. 🎓"
                return make_response(resp_text, buttons=[{'id': 'MAIN_MENU', 'text': '🏠 Main Menu'}], file_path=file_path)

            # Paid item — send payment link button
            pay_url = f"{flask_url}/pay/{selected.id}/{number}"
            return make_response(
                f"📦 *{selected.icon} {selected.name}*\n"
                f"💰 Price: *Ksh {int(selected.price)}*\n\n"
                f"💳 *Tap to pay:*\n{pay_url}\n\n"
                f"Send *0* to cancel."
            )

        full_text = title + f"\n\n{numbered_list(cats)}"
        return make_response(full_text, buttons=menu_buttons(cats, include_back))

    sess.state = 'menu'
    db.session.commit()
    return show_main_menu(user, bot_name, banner_url)


def show_main_menu(user, bot_name, banner_url, welcome=False):
    cats = Category.query.filter_by(parent_id=None, is_active=True).order_by(Category.order_index).all()
    if welcome:
        greeting = f"✅ Account created! Welcome, *{user.username}*! 🎉\n\n"
    elif user:
        greeting = f"👋 Welcome back, *{user.username}*! 😊\n\n"
    else:
        greeting = f"👋 Welcome to *{bot_name}*!\n\n"

    if not cats:
        return make_response(greeting + f"🎓 *{bot_name}*\n\n❌ No items available yet.")

    cat_list = numbered_list(cats)
    text = greeting + f"🎓 *{bot_name}*\n\nWhat do you need today?\n\n{cat_list}"
    return make_response(text, buttons=menu_buttons(cats), banner=banner_url)
