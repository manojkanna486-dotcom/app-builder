"""
Context Builder for Agent System
Provides message history and context building functionality
"""

from typing import List, Dict, Any, Optional
import json
from datetime import datetime

class MessageHistory:
    """Simple message history container for agent context"""
    
    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the history"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(message)
    
    def get_messages(self) -> List[Dict[str, Any]]:
        """Get all messages"""
        return self.messages
    
    def clear(self):
        """Clear message history"""
        self.messages = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {"messages": self.messages}
    
    def from_dict(self, data: Dict[str, Any]):
        """Load from dictionary"""
        self.messages = data.get("messages", [])

def build_agent_context(
    agent_name: str,
    files: Optional[List[Dict[str, Any]]] = None,
    supabase_config: Optional[Dict[str, Any]] = None,
    message_history: Optional[MessageHistory] = None,
    user_prompt: Optional[str] = None,
    project_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Build context for agents with all necessary information"""
    
    # Initialize message history if not provided
    if message_history is None:
        message_history = MessageHistory()
    
    context = {
        "agent_name": agent_name,
        "timestamp": datetime.now().isoformat(),
        "user_prompt": user_prompt,
        "history": message_history.to_dict(),
    }
    
    # Add project data if provided
    if project_data:
        context["project"] = {
            "id": project_data.get("id"),
            "name": project_data.get("name"),
            "description": project_data.get("description"),
            "supabase_connected": project_data.get("supabase_connected", False),
            "requirements": project_data.get("requirements"),
        }
    
    # Add files/codebase context
    if files:
        context["files"] = files
        context["codebase_size"] = len(files)
    else:
        context["files"] = []
        context["codebase_size"] = 0
    
    # Add Supabase configuration
    if supabase_config:
        context["supabase"] = {
            "connected": True,
            "url": supabase_config.get("url"),
            "project_name": supabase_config.get("project_name"),
            "config": supabase_config
        }
    else:
        context["supabase"] = {
            "connected": False
        }
    
    return context