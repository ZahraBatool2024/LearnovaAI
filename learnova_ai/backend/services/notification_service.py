"""In-app deadline notification service.

StudyHub creates an in-app notification exactly two days before a deadline.
"""

import datetime
import logging

from backend.models import DeadlineItem, Notification, Course

logger = logging.getLogger("notification_service")
ALERT_WINDOW_DAYS = 2

def _days_until(due_date_str: str, today: datetime.date) -> int:
    due = datetime.date.fromisoformat(due_date_str)
    return (due - today).days

def check_and_create_notifications(db, today: datetime.date = None):
    if today is None:
        today = datetime.date.today()
    today_str = today.isoformat()
    created = []
    for item in db.query(DeadlineItem).all():
        try:
            days_left = _days_until(item.due_date, today)
        except ValueError:
            continue
        if days_left != ALERT_WINDOW_DAYS:
            continue
        already = db.query(Notification).filter(
            Notification.deadline_item_id == item.id,
            Notification.fired_for_date == today_str
        ).first()
        if already:
            continue
        course = db.query(Course).filter(Course.id == item.course_id).first()
        course_name = course.name if course else "Unknown course"
        message = f'[{course_name}] "{item.title}" ({item.item_type}) is due in {ALERT_WINDOW_DAYS} days, on {item.due_date}.'
        note = Notification(deadline_item_id=item.id, course_id=item.course_id, message=message, fired_for_date=today_str)
        db.add(note)
        created.append(note)
    if not created:
        return []
    db.commit()
    return created

def start_scheduler(session_factory, hour: int = 8, minute: int = 0):
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    def job():
        db = session_factory()
        try:
            check_and_create_notifications(db)
        finally:
            db.close()
    scheduler.add_job(job, "cron", hour=hour, minute=minute, id="deadline_alert_scan", replace_existing=True)
    scheduler.start()
    return scheduler
