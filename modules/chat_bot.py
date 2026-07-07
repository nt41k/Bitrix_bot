"""
Chat Bot Module - Process commands from chat messages.
"""

from utils.logger import get_module_logger

logger = get_module_logger("chat_bot")

import re
import json
from config import (
    BITRIX_WEBHOOK, CHAT_WORKFLOW, COMMAND_FIELDS, FIELD_LABELS,
    DEPT_LOGISTICS, DEPT_EXPEDITORS, DEPT_DECLARANTS, DEPT_WAREHOUSE, DEPT_TRANSPORT,
    CRM_TO_GOOGLE, PORTAL, COMMAND_TO_DEPT, GOOGLE_SHEETS
)
from api_client import (
    b24_call, b24_post, update_deal, search_deals_by_field,
    add_timeline_comment, log_to_chat, update_container_data
)
from state import get_module_state
from utils.notifications import deal_link
from modules.google_sync import writeback_to_google, fetch_google_data


def get_chat_messages(chat_id, limit=50):
    """Get messages from chat via webhook."""
    return b24_call("im.dialog.messages.get", {
        "DIALOG_ID": f"chat{chat_id}",
        "LIMIT": limit
    })


def parse_message(text):
    """Parse command message format:
    !Consignment
    1. Value
    2. Value
    
    Commands must start with ! prefix to distinguish from regular chat messages.
    """
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return None, {}
    
    # Commands must start with ! prefix
    first_line = lines[0].strip()
    if not first_line.startswith("!"):
        return None, {}
    
    consignment = first_line[1:].strip()  # Remove ! prefix
    if not consignment:
        return None, {}
    
    commands = {}
    
    for line in lines[1:]:
        match = re.match(r"^(\d+)\.\s*(.+)$", line)
        if match:
            cmd_num = match.group(1)
            value = match.group(2).strip()
            if cmd_num in COMMAND_FIELDS:
                commands[COMMAND_FIELDS[cmd_num]] = value
    
    return consignment, commands


def get_user_departments(user_id):
    """Get all user department IDs via Bitrix24 REST API.
    
    Returns set of department IDs. Handles users in multiple departments.
    Uses UF_DEPARTMENT field which contains array of all department IDs.
    """
    try:
        result = b24_call("user.get", {
            "ID": user_id,
            "SELECT": ["ID", "UF_DEPARTMENT"]
        })
        if result and "error" not in result:
            users = result.get("result", [])
            if users:
                user_data = users[0]
                dept = user_data.get("UF_DEPARTMENT", [])
                if isinstance(dept, list):
                    return set(int(d) for d in dept if d)
                elif isinstance(dept, int):
                    return {dept}
                elif isinstance(dept, str):
                    # Sometimes it's a comma-separated string
                    return set(int(d.strip()) for d in dept.split(",") if d.strip())
    except Exception as e:
        print(f"[chat_bot] Error getting departments for user {user_id}: {e}")
    return set()


def get_user_name(user_id):
    """Get user name via VibeCode. Returns full name or empty string."""
    try:
        from api_client import vibe_api_call
        result = vibe_api_call(f"/users/{user_id}")
        if result and result.get("success"):
            user_data = result.get("data", {})
            name = user_data.get("name") or ""
            last_name = user_data.get("lastName") or ""
            if name and last_name:
                return f"{name} {last_name}"
            return name or last_name or str(user_id)
    except Exception as e:
        print(f"[chat_bot] Error getting name for user {user_id}: {e}")
    return str(user_id)


def check_command_access(command_num, user_id):
    """Check if user from command's department can execute this command.
    
    Returns (allowed: bool, user_depts: set, command_dept: int|None)
    """
    user_depts = get_user_departments(user_id)
    command_dept = COMMAND_TO_DEPT.get(command_num)
    
    if not command_dept:
        return False, user_depts, None
    
    if not user_depts:
        return False, set(), command_dept
    
    return command_dept in user_depts, user_depts, command_dept


def get_dept_name(dept_id):
    """Get human-readable department name."""
    dept_names = {
        DEPT_DECLARANTS: "����������",
        DEPT_EXPEDITORS: "�����������",
        32: "���������",
        DEPT_LOGISTICS: "�������",
        DEPT_WAREHOUSE: "�����",
        DEPT_IT: "IT",
    }
    return dept_names.get(dept_id, f"����� #{dept_id}")


def find_row_in_google_sheets(consignment, container=None, sheet_name=None):
    """Find row number in Google Sheets by consignment.
    
    Returns relative rowNumber for Google Apps Script (1 = first data row).
    If sheet_name is provided, searches only that sheet.
    If sheet_name is None, searches all GOOGLE_SHEETS and returns first match.
    If container is provided, requires exact match of both consignment and container.
    """
    try:
        sheets_to_search = [sheet_name] if sheet_name else GOOGLE_SHEETS
        
        for sheet in sheets_to_search:
            data = fetch_google_data(sheet)
            rows = data.get("data", [])
            if not rows:
                continue
            
            headers = rows[0]
            try:
                identifier_idx = headers.index("����� ������������� ��������� (����������)")
            except ValueError:
                continue
            
            # If container specified, find container column index
            container_idx = None
            if container:
                try:
                    container_idx = headers.index("����� ������������� �������� (���������)")
                except ValueError:
                    continue
            
            for row_idx, row in enumerate(rows[1:], start=1):
                if len(row) > identifier_idx and row[identifier_idx] == consignment:
                    if container and container_idx is not None:
                        # Need exact match: consignment + container
                        if len(row) > container_idx and row[container_idx] == container:
                            return row_idx  # Exact match found
                    else:
                        # Match by consignment only (first match)
                        return row_idx
        
        return None
    except Exception:
        return None


def run(state):
    mod_state = get_module_state(state, "chat_bot")
    # Per-chat last_message_id tracking
    chat_last_ids = mod_state.get("chat_last_ids", {})
    
    total_processed = 0
    total_messages = 0
    total_writebacks = 0
    writeback_errors = 0
    
    chat_id = CHAT_WORKFLOW
    last_id = chat_last_ids.get(str(chat_id), 0)
    
    result = get_chat_messages(chat_id)
    if "error" in result:
        print(f"[chat_bot] Failed to get messages from chat{chat_id}: {result['error']}")
        return f"0 messages, 0 processed, 0 writebacks, 0 wb errors"
    
    messages = result.get("result", {}).get("messages", [])
    if not messages:
        return f"0 messages, 0 processed, 0 writebacks, 0 wb errors"
    
    total_messages = len(messages)
    processed = 0
    new_last_id = last_id
    
    # Process in chronological order (oldest first)
    for msg in reversed(messages):
        msg_id = int(msg.get("id", 0))
        if msg_id <= last_id:
            continue
        
        text = msg.get("text", "")
        author_id = msg.get("author_id", "")
        
        # Skip bot messages (bot ID = 376)
        if str(author_id) == "376":
            new_last_id = max(new_last_id, msg_id)
            continue
        
        consignment, commands = parse_message(text)
        if not consignment or not commands:
            new_last_id = max(new_last_id, msg_id)
            continue
        
        # Check department access for each command
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        access_violations = []
        allowed_commands = {}
        
        for line in lines[1:]:
            match = re.match(r"^(\d+)\.\s*(.+)$", line)
            if match:
                cmd_num = match.group(1)
                value = match.group(2).strip()
                if cmd_num in COMMAND_FIELDS:
                    allowed, user_dept, cmd_dept = check_command_access(cmd_num, author_id)
                    if allowed:
                        allowed_commands[COMMAND_FIELDS[cmd_num]] = value
                    else:
                        access_violations.append({
                            "cmd": cmd_num,
                            "label": FIELD_LABELS.get(COMMAND_FIELDS.get(cmd_num, ""), cmd_num),
                            "user_dept": user_dept,
                            "cmd_dept": cmd_dept,
                        })
        
        # If there are access violations, notify and skip
        if access_violations:
            dept_names = []
            for v in access_violations:
                cmd_dept_name = get_dept_name(v["cmd_dept"]) if v["cmd_dept"] else "����������"
                dept_names.append(f"{v['label']} (������ {cmd_dept_name})")
            user_name = get_user_name(author_id)
            reply = f"? ������ ��������: {', '.join(dept_names)}\n���������: [USER={author_id}]{user_name}[/USER]"
            log_to_chat(reply, chat_id=CHAT_WORKFLOW)
            new_last_id = max(new_last_id, msg_id)
            continue
        
        # Use only allowed commands
        commands = allowed_commands
        if not commands:
            new_last_id = max(new_last_id, msg_id)
            continue
        
        # Find deal
        deals = search_deals_by_field("UF_CRM_1778645007478", consignment)
        deal_list = deals.get("result", [])
        
        if not deal_list:
            user_name = get_user_name(author_id)
            reply = f"❌ Сделка не найдена: {consignment}\nСотрудник: [USER={author_id}]{user_name}[/USER]"
            log_to_chat(reply, chat_id=CHAT_WORKFLOW)
            new_last_id = max(new_last_id, msg_id)
            continue
        
        deal_id = deal_list[0]["ID"]
        deal_title = deal_list[0].get("TITLE", f"Сделка #{deal_id}")
        
        # Get current field values for "before" comparison
        current_deal = deal_list[0]
        
        # Extract container name from second line (if present and not a command)
        container = None
        if len(lines) > 1 and not re.match(r"^\d+\.\s+", lines[1]):
            container = lines[1]
        
        # Separate regular commands (1-17) from container commands (18-20)
        # All commands (1-20) are now regular commands with unified handling
        regular_commands = commands
        container_commands = {}
        
        update_success = True
        update_lines = []
        
        # Process regular commands (1-17)
        if regular_commands:
            result = update_deal(deal_id, regular_commands)
            if "error" not in result:
                for crm_field, value in regular_commands.items():
                    label = FIELD_LABELS.get(crm_field, crm_field)
                    old_value = current_deal.get(crm_field, "")
                    update_lines.append(f"���������: {label}")
                    update_lines.append(f"����: {old_value}")
                    update_lines.append(f"�����: {value}")
            else:
                update_success = False
                error_msg = result.get("error_description", result.get("error", "Unknown error"))
                print(f"[chat_bot] Failed to update deal {deal_id}: {error_msg}")
        
        # Process container commands (18-20)
        if update_success and update_lines:
            # Timeline log
            changes = ", ".join(f"{FIELD_LABELS.get(k, k)}={v}" for k, v in commands.items())
            add_timeline_comment(deal_id, f"��������� �� ����: {changes}")
            
            # Build and send notification
            user_name = get_user_name(author_id)
            msg = f"? [URL=https://{PORTAL}/crm/deal/details/{deal_id}/]{consignment}[/URL]\n" + "\n".join(update_lines) + f"\n���������: [USER={author_id}]{user_name}[/USER]"
            notify_result = log_to_chat(msg, chat_id=CHAT_WORKFLOW)
            print(f"[chat_bot] Notification result: {notify_result}")
            processed += 1
            
            # Writeback to Google Sheets for regular commands only
            if regular_commands:
                try:
                    row_number = find_row_in_google_sheets(consignment, container)
                    if row_number:
                        wb_changes = {}
                        for crm_field, value in regular_commands.items():
                            if crm_field.startswith("ufCrm_"):
                                uf_field = "UF_CRM_" + crm_field[6:]
                            else:
                                uf_field = crm_field
                            if uf_field in CRM_TO_GOOGLE:
                                g_col_name = CRM_TO_GOOGLE[uf_field]
                                wb_changes[g_col_name] = value
                        if wb_changes:
                            wb_result = writeback_to_google([{
                                "conosament": consignment,
                                "container": container,
                                "changes": wb_changes
                            }])
                            if wb_result.get("success"):
                                total_writebacks += 1
                            else:
                                writeback_errors += 1
                            print(f"[chat_bot] Writeback result: {wb_result}")
                except Exception as e:
                    writeback_errors += 1
                    print(f"[chat_bot] Writeback error (non-critical): {e}")
        elif not update_success:
            user_name = get_user_name(author_id)
            msg = f"❌ [URL=https://{PORTAL}/crm/deal/details/{deal_id}/]{consignment}[/URL]\nОшибка обновления\nСотрудник: [USER={author_id}]{user_name}[/USER]"
            notify_result = log_to_chat(msg, chat_id=CHAT_WORKFLOW)
            print(f"[chat_bot] Notification result: {notify_result}")
        
        new_last_id = max(new_last_id, msg_id)
    
    # Update per-chat last message id
    chat_last_ids[str(chat_id)] = new_last_id
    total_processed += processed
    
    mod_state["chat_last_ids"] = chat_last_ids
    return f"{total_messages} messages, {total_processed} processed, {total_writebacks} writebacks, {writeback_errors} wb errors"
