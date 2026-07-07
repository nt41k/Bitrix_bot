"""
State management for unified automation.
Single JSON file for all modules.
"""

import json
import os
from config import STATE_FILE


def load_state():
    """Load state from JSON file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "crm_watcher": {},
        "google_sync": {},
        "chat_bot": {},
        "file_processor": {},
        "chat_router": {},
        "last_run": {},
        "errors": {},
    }


def save_state(state):
    """Save state to JSON file atomically."""
    tmp_file = STATE_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, STATE_FILE)
    except Exception:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        raise


def get_module_state(state, module_name):
    """Get module-specific state subset."""
    if module_name not in state:
        state[module_name] = {}
    return state[module_name]


def set_module_state(state, module_name, module_state):
    """Set module-specific state subset."""
    state[module_name] = module_state
