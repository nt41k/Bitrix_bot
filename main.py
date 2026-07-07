#!/usr/bin/env python3
"""
Unified Cargonovo Automation - Main Entry Point
Runs all modules with error isolation, per-module timeouts, and unified logging.
"""

from utils.logger import get_module_logger

logger = get_module_logger("main")

import sys
import os
import time
import traceback
import signal
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LOG_FILE, STATE_FILE, MODULE_INTERVALS, CHAT_REPORTS
from state import load_state, save_state
from api_client import log_to_chat

# Lock file — предотвращает параллельный запуск
import fcntl
import atexit

def acquire_lock():
    lock_path = "/tmp/cargonovo_automation.lock"
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        fd.close()
        return None
    return fd

def release_lock(fd):
    if fd:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()

# Import modules
from modules import crm_watcher, google_sync, chat_bot, file_processor, chat_router

MODULES = {
    "chat_bot": chat_bot,
    "file_processor": file_processor,
    "google_sync": google_sync,
    "crm_watcher": crm_watcher,
    "chat_router": chat_router,
}

# Timeout config
MODULE_TIMEOUT = 90       # default seconds per module
MODULE_TIMEOUTS = {       # per-module overrides
    "chat_bot": 60,       # Writeback to Google Sheets needs time
    "file_processor": 30,
    "google_sync": 180,   # Google fetch is slow, needs more time
    "crm_watcher": 60,
    "chat_router": 15,
}
GLOBAL_CUTOFF = 115       # skip remaining if elapsed > this (cron limit is 120s)


def log_line(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class ModuleTimeout(Exception):
    pass


def _timeout_handler(signum, frame):
    raise ModuleTimeout("Module exceeded time limit")


def run_module(name, module, state, max_seconds=None):
    """Run a single module with error isolation and timeout protection."""
    if max_seconds is None:
        max_seconds = MODULE_TIMEOUTS.get(name, MODULE_TIMEOUT)
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(max_seconds)
    start = time.time()
    result_str = ""
    try:
        log_line(f"[START] {name}")
        result_str = module.run(state)
        elapsed = time.time() - start
        log_line(f"[OK] {name}: {result_str} ({elapsed:.1f}s)")
        state["last_run"][name] = time.time()
        state["errors"][name] = None
        return True, elapsed, result_str
    except ModuleTimeout:
        elapsed = time.time() - start
        err_msg = f"TIMEOUT after {elapsed:.1f}s"
        log_line(f"[ERROR] {name}: {err_msg}")
        state["errors"][name] = {
            "time": time.time(),
            "error": err_msg,
            "traceback": "",
        }
        return False, elapsed, err_msg
    except Exception as e:
        elapsed = time.time() - start
        err_msg = f"{type(e).__name__}: {str(e)}"
        log_line(f"[ERROR] {name}: {err_msg}")
        state["errors"][name] = {
            "time": time.time(),
            "error": err_msg,
            "traceback": traceback.format_exc(),
        }
        return False, elapsed, err_msg
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def should_run_module(module_name, state):
    """Check if module should run based on its interval."""
    interval = MODULE_INTERVALS.get(module_name, 60)
    last_run = state.get("last_run", {}).get(module_name, 0)
    now = time.time()
    return (now - last_run) >= interval


def main():
    start_time = time.time()
    
    # Acquire lock
    lock_fd = acquire_lock()
    if lock_fd is None:
        print("[LOCK] Another instance is running, exiting")
        return 0  # Exit silently — don't report as error
    atexit.register(release_lock, lock_fd)
    
    log_line("=== Cargonovo Automation Started ===")
    
    state = load_state()
    if "last_run" not in state:
        state["last_run"] = {}
    if "errors" not in state:
        state["errors"] = {}
    
    results = {}
    module_outputs = {}
    for name, module in MODULES.items():
        elapsed = time.time() - start_time
        if elapsed >= GLOBAL_CUTOFF:
            log_line(f"[SKIP] {name}: global cutoff reached ({elapsed:.1f}s)")
            results[name] = "skipped"
            continue
            
        if should_run_module(name, state):
            success, mod_elapsed, output = run_module(name, module, state)
            results[name] = "ok" if success else "error"
            module_outputs[name] = output
        else:
            results[name] = "skipped"
            log_line(f"[SKIP] {name}: interval not reached")
    
    save_state(state)
    
    # Summary log
    ok_count = sum(1 for v in results.values() if v == "ok")
    err_count = sum(1 for v in results.values() if v == "error")
    skip_count = sum(1 for v in results.values() if v == "skipped")
    total_elapsed = time.time() - start_time
    log_line(f"=== Completed: {ok_count} ok, {err_count} errors, {skip_count} skipped ({total_elapsed:.1f}s) ===")
    
    # Send summary to reports chat
    try:
        summary_lines = [f"📋 Cron ({datetime.now().strftime('%H:%M')})"]
        for name, status in results.items():
            if status == "ok":
                output = module_outputs.get(name, "")
                summary_lines.append(f"✅ {name}: {output}")
            elif status == "error":
                output = module_outputs.get(name, "")
                summary_lines.append(f"❌ {name}: {output}")
            else:
                summary_lines.append(f"⏭️ {name}: skipped")
        
        summary_msg = "\n".join(summary_lines)
        log_line(f"[SUMMARY] Sending to chat {CHAT_REPORTS}: {len(summary_msg)} chars")
        result = log_to_chat(summary_msg, chat_id=CHAT_REPORTS)
        log_line(f"[SUMMARY] Result: {result}")
    except Exception as e:
        log_line(f"[ERROR] Failed to send summary: {e}")
    
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
