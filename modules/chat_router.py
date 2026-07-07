"""
Chat Router Module - Forward messages between chats based on rules.
"""

import re
from config import CHAT_WORKFLOW
from api_client import b24_call, log_to_chat
from state import get_module_state

# Routing rules: source_chat -> {pattern -> target_chat}
ROUTING_RULES = {
    CHAT_WORKFLOW: {
        r"@экспедитор": 2670,
        r"@декларант": 2674,
        r"@склад": 2684,
    }
}


def get_chat_messages(chat_id, limit=20):
    """Get messages from chat."""
    return b24_call("im.dialog.messages.get", {
        "DIALOG_ID": f"chat{chat_id}",
        "LIMIT": limit
    })


def forward_message(text, target_chat):
    """Forward message to target chat."""
    return log_to_chat(text, chat_id=target_chat)


def run(state):
    mod_state = get_module_state(state, "chat_router")
    last_ids = mod_state.get("last_message_ids", {})
    
    forwarded_count = 0
    
    for source_chat, rules in ROUTING_RULES.items():
        result = get_chat_messages(source_chat)
        if "error" in result:
            continue
        
        messages = result.get("result", {}).get("messages", [])
        last_id = last_ids.get(str(source_chat), 0)
        new_last_id = last_id
        
        for msg in reversed(messages):
            msg_id = int(msg.get("id", 0))
            if msg_id <= last_id:
                continue
            
            text = msg.get("text", "")
            author_id = msg.get("authorId", "")
            
            # Skip bot messages
            if str(author_id) == "376":
                new_last_id = max(new_last_id, msg_id)
                continue
            
            # Routing disabled — all commands and files now processed only in chat2954
            new_last_id = max(new_last_id, msg_id)
        
        last_ids[str(source_chat)] = new_last_id
    
    mod_state["last_message_ids"] = last_ids
    return f"{forwarded_count} forwarded"
