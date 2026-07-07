"""
File Processor Module - Process files uploaded to chat by consignment.
Features: exact consignment match, department-aware folders, container subfolders.
"""

from utils.logger import get_module_logger

logger = get_module_logger("file_processor")

import re
import os
import base64
import time
import requests
import json
from config import (
    CHAT_WORKFLOW, DEAL_FOLDER_PARENT_ID, PORTAL,
    DEPT_FOLDER_NAMES, DEPT_DECLARANTS, DEPT_EXPEDITORS,
    DEPT_WAREHOUSE, DEPT_LOGISTICS, DEPT_TRANSPORT,
    HASHTAG_TO_DEPT, DEPT_KEYWORDS
)
from api_client import b24_call, log_to_chat, vibe_api_call
from state import get_module_state


def extract_consignment_from_text(text):
    """Extract consignment number from message text."""
    if not text:
        return None
    
    # Pattern 1: Explicit mention
    explicit_patterns = [
        r"[Кк]оносамент[:\s]+([A-Za-z0-9\/\\\-]+)",
        r"[Кк]он[:\s]+([A-Za-z0-9\/\\\-]+)",
    ]
    for pattern in explicit_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    
    # Pattern 2: Consignment codes — most specific first
    consignment_patterns = [
        r"[A-Z0-9]+/[A-Z0-9]+",           # Complex slash: HA183CA05/AM256305
        r"\b[A-Z]+/\d+\b",                 # Simple slash: AKK/123
        r"\b[A-Z]+\\\d+\b",                # Backslash: AKK\123
        r"\b\d+[A-Z]{2,}\d+[A-Z0-9\/]*\b", # Starts with digits: 07BK089/42ZB219
        r"\b[A-Z]{3,}\d+[A-Z]*\d*\b",     # Generic: AKKMUO26000365SRV
        r"\b[A-Z]{2,4}\d{6,}\b",          # Generic short form
    ]
    for pattern in consignment_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    
    # Pattern 3: First non-empty line as fallback
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if lines:
        first_line = lines[0]
        if len(first_line) < 50 and " " not in first_line:
            return first_line
    
    return None


def extract_container_from_text(text):
    """Extract container name from second line if it's not a command."""
    if not text:
        return None
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) >= 2:
        second_line = lines[1]
        # If second line doesn't look like a command (N. Value), treat as container
        if not re.match(r"^\d+\.\s+", second_line):
            return second_line
    return None


def extract_department_from_text(text):
    """Extract explicit department from message text via hashtag or keyword.
    
    Returns (dept_id, dept_folder_name) or (None, None) if not found.
    Priority: #hashtag > keyword in text > None
    """
    if not text:
        return None, None
    
    # Pattern 1: Hashtag #отдел
    hashtag_match = re.search(r'#(\w+)', text)
    if hashtag_match:
        tag = hashtag_match.group(1).lower()
        dept_id = HASHTAG_TO_DEPT.get(tag)
        if dept_id:
            return dept_id, DEPT_FOLDER_NAMES.get(dept_id)
    
    # Pattern 2: Department keyword as standalone word (not after #)
    text_lower = text.lower()
    for keyword, dept_id in DEPT_KEYWORDS.items():
        # Match as whole word to avoid partial matches
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            return dept_id, DEPT_FOLDER_NAMES.get(dept_id)
    
    return None, None


def get_user_name(user_id):
    """Get user name via VibeCode."""
    try:
        result = vibe_api_call(f"/users/{user_id}")
        if result and result.get("success"):
            user_data = result.get("data", {})
            name = user_data.get("name") or ""
            last_name = user_data.get("lastName") or ""
            if name and last_name:
                return f"{name} {last_name}"
            return name or last_name or str(user_id)
    except Exception:
        pass
    return str(user_id)


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
                    return set(int(d.strip()) for d in dept.split(",") if d.strip())
    except Exception:
        pass
    return set()


def get_chat_messages_with_files(chat_id, limit=20):
    """Get recent messages that contain files."""
    result = b24_call("im.dialog.messages.get", {
        "DIALOG_ID": f"chat{chat_id}",
        "LIMIT": limit
    })
    if "error" in result:
        return []
    
    if isinstance(result, list):
        messages = result
    elif isinstance(result, dict):
        messages = result.get("result", {}).get("messages", [])
        if not messages and "messages" in result:
            messages = result["messages"]
    else:
        return []
    
    file_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        params = msg.get("params", {})
        if isinstance(params, dict) and params.get("FILE_ID"):
            file_ids = params["FILE_ID"]
            if isinstance(file_ids, list):
                file_ids = [str(fid) for fid in file_ids]
            else:
                file_ids = [str(file_ids)]
            
            file_messages.append({
                "message_id": msg.get("id"),
                "file_ids": file_ids,
                "text": msg.get("text", ""),
                "author_id": msg.get("author_id", ""),  # B24 REST = snake_case
            })
    return file_messages


def sanitize_folder_name(name):
    """Replace forbidden chars for Bitrix24 Disk folder names."""
    return name.replace("/", "-").replace("\\", "-")


def get_or_create_subfolder(parent_folder_id, folder_name):
    """Get or create a subfolder inside a parent folder."""
    safe_name = sanitize_folder_name(folder_name)
    
    # Try to create
    folder_result = b24_call("disk.folder.addsubfolder", {
        "id": parent_folder_id,
        "data[NAME]": safe_name,
        "data[CREATED_BY]": "376"
    })
    
    if "error" in folder_result:
        # Folder may already exist — search for it
        children = b24_call("disk.folder.getchildren", {"id": parent_folder_id})
        for child in children.get("result", []) if isinstance(children, dict) else []:
            if child.get("NAME") == safe_name:
                return child.get("ID")
        return None
    
    new_folder = folder_result.get("result", {})
    return new_folder.get("ID")


def get_or_create_deal_folder(deal_id, consignment, dept_folder_name=None, container_name=None):
    """Get or create disk folder hierarchy for deal.
    
    Structure: TEMP NEW / {consignment} / {dept} / {container}
    """
    # Get existing folder info from deal
    deals = b24_call("crm.deal.get", {"ID": deal_id})
    deal = deals.get("result", {}) if isinstance(deals, dict) else {}
    
    folder_id = deal.get("UF_CRM_1779917649707")
    disk_link = deal.get("UF_CRM_1780368582410")
    
    # If no consignment folder yet, create it
    if not folder_id:
        parent_folder_id = DEAL_FOLDER_PARENT_ID
        safe_name = sanitize_folder_name(consignment)
        
        folder_result = b24_call("disk.folder.addsubfolder", {
            "id": parent_folder_id,
            "data[NAME]": safe_name,
            "data[CREATED_BY]": "376"
        })
        
        if "error" in folder_result:
            # Try to find existing
            children = b24_call("disk.folder.getchildren", {"id": parent_folder_id})
            for child in children.get("result", []) if isinstance(children, dict) else []:
                if child.get("NAME") == safe_name:
                    folder_id = child.get("ID")
                    disk_link = child.get("DETAIL_URL")
                    break
        else:
            new_folder = folder_result.get("result", {})
            folder_id = new_folder.get("ID")
            disk_link = new_folder.get("DETAIL_URL")
        
        if folder_id and disk_link:
            b24_call("crm.deal.update", {
                "ID": deal_id,
                "FIELDS[UF_CRM_1779917649707]": folder_id,
                "FIELDS[UF_CRM_1780368582410]": disk_link
            })
    
    if not folder_id:
        return None, None, None
    
    # Create department subfolder if needed
    current_folder_id = folder_id
    dept_folder_id = None
    if dept_folder_name:
        dept_folder_id = get_or_create_subfolder(folder_id, dept_folder_name)
        if dept_folder_id:
            current_folder_id = dept_folder_id
    
    # Create container subfolder if needed
    container_folder_id = None
    if container_name:
        container_folder_id = get_or_create_subfolder(current_folder_id, container_name)
        if container_folder_id:
            current_folder_id = container_folder_id
    
    return folder_id, disk_link, current_folder_id


def download_file_from_chat(file_id):
    """Download file from chat and return file content and name."""
    file_info = b24_call("disk.file.get", {"id": file_id})
    if "error" in file_info:
        return None, None
    
    file_data = file_info.get("result", {}) if isinstance(file_info, dict) else {}
    file_name = file_data.get("NAME", f"file_{file_id}")
    download_url = file_data.get("DOWNLOAD_URL")
    
    if not download_url:
        return None, None
    
    try:
        r = requests.get(download_url, timeout=30)
        if r.status_code == 200:
            return r.content, file_name
    except Exception as e:
        print(f"[file_processor] Error downloading file {file_id}: {e}")
    
    return None, None


def upload_file_to_folder(folder_id, file_content, file_name):
    """Upload file to disk folder. Handles duplicate names."""
    encoded_content = base64.b64encode(file_content).decode("utf-8")
    
    from config import BITRIX_WEBHOOK
    url = f"{BITRIX_WEBHOOK}disk.folder.uploadfile"
    
    names_to_try = [file_name]
    name, ext = os.path.splitext(file_name)
    names_to_try.append(f"{name}_{int(time.time())}{ext}")
    
    for try_name in names_to_try:
        try:
            r = requests.post(url, json={
                "id": folder_id,
                "data": {"NAME": try_name},
                "fileContent": encoded_content
            }, timeout=30)
            j = r.json()
            if "result" in j:
                return True
            elif j.get("error") == "DISK_OBJ_22000":
                continue
            else:
                print(f"[file_processor] Upload error {try_name}: {j.get('error')}")
                return False
        except Exception as e:
            print(f"[file_processor] Upload exception {try_name}: {e}")
            return False
    
    return False


def find_deal_by_consignment_exact(consignment):
    """Find deal by consignment with exact match verification.
    
    Uses crm.deal.list for search, then crm.deal.get to verify exact match.
    Returns (deal_id, deal_consignment) or (None, None).
    """
    # Escape backslash for SQL LIKE
    escaped_value = consignment.replace("\\", "\\\\")
    
    deals = b24_call("crm.deal.list", {
        "FILTER[UF_CRM_1778645007478]": escaped_value,
        "SELECT[]": ["ID"]
    })
    deal_list = deals.get("result", []) if isinstance(deals, dict) else []
    
    if not deal_list:
        return None, None
    
    # Verify exact match with crm.deal.get (SELECT[] may omit custom fields)
    for deal_summary in deal_list:
        deal_id = deal_summary.get("ID")
        if not deal_id:
            continue
        
        full_deal = b24_call("crm.deal.get", {"ID": deal_id})
        deal_data = full_deal.get("result", {}) if isinstance(full_deal, dict) else {}
        actual_consignment = deal_data.get("UF_CRM_1778645007478", "")
        
        if actual_consignment == consignment:
            return deal_id, actual_consignment
    
    return None, None


def run(state):
    mod_state = get_module_state(state, "file_processor")
    processed_ids = mod_state.get("processed_messages", [])
    
    new_processed = list(processed_ids)
    processed_count = 0
    total_messages = 0
    
    chat_id = CHAT_WORKFLOW
    messages = get_chat_messages_with_files(chat_id)
    if not messages:
        return f"0 messages, 0 processed"
    
    total_messages = len(messages)
    
    for msg in messages:
        msg_id = msg["message_id"]
        if msg_id in processed_ids:
            continue
        
        text = msg.get("text", "")
        author_id = msg.get("author_id", "")
        
        # Only process messages with ! prefix
        if not text.strip().startswith("!"):
            new_processed.append(msg_id)
            continue
        
        text_without_bang = text.strip()[1:].strip()
        
        # Extract explicit department from text (hashtag or keyword)
        explicit_dept_id, explicit_dept_name = extract_department_from_text(text_without_bang)
        
        # Clean text for consignment extraction (remove hashtag)
        text_for_consignment = re.sub(r'#\w+\s*', '', text_without_bang).strip()
        consignment = extract_consignment_from_text(text_for_consignment)
        container = extract_container_from_text(text_for_consignment)
        user_name = get_user_name(author_id)
        
        if not consignment:
            reply = (
                f"❌ Коносамент не распознан в сообщении\n"
                f"Сотрудник: [USER={author_id}]{user_name}[/USER]"
            )
            log_to_chat(reply, chat_id=CHAT_WORKFLOW)
            new_processed.append(msg_id)
            continue
        
        # Find deal with EXACT match
        deal_id, deal_consignment = find_deal_by_consignment_exact(consignment)
        
        if not deal_id:
            reply = (
                f"❌ Сделка с коносаментом '{consignment}' не найдена\n"
                f"Сотрудник: [USER={author_id}]{user_name}[/USER]"
            )
            log_to_chat(reply, chat_id=CHAT_WORKFLOW)
            new_processed.append(msg_id)
            continue
        
        # Determine department folder: explicit hashtag/keyword first, then profile
        dept_folder_name = None
        if explicit_dept_id:
            dept_folder_name = explicit_dept_name
        else:
            user_depts = get_user_departments(author_id)
            for dept_id in user_depts:
                if dept_id in DEPT_FOLDER_NAMES:
                    dept_folder_name = DEPT_FOLDER_NAMES[dept_id]
                    break
        
        # Create folder hierarchy
        folder_id, folder_url, target_folder_id = get_or_create_deal_folder(
            deal_id, deal_consignment,
            dept_folder_name=dept_folder_name,
            container_name=container
        )
        
        uploaded_count = 0
        if target_folder_id:
            for file_id in msg.get("file_ids", []):
                file_content, file_name = download_file_from_chat(file_id)
                if file_content and file_name:
                    if upload_file_to_folder(target_folder_id, file_content, file_name):
                        uploaded_count += 1
        
        # Build notification with folder structure info
        location_parts = []
        if dept_folder_name:
            location_parts.append(dept_folder_name)
        if container:
            location_parts.append(f"контейнер {container}")
        
        location_str = " → ".join(location_parts) if location_parts else ""
        
        if uploaded_count > 0:
            msg_text = (
                f"✅ [URL=https://{PORTAL}/crm/deal/details/{deal_id}/]{consignment}[/URL]\n"
                f"Файл загружен ({uploaded_count} шт.)"
            )
            if location_str:
                msg_text += f"\nПапка: {location_str}"
            msg_text += (
                f"\n[URL={folder_url}]Ссылка на диск[/URL]\n"
                f"Сотрудник: [USER={author_id}]{user_name}[/USER]"
            )
            log_to_chat(msg_text, chat_id=CHAT_WORKFLOW)
            processed_count += 1
        else:
            msg_text = (
                f"❌ [URL=https://{PORTAL}/crm/deal/details/{deal_id}/]{consignment}[/URL]\n"
                f"Ошибка загрузки файлов"
            )
            if location_str:
                msg_text += f"\nПапка: {location_str}"
            msg_text += f"\nСотрудник: [USER={author_id}]{user_name}[/USER]"
            log_to_chat(msg_text, chat_id=CHAT_WORKFLOW)
        
        new_processed.append(msg_id)
    
    mod_state["processed_messages"] = new_processed[-1000:]
    
    return f"{total_messages} messages, {processed_count} processed"
