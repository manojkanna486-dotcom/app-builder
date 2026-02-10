"""
Model Configuration for Multi-Agent System

Architecture:
User Prompt → Orchestrator (Router) → Parallel Agents → Tester → Fix Loop → Deploy

Agent → Model Mapping:
├── Requirements Agent: Claude 3.5 Sonnet
├── Dev Agent (UI): GPT-4o mini  
├── Dev Agent (Backend): Gemini 1.5 Pro
├── Conversational Tester: o1-mini
├── Fix Agent: DeepSeek Coder V2
└── Deployment Agent: Claude Haiku
"""

# OpenRouter model identifiers
MODELS = {
    # Requirements Agent - planning and specs (Claude 3.5 Sonnet)
    "requirements": "anthropic/claude-3.5-sonnet",
    
    # Code Generation - Frontend/UI (GPT-4o mini)
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation - Backend/API/DB (Gemini 1.5 Pro)
    "code_generation_backend": "google/gemini-pro-1.5",
    
    # Conversational Tester (o1-mini)
    "tester": "openai/o1-mini",
    
    # Fix Agent (DeepSeek Coder V2)
    "fix": "deepseek/deepseek-chat",
    
    # Deployment Agent (Claude Haiku)
    "deployment": "anthropic/claude-3-haiku",
    
    # Orchestrator (Router - uses Claude Haiku for routing decisions)
    "orchestrator": "anthropic/claude-3-haiku",
}

# Model-specific settings
MODEL_SETTINGS = {
    "anthropic/claude-3.5-sonnet": {
        "max_tokens": 8192,
        "temperature": 0.3,  # Lower temp for precise requirements
    },
    "openai/gpt-4o-mini": {
        "max_tokens": 16000,
        "temperature": 0.7,
    },
    "google/gemini-pro-1.5": {
        "max_tokens": 16000,
        "temperature": 0.5,
    },
    "openai/o1-mini": {
        "max_tokens": 8192,
        "temperature": 1.0,  # o1 models work best with temp=1
    },
    "deepseek/deepseek-chat": {
        "max_tokens": 16000,
        "temperature": 0.2,  # Low temp for precise code fixes
    },
    "anthropic/claude-3-haiku": {
        "max_tokens": 4096,
        "temperature": 0.5,
    },
}

# Fallback models when primary is unavailable
FALLBACK_MODELS = {
    "anthropic/claude-3.5-sonnet": "openai/gpt-4o-mini",
    "google/gemini-pro-1.5": "openai/gpt-4o-mini",
    "openai/o1-mini": "openai/gpt-4o-mini",
    "deepseek/deepseek-coder": "openai/gpt-4o-mini",
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
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 4096, "temperature": 0.7})
