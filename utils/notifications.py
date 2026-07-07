"""
Notification utilities for unified automation.
"""

from config import PORTAL


def deal_link(deal_id, title=None):
    """Generate BB-code link for deal."""
    name = title or f"Сделка #{deal_id}"
    return f"[URL=https://{PORTAL}/crm/deal/details/{deal_id}/]{name}[/URL]"


def task_link(task_id, title=None, user_id=376):
    """Generate BB-code link for task."""
    name = title or f"Задача #{task_id}"
    return f"[URL=https://{PORTAL}/company/personal/user/{user_id}/tasks/task/view/{task_id}/]{name}[/URL]"


def folder_link(folder_id, name="Папка"):
    """Generate BB-code link for disk folder."""
    return f"[URL=https://{PORTAL}/docs/path/{folder_id}/]{name}[/URL]"


def format_change_notification(deal_id, deal_title, changed_fields, folder_id=None):
    """Format deal change notification."""
    lines = [f"✅ {deal_link(deal_id, deal_title)}"]
    for field, (old, new) in changed_fields.items():
        lines.append(f"  {field}: {old} → {new}")
    if folder_id:
        lines.append(f"  📁 {folder_link(folder_id)}")
    return "\n".join(lines)
