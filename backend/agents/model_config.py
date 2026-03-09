"""
Model Configuration for Multi-Agent System

Architecture:
User Prompt → Orchestrator (Router) → Parallel Agents → Tester → Fix Loop → Deploy

Agent → Model Mapping (ChatGPT Mini / gpt-4o-mini):
├── Requirements Agent: openai/gpt-4o-mini
├── Code Generation: openai/gpt-4o-mini
├── Tester Agent: openai/gpt-4o-mini
├── Fix Agent: openai/gpt-4o-mini
├── Deployment Agent: openai/gpt-4o-mini
└── Orchestrator: openai/gpt-4o-mini
"""

# OpenRouter model identifiers - Using ChatGPT Mini (gpt-4o-mini)
MODELS = {
    # Requirements Agent
    "requirements": "openai/gpt-4o-mini",
    
    # Code Generation - Frontend/UI
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation - Backend/API/DB
    "code_generation_backend": "openai/gpt-4o-mini",
    
    # Tester Agent
    "tester": "openai/gpt-4o-mini",
    
    # Fix Agent
    "fix": "openai/gpt-4o-mini",
    
    # Deployment Agent
    "deployment": "openai/gpt-4o-mini",
    
    # Orchestrator (Router)
    "orchestrator": "openai/gpt-4o-mini",
}

# Model-specific settings
MODEL_SETTINGS = {
    # ChatGPT Mini (gpt-4o-mini) - primary model
    "openai/gpt-4o-mini": {
        "max_tokens": 16000,
        "temperature": 0.5,
    },
    # Legacy model settings (for fallback)
    "anthropic/claude-3.5-sonnet": {
        "max_tokens": 8192,
        "temperature": 0.3,
    },
    "google/gemini-pro-1.5": {
        "max_tokens": 16000,
        "temperature": 0.5,
    },
    "openai/o1-mini": {
        "max_tokens": 8192,
        "temperature": 1.0,
    },
    "deepseek/deepseek-chat": {
        "max_tokens": 16000,
        "temperature": 0.2,
    },
    "anthropic/claude-3-haiku": {
        "max_tokens": 4096,
        "temperature": 0.5,
    },
}

# Fallback models when primary is unavailable
FALLBACK_MODELS = {
    "openai/gpt-4o-mini": "anthropic/claude-3.5-sonnet",  # Fallback to Claude if GPT unavailable
    "anthropic/claude-opus-4.6": "anthropic/claude-3.5-sonnet",
    "anthropic/claude-3.5-sonnet": "openai/gpt-4o-mini",
    "google/gemini-pro-1.5": "openai/gpt-4o-mini",
    "openai/o1-mini": "openai/gpt-4o-mini",
    "deepseek/deepseek-chat": "openai/gpt-4o-mini",
    "anthropic/claude-3-haiku": "openai/gpt-4o-mini",
}

def get_model(agent_type: str) -> str:
    """Get the model ID for a given agent type"""
    return MODELS.get(agent_type, "openai/gpt-4o-mini")

def get_fallback_model(model_id: str) -> str:
    """Get fallback model when primary fails"""
    return FALLBACK_MODELS.get(model_id, "openai/gpt-4o-mini")

def get_model_settings(model_id: str) -> dict:
    """Get model-specific settings"""
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 8192, "temperature": 0.5})
