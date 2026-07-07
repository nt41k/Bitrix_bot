"""
Unified API client for Bitrix24 (VibeCode + REST webhook).
"""

import json
import urllib.parse
import requests
from datetime import datetime
from config import VIBE_KEY, VIBE_BASE_URL, BITRIX_WEBHOOK


def vibe_api_call(path, method="GET", body=None):
    """Call VibeCode API using requests (handles SSL/redirects better than urllib)."""
    url = f"{VIBE_BASE_URL}{path}"
    headers = {"X-Api-Key": VIBE_KEY, "Content-Type": "application/json"}
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=60)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=body, timeout=60)
        elif method == "PATCH":
            resp = requests.patch(url, headers=headers, json=body, timeout=60)
        else:
            resp = requests.request(method, url, headers=headers, json=body, timeout=60)
        resp.raise_for_status()
        parsed = resp.json()
        if not isinstance(parsed, dict):
            return {"_error": True, "exception": f"Unexpected response type: {type(parsed).__name__}"}
        return parsed
    except requests.exceptions.HTTPError as e:
        return {"_error": True, "status": e.response.status_code if e.response else None, "body": str(e)[:500]}
    except Exception as e:
        return {"_error": True, "exception": str(e)}


def b24_call(method, params=None):
    """Call Bitrix24 REST API via webhook using requests."""
    url = f"{BITRIX_WEBHOOK}{method}"
    if params:
        # Use safe='/' to preserve forward slashes in consignment numbers
        query = "&".join(f"{k}={urllib.parse.quote(str(v), safe='/')}" for k, v in params.items())
        url = f"{url}?{query}"
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def b24_post(method, payload):
    """POST to Bitrix24 REST API via webhook using requests with form-data.
    
    Automatically flattens nested dicts like {'fields': {'KEY': 'value'}} 
    to {'fields[KEY]': 'value'} format expected by Bitrix24.
    """
    url = f"{BITRIX_WEBHOOK}{method}"
    
    # Flatten nested fields dict
    flat_payload = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat_payload[f"{key}[{sub_key}]"] = sub_value
        else:
            flat_payload[key] = value
    
    try:
        resp = requests.post(url, data=flat_payload, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


def log_to_chat(message, chat_id=2386):
    """Send message to Bitrix24 chat from bot 530 (Геральд-WH)."""
    result = b24_post("im.message.add", {
        "DIALOG_ID": f"chat{chat_id}",
        "MESSAGE": message,
        "FROM_USER_ID": 530  # Send as bot "Геральд-WH"
    })
    if result.get("error"):
        print(f"[log_to_chat] Failed: {result.get('error')}")
    return result

def get_deals_by_category(category_id=6, limit=50):
    """Get deals from specific category."""
    return b24_post("crm.deal.list", {
        "FILTER": {"CATEGORY_ID": category_id},
        "SELECT": ["ID", "TITLE", "STAGE_ID", "ASSIGNED_BY_ID", "DATE_MODIFY"],
        "ORDER": {"DATE_MODIFY": "DESC"},
        "LIMIT": limit
    })


def get_deal_fields(deal_id):
    """Get full deal fields."""
    return b24_call("crm.deal.get", {"ID": deal_id})


def update_deal(deal_id, fields):
    """Update deal fields. Converts camelCase field names to UF_CRM_ format for Bitrix24 REST API."""
    # Convert field names: ufCrm_1234567890 -> UF_CRM_1234567890
    converted_fields = {}
    for key, value in fields.items():
        if key.startswith("ufCrm_"):
            # Convert to UF_CRM_ format
            converted_key = "UF_CRM_" + key[6:]
            converted_fields[converted_key] = value
        else:
            converted_fields[key] = value
    return b24_post("crm.deal.update", {"ID": deal_id, "fields": converted_fields})


def search_deals_by_field(field, value):
    """Search deals by custom field."""
    return b24_call("crm.deal.list", {
        f"FILTER[{field}]": value,
        "SELECT[]": ["ID", "TITLE"]
    })


def add_timeline_comment(entity_id, text, title="Автоматизация"):
    """Add timeline comment to deal."""
    return b24_post("crm.timeline.comment.add", {
        "fields": {
            "ENTITY_ID": entity_id,
            "ENTITY_TYPE": "deal",
            "COMMENT": text,
            "AUTHOR_ID": 376
        }
    })


def update_container_data(deal_id, container_name, data):
    """Update per-container data in JSON field UF_CRM_1781078096027.
    
    Args:
        deal_id: Deal ID
        container_name: Container identifier (e.g., 'TCKU1925813')
        data: Dict with keys like 'weight', 'status', etc.
    
    Returns:
        API response dict
    """
    # Get current JSON data
    deal_result = b24_call("crm.deal.get", {"ID": deal_id})
    deal = deal_result.get("result", {}) if isinstance(deal_result, dict) else {}
    
    # Parse existing JSON or start fresh
    json_field = deal.get("UF_CRM_1781078096027", "")
    try:
        if json_field and isinstance(json_field, str):
            containers = json.loads(json_field)
        elif json_field and isinstance(json_field, dict):
            containers = json_field
        else:
            containers = {}
    except (json.JSONDecodeError, TypeError):
        # If field contains plain text (single container), convert to JSON
        if json_field and isinstance(json_field, str):
            containers = {json_field.strip(): {}}
        else:
            containers = {}
    
    # Ensure container entry exists
    if container_name not in containers:
        containers[container_name] = {}
    
    # Update with new data
    containers[container_name].update(data)
    containers[container_name]["updated"] = datetime.now().isoformat()
    
    # Save back to CRM
    return b24_post("crm.deal.update", {
        "ID": deal_id,
        "fields": {
            "UF_CRM_1781078096027": json.dumps(containers, ensure_ascii=False)
        }
    })


def vibe_batch_call(calls):
    """POST /v1/batch — до 50 вызовов в одном запросе."""
    return vibe_api_call("/batch", "POST", {"calls": calls})


def batch_update_deals(items):
    """Массовое обновление до 500 сделок через VibeCode /v1/batch."""
    if not items:
        return {"success": True, "updated": 0}
    all_results = {}
    total_ok = 0
    total_failed = 0
    for batch_start in range(0, len(items), 50):
        batch = items[batch_start:batch_start + 50]
        calls = []
        for i, item in enumerate(batch):
            deal_id = item.pop("id", None)
            if not deal_id:
                continue
            calls.append({
                "id": f"update_{batch_start + i}",
                "entity": "deals",
                "action": "update",
                "entityId": deal_id,
                "params": item
            })
        result = vibe_batch_call(calls)
        if result.get("success") and isinstance(result.get("data"), dict):
            results = result["data"].get("results", {})
            all_results.update(results)
            ok = sum(1 for x in results.values() if x.get("item", {}).get("id") or x.get("id"))
            total_ok += ok
            total_failed += len(results) - ok
        else:
            total_failed += len(batch)
    return {"success": True, "updated": total_ok, "failed": total_failed, "data": {"results": all_results}}


def batch_create_deals(items):
    """Массовое создание до 500 сделок через VibeCode /v1/batch."""
    if not items:
        return {"success": True, "created": 0}
    all_results = {}
    total_ok = 0
    total_failed = 0
    for batch_start in range(0, len(items), 50):
        batch = items[batch_start:batch_start + 50]
        calls = []
        for i, item in enumerate(batch):
            calls.append({
                "id": f"create_{batch_start + i}",
                "entity": "deals",
                "action": "create",
                "params": item
            })
        result = vibe_batch_call(calls)
        if result.get("success") and isinstance(result.get("data"), dict):
            results = result["data"].get("results", {})
            all_results.update(results)
            ok = sum(1 for x in results.values() if x.get("item", {}).get("id") or x.get("id"))
            total_ok += ok
            total_failed += len(results) - ok
        else:
            total_failed += len(batch)
    return {"success": True, "created": total_ok, "failed": total_failed, "data": {"results": all_results}}
