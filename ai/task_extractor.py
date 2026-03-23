import json
from datetime import date

import anthropic

import config
from database import get_db
from ai.thread_matcher import find_related_task

SYSTEM_PROMPT = """\
You are MailMind, an intelligent email-to-task assistant.

Your job is to analyze an email and respond with a JSON object.

ALWAYS respond with valid JSON only. No explanation, no markdown, just JSON.

JSON structure:
{
  "has_action_item": boolean,
  "action": "create" | "update" | "complete" | "cancel" | "none",
  "task": {
    "title": "concise action-oriented title (max 80 chars)",
    "priority": "High" | "Medium" | "Low",
    "due_date": "YYYY-MM-DD or null",
    "tags": ["tag1", "tag2"],
    "notes": "summary of email thread for context (2-3 sentences max)",
    "existing_task_id": null
  },
  "reasoning": "one sentence explaining your decision"
}

Rules:
- Only set has_action_item=true if the email explicitly or implicitly asks \
YOU (the recipient) to do something
- Due dates: convert relative language to absolute dates based on today's date
- Priority: High = urgent/deadline/executive sender, Low = FYI/no rush, \
else Medium
- Tags: use broad categories (Finance, Legal, HR, IT, Marketing, Project, \
Personal, Travel, or infer a project name from context)
- If a follow-up email says the task is done or cancelled, set action to \
'complete' or 'cancel' and include the existing_task_id
- Keep task titles action-oriented: start with a verb (Send, Review, Schedule, \
Prepare, Confirm, etc.)"""


def process_email(scanned_email_id):
    """Analyse a scanned email with Claude and create/update tasks."""
    db = get_db()
    email = db.execute(
        "SELECT * FROM scanned_emails WHERE id = ?", (scanned_email_id,)
    ).fetchone()

    if not email:
        db.close()
        return

    # --- build user message ---
    body = (email["subject"] or "") + "\n"  # fallback if no body stored
    # Body is not stored in scanned_emails in current schema, so we use subject + sender context
    # If body column exists, use it
    body_text = ""
    try:
        body_text = email["body"] or ""
    except (IndexError, KeyError):
        pass

    if len(body_text) > 3000:
        body_text = body_text[:3000] + "\n... [truncated]"

    # Check for related task (follow-up detection)
    related_task = find_related_task(email["thread_id"], email["subject"])

    user_parts = [
        f"Today's date: {date.today().isoformat()}",
        f"Subject: {email['subject']}",
        f"From: {email['sender']}",
        f"Received: {email['received_at']}",
    ]
    if body_text:
        user_parts.append(f"Body:\n{body_text}")

    if related_task:
        user_parts.append(
            f"\n--- EXISTING RELATED TASK ---\n"
            f"Task ID: {related_task['id']}\n"
            f"Title: {related_task['title']}\n"
            f"Status: {related_task['status']}\n"
            f"Priority: {related_task['priority']}\n"
            f"Notes: {related_task['notes']}"
        )

    user_message = "\n".join(user_parts)

    # --- call Claude ---
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as e:
        print(f"[task_extractor] Claude API error for email {scanned_email_id}: {e}")
        db.close()
        return

    # --- parse response ---
    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[task_extractor] Bad JSON from Claude for email {scanned_email_id}: {raw[:200]}")
        db.close()
        return

    action = result.get("action", "none")
    task_data = result.get("task", {})
    task_id = None

    if action == "create" and result.get("has_action_item"):
        tags = ",".join(task_data.get("tags", []))
        source_ids = json.dumps([scanned_email_id])
        cursor = db.execute(
            """INSERT INTO tasks
               (title, status, priority, due_date, tags, notes,
                source_email_ids, thread_id)
               VALUES (?, 'Open', ?, ?, ?, ?, ?, ?)""",
            (
                task_data.get("title", "Untitled task")[:80],
                task_data.get("priority", "Medium"),
                task_data.get("due_date"),
                tags,
                task_data.get("notes", ""),
                source_ids,
                email["thread_id"],
            ),
        )
        task_id = cursor.lastrowid

    elif action == "update":
        existing_id = task_data.get("existing_task_id") or (
            related_task["id"] if related_task else None
        )
        if existing_id:
            updates, params = [], []
            if task_data.get("notes"):
                updates.append("notes = ?")
                params.append(task_data["notes"])
            if task_data.get("due_date"):
                updates.append("due_date = ?")
                params.append(task_data["due_date"])
            if task_data.get("priority"):
                updates.append("priority = ?")
                params.append(task_data["priority"])
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(existing_id)
                db.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
            task_id = existing_id

    elif action == "complete":
        existing_id = task_data.get("existing_task_id") or (
            related_task["id"] if related_task else None
        )
        if existing_id:
            db.execute(
                "UPDATE tasks SET status = 'Done', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing_id,),
            )
            task_id = existing_id

    elif action == "cancel":
        existing_id = task_data.get("existing_task_id") or (
            related_task["id"] if related_task else None
        )
        if existing_id:
            db.execute(
                "UPDATE tasks SET status = 'Cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing_id,),
            )
            task_id = existing_id

    # Mark email as processed
    db.execute(
        "UPDATE scanned_emails SET was_processed = 1, task_id_created = ? WHERE id = ?",
        (task_id, scanned_email_id),
    )
    db.commit()
    db.close()

    print(
        f"[task_extractor] Email {scanned_email_id}: action={action}, "
        f"task_id={task_id}, reasoning={result.get('reasoning', '')[:100]}"
    )
    return result
