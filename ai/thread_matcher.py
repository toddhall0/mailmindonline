import re

from database import get_db


def find_related_task(thread_id, subject):
    """Find an existing task related to this email thread or subject.

    1. Check scanned_emails for same thread_id with an associated task.
    2. Fall back to fuzzy subject matching against open task titles.
    Returns the matched task row or None.
    """
    db = get_db()

    # --- Match by thread_id ---
    if thread_id:
        row = db.execute(
            """SELECT t.* FROM tasks t
               JOIN scanned_emails se ON se.task_id_created = t.id
               WHERE se.thread_id = ? AND se.task_id_created IS NOT NULL
               ORDER BY t.created_at DESC LIMIT 1""",
            (thread_id,),
        ).fetchone()
        if row:
            db.close()
            return row

    # --- Fuzzy subject match ---
    if subject:
        clean = _strip_prefixes(subject).strip().lower()
        if len(clean) < 3:
            db.close()
            return None

        open_tasks = db.execute(
            "SELECT * FROM tasks WHERE status IN ('Open', 'In Progress')"
        ).fetchall()
        db.close()

        best, best_score = None, 0.0
        for task in open_tasks:
            score = _similarity(clean, task["title"].lower())
            if score > best_score:
                best, best_score = task, score

        if best_score >= 0.45:
            return best

    else:
        db.close()

    return None


_PREFIX_RE = re.compile(r"^(re|fwd|fw)\s*:\s*", re.IGNORECASE)


def _strip_prefixes(text):
    """Remove Re:/Fwd:/Fw: prefixes."""
    prev = None
    while prev != text:
        prev = text
        text = _PREFIX_RE.sub("", text)
    return text


def _similarity(a, b):
    """Simple token-overlap similarity ratio."""
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    return len(overlap) / max(len(tokens_a), len(tokens_b))
