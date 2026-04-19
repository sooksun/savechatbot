from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from .config import get_settings
from .services.summarizer import run_daily, run_weekly

settings = get_settings()
_scheduler: BackgroundScheduler | None = None


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":", 1)
    return int(h), int(m)


def start() -> None:
    global _scheduler
    if _scheduler:
        return
    sched = BackgroundScheduler(timezone=ZoneInfo(settings.TIMEZONE))

    dh, dm = _parse_hm(settings.DAILY_SUMMARY_AT)
    sched.add_job(run_daily, CronTrigger(hour=dh, minute=dm), id="daily", replace_existing=True)

    wh, wm = _parse_hm(settings.WEEKLY_SUMMARY_AT)
    sched.add_job(
        run_weekly,
        CronTrigger(day_of_week=settings.WEEKLY_SUMMARY_DOW, hour=wh, minute=wm),
        id="weekly",
        replace_existing=True,
    )
    sched.start()
    _scheduler = sched


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
