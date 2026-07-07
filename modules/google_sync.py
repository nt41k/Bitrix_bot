"""
Google Sheets <-> Bitrix24 Sync Module
"""

from utils.logger import get_module_logger

logger = get_module_logger("google_sync")

import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from config import (
    APPS_SCRIPT_ENDPOINT, SPREADSHEET_ID, GOOGLE_TO_CRM,
    FIELD_LABELS, CHAT_REPORTS, GOOGLE_SHEETS, DEAL_FOLDER_PARENT_ID,
    SHEET_TO_CATEGORY, CATEGORY_ID_LOGISTICS
)
from api_client import (
    b24_call, b24_post, update_deal, search_deals_by_field,
    add_timeline_comment, log_to_chat,
    vibe_api_call, vibe_batch_call, batch_update_deals, batch_create_deals
)
from state import get_module_state


# Fixed headers for Google Sheets (second row - yellow header)
# These match the actual column names in the sheet
GOOGLE_HEADERS = [
    "SHID",
    "ОТВЕТСТВЕННЫЙ ЛОГИСТ",
    "КЛИЕНТ",
    "НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)",
    "ДИСК ССЫЛКА",
    "ДАТА",
    "ПРИБЫТИЕ",
    "СУДНО",
    "ПОРТ/СВХ",
    "ЛИНИЯ",
    "НОМЕР ТРАНСПОРТНОГО СРЕДСТВА (КОНТЕЙНЕР)",
    "ВЕС, МЕСТА",
    "Тип КОНТ",
    "НАИМЕНОВАНИЕ ТОВАРА",
    "КОД РЕЛИЗ ",
    "КОММЕНТАРИЙ Л",
    "№ ДТ",
    "ИТС",
    "ДЕКЛАРАНТ ",
    "КОММЕНТАРИЙ ДЛЯ ДЕКЛАРАНТА",
    "ЗАЯВКА/ПИСЬМО",
    "В РАБОТЕ (ОЖИДАЕМ АКФК) / АКТ",
    "ПОЛУЧИЛИ ЗАКЛЮЧЕНИЕ",
    "ВЫПУСК АКФК / АКТ",
    "ЭКСПДЕДИТОР",
    "КОММЕНТАРИЙ ДЛЯ ЭКСПЕДИТОРА",
    "ВЫВОЗ",
    "СДАЧА",
    "ПЕРЕВОЗЧИК",
    "ВХОДЯЩАЯ СТОИМОСТЬ",
    "ТРАНСПОРТ",
    "КОММЕНТАРИЙ ДЛЯ ТРАНСПОРТА",
    "ВЫГРУЖЕН",
    "ПОГРУЖЕН",
    "СКЛАД",
    "КОММЕНТАРИЙ ДЛЯ СКЛАДА",
]


def fetch_google_data(sheet="Новороссийск", timeout=30):
    """Fetch data from Google Apps Script with configurable timeout."""
    try:
        params = {
            'action': 'read',
            'sheetName': sheet,
            '_': int(time.time() * 1000)  # Cache-busting
        }
        resp = requests.get(
            APPS_SCRIPT_ENDPOINT,
            params=params,
            timeout=timeout,
            allow_redirects=True
        )
        
        # Check for HTML error pages
        ct = resp.headers.get('Content-Type', '')
        if 'text/html' in ct:
            import re
            m = re.search(r'<div[^>]*>([^<]+)</div>', resp.text)
            error_msg = m.group(1) if m else 'Unknown HTML error'
            raise Exception(f"Apps Script HTML error: {error_msg}")
        
        data = resp.json()
        
        if not data.get('success'):
            raise Exception(f"Apps Script error: {data.get('error', data)}")
        
        # Use fixed headers instead of potentially corrupted ones from Apps Script
        headers = GOOGLE_HEADERS
        raw_rows = data.get('rows', [])
        
        # Build list of lists: first row is headers, rest are data
        result = [headers]
        for raw_row in raw_rows:
            if isinstance(raw_row, dict):
                row = [raw_row.get(h, "") for h in headers]
            else:
                row = raw_row
            result.append(row)
        
        return {"data": result, "sheet": sheet}
    except Exception as e:
        raise Exception(f"Google fetch failed for '{sheet}': {e}")


def fetch_all_sheets_parallel(sheets, timeout=30, max_workers=6):
    """Fetch all Google Sheets in parallel using ThreadPoolExecutor.
    
    Returns: list of (sheet_name, data_dict or None, error_or_None)
    """
    results = []
    
    def fetch_one(sheet):
        try:
            data = fetch_google_data(sheet, timeout=timeout)
            return (sheet, data, None)
        except Exception as e:
            return (sheet, None, str(e))
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, sheet): sheet for sheet in sheets}
        for future in as_completed(futures):
            sheet, data, error = future.result()
            if error:
                print(f"[google_sync] Parallel fetch error '{sheet}': {error}")
            results.append((sheet, data, error))
    
    return results


def validate_consignment(consignment):
    """Ensure consignment is a valid identifier, not a URL or path."""
    if not consignment:
        return False, "empty"
    c = str(consignment).strip()
    if c.startswith(("http://", "https://")):
        return False, f"URL detected: {c[:50]}..."
    if "/" in c and "." in c:
        return False, f"suspicious path: {c[:50]}..."
    return True, None


def is_valid_container(name):
    """Check if value looks like a container number (4 letters + 7 digits)."""
    if not name:
        return False
    name = str(name).strip().upper()
    # Standard container: 4 letters + 7 digits (e.g., TCKU1925813)
    import re
    return bool(re.match(r'^[A-Z]{4}\d{7}$', name))


def format_date(value):
    """Convert various date formats (ISO, yyyy-mm-dd, timestamp) to dd.mm.yyyy."""
    if not value:
        return value
    if isinstance(value, str):
        value = value.strip()
        # Already in target format
        if len(value) == 10 and value[2] == "." and value[5] == ".":
            return value
    # ISO format with time: 2026-06-28T21:00:00.000Z
    try:
        if isinstance(value, str) and "T" in value:
            from datetime import datetime
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
    except Exception:
        pass
    # yyyy-mm-dd format
    try:
        if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
            from datetime import datetime
            dt = datetime.strptime(value[:10], "%Y-%m-%d")
            return dt.strftime("%d.%m.%Y")
    except Exception:
        pass
    # Numeric timestamp (milliseconds or seconds)
    try:
        if isinstance(value, (int, float)):
            from datetime import datetime
            if value > 1e10:
                value = value / 1000
            dt = datetime.fromtimestamp(value)
            return dt.strftime("%d.%m.%Y")
    except Exception:
        pass
    return value


def get_or_create_deal_folder(deal_id, consignment):
    """Get or create disk folder for deal inside TEMP NEW. Returns folder ID and detail URL."""
    # First check if deal already has folder
    deals = b24_call("crm.deal.get", {"ID": deal_id})
    deal = deals.get("result", {}) if isinstance(deals, dict) else {}
    
    folder_id = deal.get("UF_CRM_1779917649707")
    disk_link = deal.get("UF_CRM_1780368582410")
    
    if folder_id and disk_link:
        return folder_id, disk_link
    
    # Need to create folder inside TEMP NEW (DEAL_FOLDER_PARENT_ID)
    parent_folder_id = DEAL_FOLDER_PARENT_ID
    
    # Sanitize consignment for folder name (replace / with -)
    safe_name = str(consignment).replace("/", "-")
    
    # Create folder with consignment name
    folder_result = b24_call("disk.folder.addsubfolder", {
        "id": parent_folder_id,
        "data[NAME]": safe_name,
        "data[CREATED_BY]": "376"
    })
    
    if "error" in folder_result:
        # Folder might already exist, try to find it
        children = b24_call("disk.folder.getchildren", {"id": parent_folder_id})
        for child in children.get("result", []) if isinstance(children, dict) else []:
            if child.get("NAME") == safe_name:
                folder_id = child.get("ID")
                detail_url = child.get("DETAIL_URL")
                # Update deal with folder info
                b24_post("crm.deal.update", {
                    "ID": deal_id,
                    "fields": {
                        "UF_CRM_1779917649707": folder_id,
                        "UF_CRM_1780368582410": detail_url
                    }
                })
                return folder_id, detail_url
        return None, None
    
    new_folder = folder_result.get("result", {})
    folder_id = new_folder.get("ID")
    detail_url = new_folder.get("DETAIL_URL")
    
    # Update deal with folder info
    if folder_id and detail_url:
        b24_post("crm.deal.update", {
            "ID": deal_id,
            "fields": {
                "UF_CRM_1779917649707": folder_id,
                "UF_CRM_1780368582410": detail_url
            }
        })
    
    return folder_id, detail_url


def writeback_to_google(updates):
    """Write CRM data back to Google Sheets.
    
    Supports two modes:
    1. Conosament-based (Scenario 3): {"conosament": "XXX", "changes": {...}, "sheetName": "sheet"}
       - Apps Script finds ALL rows with this consignment and updates them
    2. Row-based (Scenario 1): {"rowNumber": N, "changes": {...}, "sheetName": "sheet"}
       - Apps Script updates specific row(s)
    """
    if not updates:
        return {"updated": 0}
    
    # Separate conosament-based and row-based updates
    conosament_updates = []  # [{"conosament": "XXX", "changes": {...}, "sheetName": "sheet"}, ...]
    row_updates = []         # [{"rowNumber": N, "changes": {...}, "sheetName": "sheet"}, ...]
    container_updates = []   # [{"conosament": "XXX", "container": "YYY", "changes": {...}}, ...]
    
    for u in updates:
        if "conosament" in u and "container" in u:
            container_updates.append(u)
        elif "conosament" in u:
            conosament_updates.append(u)
        elif "rowNumber" in u:
            row_updates.append(u)
    
    total_success = 0
    total_errors = []
    
    # ── Mode 0: Container-based (exact match: consignment + container) ──
    for u in container_updates:
        sheet_name = u.get("sheetName", "Новороссийск")
        consignment = u["conosament"]
        container = u["container"]
        changes = u.get("changes", {})
        
        valid_changes = {}
        for col_name, value in changes.items():
            if col_name in GOOGLE_HEADERS:
                valid_changes[col_name] = value
            else:
                total_errors.append(f"Unknown column '{col_name}' in sheet '{sheet_name}'")
        
        if not valid_changes:
            continue
        
        payload = {
            "spreadsheetId": SPREADSHEET_ID,
            "sheetName": sheet_name,
            "conosament": consignment,
            "container": container,
            "changes": valid_changes
        }
        
        try:
            resp = requests.post(
                APPS_SCRIPT_ENDPOINT,
                json=payload,
                timeout=30,
                allow_redirects=True
            )
            
            ct = resp.headers.get('Content-Type', '')
            if 'text/html' in ct:
                import re
                m = re.search(r'<div[^>]*>([^<]+)</div>', resp.text)
                error_msg = m.group(1) if m else 'Unknown HTML error'
                total_errors.append(f"Sheet '{sheet_name}': HTML error: {error_msg}")
                continue
            
            result = resp.json()
            if result.get("success"):
                total_success += result.get("updated", 0)
                if result.get("errors"):
                    total_errors.extend([f"Sheet '{sheet_name}': {e}" for e in result["errors"]])
            else:
                total_errors.append(f"Sheet '{sheet_name}': {result.get('error', str(result))}")
                
        except Exception as e:
            total_errors.append(f"Sheet '{sheet_name}': {str(e)}")
    
    # ── Mode 1: Conosament-based (one request per consignment per sheet) ──
    # Group by (sheetName, conosament) and merge changes
    conosament_by_key = {}
    for u in conosament_updates:
        key = (u.get("sheetName", "Новороссийск"), u["conosament"])
        if key not in conosament_by_key:
            conosament_by_key[key] = {}
        conosament_by_key[key].update(u.get("changes", {}))
    
    for (sheet_name, consignment), changes in conosament_by_key.items():
        # Validate column names
        valid_changes = {}
        for col_name, value in changes.items():
            if col_name in GOOGLE_HEADERS:
                valid_changes[col_name] = value
            else:
                total_errors.append(f"Unknown column '{col_name}' in sheet '{sheet_name}'")
        
        if not valid_changes:
            continue
        
        payload = {
            "spreadsheetId": SPREADSHEET_ID,
            "sheetName": sheet_name,
            "conosament": consignment,
            "changes": valid_changes
        }
        
        try:
            resp = requests.post(
                APPS_SCRIPT_ENDPOINT,
                json=payload,
                timeout=30,
                allow_redirects=True
            )
            
            ct = resp.headers.get('Content-Type', '')
            if 'text/html' in ct:
                import re
                m = re.search(r'<div[^>]*>([^<]+)</div>', resp.text)
                error_msg = m.group(1) if m else 'Unknown HTML error'
                total_errors.append(f"Sheet '{sheet_name}': HTML error: {error_msg}")
                continue
            
            result = resp.json()
            if result.get("success"):
                total_success += result.get("updated", 0)
                if result.get("errors"):
                    total_errors.extend([f"Sheet '{sheet_name}': {e}" for e in result["errors"]])
            else:
                total_errors.append(f"Sheet '{sheet_name}': {result.get('error', str(result))}")
                
        except Exception as e:
            total_errors.append(f"Sheet '{sheet_name}': {str(e)}")
    
    # ── Mode 2: Row-based (batch updates array) ──
    if row_updates:
        by_sheet = {}
        for u in row_updates:
            sheet = u.get("sheetName", "Новороссийск")
            if sheet not in by_sheet:
                by_sheet[sheet] = []
            by_sheet[sheet].append(u)
        
        for sheet_name, sheet_updates in by_sheet.items():
            batch_updates = []
            for u in sheet_updates:
                changes = u.get("changes", {})
                valid_changes = {}
                for col_name, value in changes.items():
                    if col_name in GOOGLE_HEADERS:
                        valid_changes[col_name] = value
                    else:
                        total_errors.append(f"Unknown column '{col_name}' in sheet '{sheet_name}'")
                
                if valid_changes:
                    batch_updates.append({
                        "rowNumber": u["rowNumber"],
                        "changes": valid_changes
                    })
            
            if not batch_updates:
                continue
            
            payload = {
                "spreadsheetId": SPREADSHEET_ID,
                "sheetName": sheet_name,
                "updates": batch_updates
            }
            
            try:
                resp = requests.post(
                    APPS_SCRIPT_ENDPOINT,
                    json=payload,
                    timeout=30,
                    allow_redirects=True
                )
                
                ct = resp.headers.get('Content-Type', '')
                if 'text/html' in ct:
                    import re
                    m = re.search(r'<div[^>]*>([^<]+)</div>', resp.text)
                    error_msg = m.group(1) if m else 'Unknown HTML error'
                    total_errors.append(f"Sheet '{sheet_name}': HTML error: {error_msg}")
                    continue
                
                result = resp.json()
                if result.get("success"):
                    total_success += result.get("updated", 0)
                    if result.get("errors"):
                        total_errors.extend([f"Sheet '{sheet_name}': {e}" for e in result["errors"]])
                else:
                    total_errors.append(f"Sheet '{sheet_name}': {result.get('error', str(result))}")
                    
            except Exception as e:
                total_errors.append(f"Sheet '{sheet_name}': {str(e)}")
    
    return {
        "success": total_success > 0,
        "updated": total_success,
        "errors": total_errors if total_errors else None
    }


def find_all_rows_in_google_sheets(consignment, state=None):
    """Find all rows for a consignment across all Google Sheets.
    
    Self-sufficient: queries Google Sheets directly instead of relying on
    google_sync state to avoid cross-module dependency issues.
    
    Returns: [{"sheetName": str, "rowNumber": int}, ...]
    rowNumber is RELATIVE (1 = first data row) — Apps Script adds header_offset.
    """
    all_rows = []
    
    # Try cache first if state is available
    if state is not None:
        mod_state = get_module_state(state, "google_sync")
        cached_data = mod_state.get("sheet_data_cache", {})
        
        for sheet_name, data in cached_data.items():
            headers = data.get("headers", [])
            rows = data.get("rows", [])
            if not rows or not headers:
                continue
            
            try:
                identifier_idx = headers.index("НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)")
            except ValueError:
                continue
            
            for row_idx, row in enumerate(rows, start=1):
                if len(row) > identifier_idx and row[identifier_idx] == consignment:
                    # Return RELATIVE rowNumber (1 = first data row)
                    all_rows.append({"sheetName": sheet_name, "rowNumber": row_idx})
        
        if all_rows:
            return all_rows
    
    # Fallback: query each sheet via API
    for sheet_name in GOOGLE_SHEETS:
        try:
            data = fetch_google_data(sheet_name)
            rows = data.get("data", [])
            if not rows or len(rows) < 2:
                continue
            
            headers = rows[0]
            try:
                identifier_idx = headers.index("НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)")
            except ValueError:
                continue
            
            for row_idx, row in enumerate(rows[1:], start=1):
                if len(row) > identifier_idx and row[identifier_idx] == consignment:
                    # Return RELATIVE rowNumber (1 = first data row)
                    all_rows.append({"sheetName": sheet_name, "rowNumber": row_idx})
        except Exception as e:
            print(f"[find_all_rows] Error querying {sheet_name}: {e}")
            continue
    
    return all_rows


def run(state):
    mod_state = get_module_state(state, "google_sync")
    total_updates = 0
    total_creates = 0
    total_errors = 0

    # ── 1. Параллельный fetch всех листов ──
    all_sheets_data = []   # [(sheet_name, headers, [(row_idx, row, consignment), ...]), ...]
    all_consignments = set()

    sheet_results = fetch_all_sheets_parallel(GOOGLE_SHEETS, timeout=30, max_workers=6)

    # Очищаем row_map перед заполнением, чтобы избежать дубликатов
    mod_state["consignment_row_map"] = {}

    for sheet_name, data, error in sheet_results:
        if error:
            total_errors += 1
            continue
        rows = data.get("data", [])
        if not rows or len(rows) < 2:
            continue

        headers = rows[0]
        identifier_idx = headers.index("НОМЕР ТРАНСПОРТНОГО ДОКУМЕНТА (КОНОСАМЕНТ)")

        sheet_rows = []
        for row_idx, row in enumerate(rows[1:], start=1):
            if len(row) <= identifier_idx:
                continue
            consignment = row[identifier_idx]
            if not consignment:
                continue
            is_valid, error = validate_consignment(consignment)
            if not is_valid:
                print(f"[google_sync] Skip invalid consignment row {row_idx}: {error}")
                continue
            all_consignments.add(consignment)
            sheet_rows.append((row_idx, row, consignment))

        all_sheets_data.append((sheet_name, headers, sheet_rows))

        # Кэш для других модулей
        if "sheet_data_cache" not in mod_state:
            mod_state["sheet_data_cache"] = {}
        mod_state["sheet_data_cache"][sheet_name] = {
            "headers": headers,
            "rows": [r[1] for r in sheet_rows]
        }

        # Сохраняем номера строк для writeback (CRM → Google Sheets)
        # Используем RELATIVE row numbers (1 = первая строка данных) — Apps Script ожидает это
        for row_idx, row, consignment in sheet_rows:
            mod_state["consignment_row_map"].setdefault(consignment, []).append({
                "sheet": sheet_name,
                "row": row_idx  # relative: 1 = first data row
            })

    if not all_consignments:
        return "0 updates, 0 creates, 0 errors"

    # ── 2. ОДИН поиск всех существующих сделок ──
    consignment_list = list(all_consignments)
    existing_deals = {}   # consignment -> deal_id

    print(f"[google_sync] Searching {len(consignment_list)} consignments...")
    try:
        search_result = vibe_api_call("/deals/search", "POST", {
            "filter": {"ufCrm_1778645007478": consignment_list},
            "select": ["id", "ufCrm_1778645007478", "categoryId"],
            "limit": 5000
        })
        if search_result.get("success") and isinstance(search_result.get("data"), list):
            for deal in search_result["data"]:
                cons = deal.get("ufCrm_1778645007478")
                cat = deal.get("categoryId")
                if cons:
                    # Store with category info for filtering
                    existing_deals[cons] = {"id": deal["id"], "categoryId": cat}
        print(f"[google_sync] Found {len(existing_deals)} existing deals")
    except Exception as e:
        print(f"[google_sync] Bulk search failed: {e}")

    # Fallback: если bulk search не сработал (пустой результат при непустых коносаментах),
    # используем индивидуальный поиск для защиты от дубликатов
    if not existing_deals and consignment_list:
        print(f"[google_sync] WARNING: Bulk search returned 0 deals for {len(consignment_list)} consignments. Running fallback search...")
        for cons in consignment_list:
            try:
                deals = search_deals_by_field("UF_CRM_1778645007478", cons)
                deal_list = deals.get("result", []) if isinstance(deals, dict) else []
                if deal_list:
                    # Get categoryId from deal data
                    deal_id = deal_list[0]["ID"]
                    deal_detail = b24_call("crm.deal.get", {"ID": deal_id})
                    cat_id = None
                    if isinstance(deal_detail, dict):
                        cat_id = deal_detail.get("result", {}).get("CATEGORY_ID")
                    existing_deals[cons] = {"id": deal_id, "categoryId": cat_id}
            except Exception as e:
                print(f"[google_sync] Fallback search error for {cons}: {e}")
        print(f"[google_sync] Fallback found {len(existing_deals)} deals")

    # ── 3. Batch-загрузка полных данных сделок (для сравнения) ──
    print(f"[google_sync] Loading deal data for {len(existing_deals)} deals...")
    deal_data_cache = {}
    deal_ids = [d["id"] for d in existing_deals.values()]
    for i in range(0, len(deal_ids), 50):
        batch_ids = deal_ids[i:i + 50]
        calls = [
            {"id": str(did), "entity": "deals", "action": "get", "entityId": did}
            for did in batch_ids
        ]
        batch_result = vibe_batch_call(calls)
        if batch_result.get("success") and isinstance(batch_result.get("data"), dict):
            for call_id, result in batch_result["data"].get("results", {}).items():
                if isinstance(result, dict) and "id" in result:
                    deal_data_cache[result["id"]] = result
    print(f"[google_sync] Loaded {len(deal_data_cache)} deal details")

    # ── 4. Собираем batch-операции ──
    print(f"[google_sync] Building batch operations...")
    update_batch = []      # [{id: N, ufCrm_...: "value"}, ...]
    create_batch = []      # [{title: "...", ufCrm_...: "value"}, ...]
    timeline_calls = []    # для POST /v1/batch
    new_deal_meta = []     # [(consignment, sheet_name, row_idx), ...]
    
    # Словарь для сбора всех контейнеров по коносаменту (для JSON)
    consignment_containers = {}  # consignment -> {container_name: {}}

    for sheet_name, headers, sheet_rows in all_sheets_data:
        print(f"[google_sync] Processing sheet '{sheet_name}': {len(sheet_rows)} rows")
        expected_category = SHEET_TO_CATEGORY.get(sheet_name, CATEGORY_ID_LOGISTICS)
        
        for row_idx, row, consignment in sheet_rows:
            # Собираем контейнеры для JSON
            container_col = "НОМЕР ТРАНСПОРТНОГО СРЕДСТВА (КОНТЕЙНЕР)"
            if container_col in headers:
                container_idx = headers.index(container_col)
                if container_idx < len(row) and row[container_idx]:
                    container_name = str(row[container_idx]).strip()
                    if container_name and is_valid_container(container_name):
                        if consignment not in consignment_containers:
                            consignment_containers[consignment] = {}
                        if container_name not in consignment_containers[consignment]:
                            consignment_containers[consignment][container_name] = {}
            
            # Check if deal exists with matching category
            deal_id = None
            deal_category = None
            if consignment in existing_deals:
                deal_info = existing_deals[consignment]
                deal_id = deal_info["id"]
                deal_category = deal_info.get("categoryId")
                
                if deal_category != expected_category:
                    print(f"[google_sync] Category mismatch for {consignment} in {sheet_name}: expected {expected_category}, found {deal_category}. Will create new deal.")
                    deal_id = None  # Force creation
            
            if deal_id:
                # UPDATE existing deal
                deal_data = deal_data_cache.get(deal_id, {})

                changed = {}
                for g_col, crm_field in GOOGLE_TO_CRM.items():
                    if g_col not in headers:
                        continue
                    idx = headers.index(g_col)
                    if idx >= len(row) or not row[idx]:
                        continue
                    new_val = row[idx]
                    # Convert date format for "ДАТА" column
                    if g_col == "ДАТА":
                        new_val = format_date(new_val)
                    vibe_field = crm_field.replace("UF_CRM_", "ufCrm_")
                    old_val = deal_data.get(vibe_field)
                    if str(new_val) != str(old_val or ""):
                        changed[vibe_field] = new_val

                if changed:
                    item = {"id": deal_id}
                    item.update(changed)
                    update_batch.append(item)

                    labels = ", ".join(
                        f"{FIELD_LABELS.get(k.replace('ufCrm_', 'UF_CRM_'), k)}={v}"
                        for k, v in changed.items()
                    )
                    timeline_calls.append({
                        "id": f"tl-{deal_id}",
                        "entity": "timelines",
                        "action": "create",
                        "params": {
                            "entityType": "deal",
                            "entityId": deal_id,
                            "title": "Автоматизация",
                            "text": f"Обновлено из Google Sheets ({sheet_name}): {labels}"
                        }
                    })
            else:
                # ЗАЩИТА: перед созданием — проверить ещё раз, что сделки нет
                # (bulk search мог не сработать)
                try:
                    deals = search_deals_by_field("UF_CRM_1778645007478", consignment)
                    deal_list = deals.get("result", []) if isinstance(deals, dict) else []
                    if deal_list:
                        # Сделка уже есть — пропускаем создание, логируем
                        print(f"[google_sync] DUPLICATE PREVENTED: {consignment} already exists as deal {deal_list[0]['ID']}")
                        total_errors += 1
                        continue
                except Exception as e:
                    print(f"[google_sync] Pre-create check failed for {consignment}: {e}")
                    total_errors += 1
                    continue

                item = {
                    "title": f"Авто: {consignment}",
                    "categoryId": SHEET_TO_CATEGORY.get(sheet_name, CATEGORY_ID_LOGISTICS),
                    "ufCrm_1778645007478": consignment,
                }
                for g_col, crm_field in GOOGLE_TO_CRM.items():
                    if g_col not in headers:
                        continue
                    idx = headers.index(g_col)
                    if idx < len(row) and row[idx]:
                        vibe_field = crm_field.replace("UF_CRM_", "ufCrm_")
                        val = row[idx]
                        if g_col == "ДАТА":
                            val = format_date(val)
                        item[vibe_field] = val
                create_batch.append(item)
                new_deal_meta.append((consignment, sheet_name, row_idx))

    # ── 4.5. JSON-обновление контейнеров ──
    # Собираем все контейнеры в JSON для каждого коносамента
    update_by_id = {item["id"]: item for item in update_batch}
    for consignment, containers in consignment_containers.items():
        if consignment in existing_deals:
            deal_id = existing_deals[consignment]["id"]
            deal_data = deal_data_cache.get(deal_id, {})
            current_json_str = deal_data.get("ufCrm_1781078096027") or deal_data.get("UF_CRM_1781078096027") or ""
            
            current_containers = {}
            if current_json_str:
                try:
                    if isinstance(current_json_str, str):
                        current_containers = json.loads(current_json_str)
                    elif isinstance(current_json_str, dict):
                        current_containers = current_json_str
                except json.JSONDecodeError:
                    # Old single-value format — convert to JSON if valid container
                    old_val = str(current_json_str).strip()
                    if is_valid_container(old_val):
                        current_containers = {old_val: {}}
            
            # Filter out invalid containers from current data
            original_containers = dict(current_containers)
            current_containers = {k: v for k, v in current_containers.items() if is_valid_container(k)}
            
            merged = dict(current_containers)
            merged.update(containers)
            
            if merged != original_containers:
                new_json = json.dumps(merged, ensure_ascii=False)
                if deal_id in update_by_id:
                    update_by_id[deal_id]["ufCrm_1781078096027"] = new_json
                else:
                    update_by_id[deal_id] = {"id": deal_id, "ufCrm_1781078096027": new_json}
                print(f"[google_sync] Container JSON for {consignment}: {list(merged.keys())}")
    
    update_batch = list(update_by_id.values())
    
    # Add container JSON to new deals
    for item in create_batch:
        cons = item.get("ufCrm_1778645007478", "")
        if cons in consignment_containers:
            item["ufCrm_1781078096027"] = json.dumps(consignment_containers[cons], ensure_ascii=False)

    # ── 5. Batch-обновление (по 500 за раз) ──
    if update_batch:
        for i in range(0, len(update_batch), 500):
            chunk = update_batch[i:i + 500]
            result = batch_update_deals(chunk)
            if result.get("success") and isinstance(result.get("data"), dict):
                results = result["data"].get("results", {})
                ok = sum(1 for x in results.values() if x.get("item", {}).get("id") or x.get("id"))
                total_updates += ok
                failed = len(results) - ok
                total_errors += failed
                if failed:
                    print(f"[google_sync] Batch update: {ok} ok, {failed} failed")
                    for call_id, res in results.items():
                        if not (res.get("item", {}).get("id") or res.get("id")):
                            print(f"[google_sync] Failed update {call_id}: {res.get('error')} - {res.get('message', '')}")
            else:
                total_errors += len(chunk)
                print(f"[google_sync] Batch update error: {result}")

    # ── 6. Batch-создание (по 500 за раз) ──
    created_deals = []   # [(deal_id, consignment, sheet_name, row_idx), ...]
    if create_batch:
        for i in range(0, len(create_batch), 500):
            chunk = create_batch[i:i + 500]
            result = batch_create_deals(chunk)
            if result.get("success") and isinstance(result.get("data"), dict):
                results = result["data"].get("results", {})
                ok = 0
                for j, (call_id, item_res) in enumerate(results.items()):
                    if item_res.get("item", {}).get("id"):
                        ok += 1
                        meta = new_deal_meta[i + j]
                        created_deals.append((item_res["item"]["id"], *meta))
                    else:
                        total_errors += 1
                        print(f"[google_sync] Create failed: {item_res.get('error')} - {item_res.get('message', '')}")
                total_creates += ok
            else:
                total_errors += len(chunk)
                print(f"[google_sync] Batch create error: {result}")

    # ── 7. Batch timeline-комментарии (по 50 за раз) ──
    if timeline_calls:
        for i in range(0, len(timeline_calls), 50):
            chunk = timeline_calls[i:i + 50]
            result = vibe_batch_call(chunk)
            if not result.get("success"):
                print(f"[google_sync] Batch timeline error: {result}")

    # ── 8. Папки на Диске для новых сделок (последовательно, B24 REST) ──
    for deal_id, consignment, sheet_name, row_idx in created_deals:
        try:
            folder_id, folder_url = get_or_create_deal_folder(deal_id, consignment)
            if folder_url:
                # NOTE: Writeback to Google Sheets is handled by crm_watcher
                # when it detects UF_CRM_1780368582410 change.
                # Do NOT writeback here to avoid duplicate writes and log noise.
                add_timeline_comment(deal_id, f"Создана папка на Диске: {folder_url}")
        except Exception as e:
            total_errors += 1
            print(f"[google_sync] Folder error deal {deal_id}: {e}")

    # ── 9. Проверка существующих сделок без папки ──
    missing_folder_count = 0
    for consignment, deal_info in existing_deals.items():
        deal_id = deal_info["id"]
        deal_data = deal_data_cache.get(deal_id, {})
        folder_id = deal_data.get("ufCrm_1779917649707") or deal_data.get("UF_CRM_1779917649707")
        if not folder_id:
            try:
                folder_id, folder_url = get_or_create_deal_folder(deal_id, consignment)
                if folder_url:
                    missing_folder_count += 1
                    # NOTE: Writeback to Google Sheets is handled by crm_watcher
                    # when it detects UF_CRM_1780368582410 change.
                    # Do NOT writeback here to avoid duplicate writes and log noise.
                    add_timeline_comment(deal_id, f"Создана папка на Диске: {folder_url}")
            except Exception as e:
                total_errors += 1
                print(f"[google_sync] Folder fix error deal {deal_id} ({consignment}): {e}")
    
    if missing_folder_count:
        print(f"[google_sync] Fixed {missing_folder_count} deals with missing folders")

    # Debug: check consignment_row_map
    row_map = mod_state.get("consignment_row_map", {})
    print(f"[google_sync] consignment_row_map: {len(row_map)} entries")
    for k, v in list(row_map.items())[:3]:
        print(f"  {k}: {v}")

    return f"{total_updates} updates, {total_creates} creates, {total_errors} errors"
