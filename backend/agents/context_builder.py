"""
Context Builder - Builds agent-specific context based on agent type

Rules:
- DEV and TEST agents: Full codebase + schema + message history
- Other agents (Planner, Product, UX, Database, Architecture): Schema + message history only
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AgentMessage:
    """Structured message from an agent"""
    
    def __init__(
        self,
        agent_name: str,
        plan: str,
        reasoning: str,
        affected_files: Optional[List[str]] = None,
        timestamp: Optional[str] = None
    ):
        self.agent_name = agent_name
        self.plan = plan
        self.reasoning = reasoning
        self.affected_files = affected_files or []
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "agent": self.agent_name,
            "timestamp": self.timestamp,
            "plan": self.plan,
            "reasoning": self.reasoning,
            "affected_files": self.affected_files
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AgentMessage':
        return cls(
            agent_name=data.get("agent", ""),
            plan=data.get("plan", ""),
            reasoning=data.get("reasoning", ""),
            affected_files=data.get("affected_files", []),
            timestamp=data.get("timestamp")
        )


class MessageHistory:
    """Shared message history for all agents"""
    
    def __init__(self):
        self.messages: List[AgentMessage] = []
    
    def add_message(self, message: AgentMessage):
        """Add a message to history"""
        self.messages.append(message)
        logger.info(f"Message history: Added message from {message.agent_name}")
    
    def get_messages(self) -> List[Dict]:
        """Get all messages as dicts"""
        return [msg.to_dict() for msg in self.messages]
    
    def format_for_context(self) -> str:
        """Format messages for inclusion in agent context"""
        if not self.messages:
            return "No previous agent messages."
        
        formatted = "AGENT MESSAGE HISTORY (with reasoning):\n\n"
        for msg in self.messages:
            formatted += f"[{msg.timestamp}] {msg.agent_name}:\n"
            formatted += f"  Plan: {msg.plan}\n"
            formatted += f"  Reasoning: {msg.reasoning}\n"
            if msg.affected_files:
                formatted += f"  Affected Files: {', '.join(msg.affected_files)}\n"
            formatted += "\n"
        
        return formatted
    
    def get_thinking_summary(self) -> str:
        """Get a summary of all reasoning/thinking from agents"""
        if not self.messages:
            return "No previous thinking available."
        
        thinking_parts = []
        for msg in self.messages:
            if msg.reasoning:
                thinking_parts.append(f"{msg.agent_name}: {msg.reasoning}")
        
        if thinking_parts:
            return "PREVIOUS THINKING:\n" + "\n".join(f"- {t}" for t in thinking_parts)
        return "No previous thinking available."


def build_agent_context(
    agent_name: str,
    files: Optional[List[Dict]] = None,
    supabase_config: Optional[Dict] = None,
    message_history: Optional[MessageHistory] = None,
    user_prompt: Optional[str] = None
) -> str:
    """
    Build context for an agent based on agent type.
    
    Args:
        agent_name: Name of the agent (dev, test, requirements, planner, etc.)
        files: List of file dicts with 'path' and 'content'
        supabase_config: Supabase configuration dict
        message_history: MessageHistory object
        user_prompt: Current user prompt
    
    Returns:
        Formatted context string
    """
    
    agent_name_lower = agent_name.lower()
    
    # DEV and TEST agents get full codebase
    if agent_name_lower in ["dev", "test", "tester", "fix", "fix_agent", "dev_agent"]:
        return _build_full_context(files, supabase_config, message_history, user_prompt)
    
    # Other agents get schema + history only
    else:
        return _build_limited_context(supabase_config, message_history, user_prompt)


def _build_full_context(
    files: Optional[List[Dict]],
    supabase_config: Optional[Dict],
    message_history: Optional[MessageHistory],
    user_prompt: Optional[str]
) -> str:
    """Build full context with entire codebase"""
    
    context_parts = []
    
    # User prompt
    if user_prompt:
        context_parts.append(f"USER REQUEST:\n{user_prompt}\n")
    
    # Message history with reasoning
    if message_history:
        context_parts.append(message_history.format_for_context())
        # Also include thinking summary for quick reference
        thinking_summary = message_history.get_thinking_summary()
        if thinking_summary and thinking_summary != "No previous thinking available.":
            context_parts.append(f"\n{thinking_summary}\n")
    
    # Full codebase - ALL files exactly as they exist
    if files:
        context_parts.append("ENTIRE PROJECT CODEBASE:\n")
        context_parts.append("=" * 80)
        for f in files:
            file_path = f.get("path", "unknown")
            file_content = f.get("content", "")
            file_type = f.get("file_type", "unknown")
            
            context_parts.append(f"\nFILE: {file_path} (Type: {file_type})")
            context_parts.append("-" * 80)
            context_parts.append(file_content)
            context_parts.append("")
        context_parts.append("=" * 80)
    else:
        context_parts.append("CODEBASE: No existing files (new project)\n")
    
    # Supabase schema
    if supabase_config:
        schema_info = _format_supabase_schema(supabase_config)
        if schema_info:
            context_parts.append("\nSUPABASE SCHEMA:\n")
            context_parts.append(schema_info)
    
    return "\n".join(context_parts)


def _build_limited_context(
    supabase_config: Optional[Dict],
    message_history: Optional[MessageHistory],
    user_prompt: Optional[str]
) -> str:
    """Build limited context without codebase (for planning agents)"""
    
    context_parts = []
    
    # User prompt
    if user_prompt:
        context_parts.append(f"USER REQUEST:\n{user_prompt}\n")
    
    # Message history with reasoning
    if message_history:
        context_parts.append(message_history.format_for_context())
        # Also include thinking summary for quick reference
        thinking_summary = message_history.get_thinking_summary()
        if thinking_summary and thinking_summary != "No previous thinking available.":
            context_parts.append(f"\n{thinking_summary}\n")
    
    # Supabase schema only (no codebase)
    if supabase_config:
        schema_info = _format_supabase_schema(supabase_config)
        if schema_info:
            context_parts.append("\nSUPABASE SCHEMA:\n")
            context_parts.append(schema_info)
    
    return "\n".join(context_parts)


def _format_supabase_schema(supabase_config: Dict) -> str:
    """Format Supabase schema information"""
    
    if not supabase_config:
        return ""
    
    schema_parts = []
    
    url = supabase_config.get("url", "")
    if url and url != "YOUR_SUPABASE_URL":
        schema_parts.append(f"Supabase URL: {url}")
        schema_parts.append(f"Connected: Yes")
    else:
        schema_parts.append("Supabase: Not connected (using mock data)")
    
    # If we have schema info in config, include it
    if "schema" in supabase_config:
        schema_parts.append(f"\nSchema Details:\n{supabase_config['schema']}")
    
    return "\n".join(schema_parts)

