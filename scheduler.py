from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import requests
import random

scheduler = BackgroundScheduler()

def send_daily_quotes(app):
    """Send daily motivational quotes to all users"""
    with app.app_context():
        from models import db, User, DailyQuote, Settings
        quotes = DailyQuote.query.filter_by(is_active=True).all()
        if not quotes:
            return
        quote = random.choice(quotes)
        users = User.query.all()
        bot_name = Settings.query.filter_by(key='bot_name').first()
        name = bot_name.value if bot_name else 'Dev Clin Studies'

        msg = f"🌟 *Daily Quote — {name}*\n\n_{quote.text}_"
        if quote.author:
            msg += f"\n\n— *{quote.author}*"
        msg += "\n\nSend *menu* to browse our content 📚"

        bridge_url = Settings.query.filter_by(key='bridge_url').first()
        if not bridge_url:
            return

        for user in users:
            try:
                requests.post(f"{bridge_url.value}/send", json={
                    'number': user.whatsapp_number,
                    'message': msg
                }, timeout=5)
            except:
                pass

def init_scheduler(app):
    # 6:00 AM, 9:30 AM, 12:00 PM, 3:00 PM, 9:00 PM EAT (UTC+3)
    times = [
        (3, 0),   # 6AM EAT
        (6, 30),  # 9:30AM EAT
        (9, 0),   # 12PM EAT
        (12, 0),  # 3PM EAT
        (18, 0),  # 9PM EAT
    ]
    for hour, minute in times:
        scheduler.add_job(
            send_daily_quotes,
            CronTrigger(hour=hour, minute=minute),
            args=[app],
            id=f'quote_{hour}_{minute}',
            replace_existing=True
        )
    scheduler.start()
    return scheduler
