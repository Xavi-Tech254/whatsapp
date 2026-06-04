from app import app, init_db
from scheduler import init_scheduler

init_db()

try:
    init_scheduler(app)
except Exception as e:
    print(f"Scheduler warning: {e}")
