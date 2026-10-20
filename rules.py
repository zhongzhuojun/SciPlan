from __future__ import annotations

import re
from datetime import date, timedelta


WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _last_day(year: int, month: int) -> date:
    first = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return first - timedelta(days=1)


def parse_due(text: str, today: date | None = None):
    """Extract common Chinese and ISO deadline expressions without an API call."""
    today = today or date.today()
    full = re.search(r"(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?", text)
    if full:
        try: return date(int(full.group(1)), int(full.group(2)), int(full.group(3))).isoformat()
        except ValueError: pass
    m = re.search(r"(?<!\d)(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2)); year = today.year if month >= today.month else today.year + 1
        try: return date(year, month, day).isoformat()
        except ValueError: pass
    if re.search(r"今天|今日|当天", text): return today.isoformat()
    if re.search(r"明天|明日", text): return (today + timedelta(days=1)).isoformat()
    if re.search(r"后天", text): return (today + timedelta(days=2)).isoformat()
    rel = re.search(r"(\d+)\s*天(?:内|后|之前|前)", text)
    if rel: return (today + timedelta(days=int(rel.group(1)))).isoformat()
    if re.search(r"一周内|这周内|本周内", text): return (today + timedelta(days=6)).isoformat()
    if re.search(r"两周内|二周内", text): return (today + timedelta(days=14)).isoformat()
    next_week = re.search(r"下周\s*([一二三四五六日天])", text)
    if next_week:
        return (today + timedelta(days=7 + WEEKDAYS[next_week.group(1)] - today.weekday())).isoformat()
    this_week = re.search(r"(?:本周|这周)\s*([一二三四五六日天])", text)
    if this_week:
        return (today + timedelta(days=(WEEKDAYS[this_week.group(1)] - today.weekday()) % 7)).isoformat()
    week = re.search(r"(?:周|星期)\s*([一二三四五六日天])", text)
    if week:
        return (today + timedelta(days=(WEEKDAYS[week.group(1)] - today.weekday()) % 7)).isoformat()
    if re.search(r"下周", text): return (today + timedelta(days=7 - today.weekday())).isoformat()
    if re.search(r"月底|月末", text): return _last_day(today.year, today.month).isoformat()
    if re.search(r"下月底|下月末", text):
        month = 1 if today.month == 12 else today.month + 1; year = today.year + (today.month == 12)
        return _last_day(year, month).isoformat()
    return None


def clamp_priority(ai_priority: int, due: str | None, text: str = "") -> int:
    """P1 is most urgent; the local rule can only raise urgency."""
    ai = max(1, min(4, int(ai_priority or 3)))
    if not due:
        return min(ai, 2) if re.search(r"截止|ddl|deadline|必须.*前|催|赶紧|尽快", text, re.I) else ai
    try: days = (date.fromisoformat(due) - date.today()).days
    except ValueError: days = 99
    floor = 1 if days <= 1 else 2 if days <= 3 else 3 if days <= 7 else 4
    return min(ai, floor)
