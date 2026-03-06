"""
Model Configuration for Multi-Agent System

Architecture:
User Prompt → Orchestrator (Router) → Parallel Agents → Tester → Fix Loop → Deploy

All agents use Claude claude-sonnet-4-5 (latest) for best code quality.
"""

# OpenRouter model identifiers
CLAUDE_LATEST = "anthropic/claude-sonnet-4-5"

MODELS = {
    # Requirements Agent - planning and specs
    "requirements": CLAUDE_LATEST,
    
    # Code Generation - Frontend/UI
    "code_generation_frontend": CLAUDE_LATEST,
    
    # Code Generation - Backend/API/DB
    "code_generation_backend": CLAUDE_LATEST,
    
    # Tester Agent
    "tester": CLAUDE_LATEST,
    
    # Fix Agent
    "fix": CLAUDE_LATEST,
    
    # Deployment Agent
    "deployment": CLAUDE_LATEST,
    
    # Orchestrator / Router
    "orchestrator": CLAUDE_LATEST,
    
    # Dev Agent
    "dev": CLAUDE_LATEST,
    
    # Clarification Agent
    "clarification": CLAUDE_LATEST,
    
    # Thinking Agent
    "thinking": CLAUDE_LATEST,
}

# Model-specific settings
MODEL_SETTINGS = {
    CLAUDE_LATEST: {
        "max_tokens": 16000,
        "temperature": 0.3,
    },
}

# Fallback models when primary is unavailable
FALLBACK_MODELS = {
    CLAUDE_LATEST: "openai/gpt-4o-mini",
}

def get_model(agent_type: str) -> str:
    """Get the model ID for a given agent type"""
    return MODELS.get(agent_type, CLAUDE_LATEST)

def get_fallback_model(model_id: str) -> str:
    """Get fallback model when primary fails"""
    return FALLBACK_MODELS.get(model_id, "openai/gpt-4o-mini")

def get_model_settings(model_id: str) -> dict:
    """Get model-specific settings"""
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 16000, "temperature": 0.3})
