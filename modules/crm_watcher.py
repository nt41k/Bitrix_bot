"""
CRM Watcher Module - Track deal changes and write back to Google Sheets.
"""

from utils.logger import get_module_logger

logger = get_module_logger("crm_watcher")

import time
from datetime import datetime
from config import CATEGORY_ID_LOGISTICS, CATEGORY_ID_TEST, CRM_TO_GOOGLE, FIELD_LABELS, CRM_WATCHER_NEW_DEAL_DELAY, ENABLE_GOOGLE_WRITEBACK
from api_client import get_deals_by_category, get_deal_fields, log_to_chat
from modules.google_sync import writeback_to_google
from state import get_module_state
from utils.notifications import deal_link

# Fields to watch for changes (all fields that map to Google Sheets columns)
WATCHED_FIELDS = list(CRM_TO_GOOGLE.keys())


def parse_b24_datetime(dt_str):
    """Parse Bitrix24 datetime string to timestamp."""
    if not dt_str:
        return 0
    try:
        # Format: 2026-07-02T11:44:27+03:00
        dt = datetime.fromisoformat(dt_str)
        return dt.timestamp()
    except Exception:
        return 0


def run(state):
    mod_state = get_module_state(state, "crm_watcher")
    snapshot = mod_state.get("snapshot", {})
    now = time.time()
    
    # Get recent deals from both logistics and test pipelines
    all_deals = []
    for cat_id, cat_name in [(CATEGORY_ID_LOGISTICS, "logistics"), (CATEGORY_ID_TEST, "test")]:
        result = get_deals_by_category(cat_id, limit=50)
        if "error" in result:
            print(f"[crm_watcher] Warning: Failed to fetch {cat_name} deals: {result['error']}")
            continue
        deals = result.get("result", [])
        print(f"[crm_watcher] Fetched {len(deals)} deals from {cat_name} (category {cat_id})")
        all_deals.extend(deals)
    
    deals = all_deals
    new_snapshot = {}
    notifications = []
    writeback_updates = []  # [{sheet, row, column, value}, ...]
    
    for deal in deals:
        deal_id = str(deal.get("ID"))
        if not deal_id:
            continue
        
        # Get full deal data
        full = get_deal_fields(deal_id)
        if "error" in full:
            continue
        
        deal_data = full.get("result", {})
        
        # Build current state with only watched fields
        current = {}
        for field in WATCHED_FIELDS:
            # Try both UF_CRM_ and ufCrm_ formats
            value = deal_data.get(field)
            if value is None and field.startswith("UF_CRM_"):
                value = deal_data.get("ufCrm_" + field[7:])
            current[field] = value
        
        new_snapshot[deal_id] = current
        
        # Check deal age — skip very new deals to avoid race with google_sync
        created_time = parse_b24_datetime(deal_data.get("DATE_CREATE", ""))
        deal_age = now - created_time
        is_new_deal = deal_age < CRM_WATCHER_NEW_DEAL_DELAY
        
        # Check for changes (skip if no previous snapshot for this deal)
        if deal_id in snapshot and not is_new_deal:
            changed_fields = {}
            for field in WATCHED_FIELDS:
                old_val = snapshot[deal_id].get(field)
                new_val = current.get(field)
                # Compare as strings to handle type differences and None transitions
                if str(new_val or "") != str(old_val or ""):
                    label = FIELD_LABELS.get(field, field)
                    changed_fields[label] = (old_val, new_val)
                    
                    # Prepare writeback to Google Sheets (only if enabled)
                    if ENABLE_GOOGLE_WRITEBACK:
                        google_col = CRM_TO_GOOGLE.get(field)
                        if google_col:
                            consignment = deal_data.get("UF_CRM_1778645007478") or deal_data.get("ufCrm_1778645007478", "")
                            if consignment:
                                # Use conosament-based writeback (Apps Script finds all matching rows)
                                writeback_updates.append({
                                    "sheetName": "TESTLIST",  # Only TESTLIST for now
                                    "conosament": consignment,
                                    "changes": {google_col: str(new_val)}
                                })
            
            if changed_fields:
                title = deal_data.get("TITLE", f"Сделка #{deal_id}")
                folder_id = deal_data.get("UF_CRM_1779917649707") or deal_data.get("ufCrm_1779917649707")
                msg_lines = [f"✅ {deal_link(deal_id, title)}"]
                for label, (old, new) in changed_fields.items():
                    msg_lines.append(f"  {label}: {old or '(пусто)'} → {new}")
                if folder_id:
                    msg_lines.append(f"  📁 [URL=https://cargonovo.bitrix24.ru/docs/path/{folder_id}/]Папка[/URL]")
                notifications.append("\n".join(msg_lines))
        else:
            # First time seeing this deal, or deal is too new — just add to snapshot, no writeback
            if is_new_deal:
                print(f"[crm_watcher] Skipping new deal {deal_id} (age: {deal_age:.0f}s < {CRM_WATCHER_NEW_DEAL_DELAY}s)")
            pass
    
    # Deduplicate writeback updates (same sheet+conosament+column = one update)
    seen = set()
    deduped_updates = []
    for u in writeback_updates:
        key = (u.get("sheetName"), u.get("conosament"), tuple(sorted(u.get("changes", {}).keys())))
        if key not in seen:
            seen.add(key)
            deduped_updates.append(u)
    writeback_updates = deduped_updates
    
    # Send writeback to Google Sheets (only if enabled)
    if writeback_updates and ENABLE_GOOGLE_WRITEBACK:
        print(f"[crm_watcher] Writeback {len(writeback_updates)} updates to Google Sheets...")
        try:
            wb_result = writeback_to_google(writeback_updates)
            print(f"[crm_watcher] Writeback result: {wb_result}")
        except Exception as e:
            print(f"[crm_watcher] Writeback error: {e}")
    elif writeback_updates:
        print(f"[crm_watcher] Writeback DISABLED: {len(writeback_updates)} updates would be sent (ENABLE_GOOGLE_WRITEBACK=False)")
    
    # Send notifications — DISABLED per user request
    # for msg in notifications:
    #     try:
    #         log_to_chat(msg, chat_id=CHAT_WORKFLOW)
    #     except Exception:
    #         pass
    
    # Update snapshot
    mod_state["snapshot"] = new_snapshot
    
    return f"{len(deals)} deals checked, {len(notifications)} changes, {len(writeback_updates)} writebacks"
