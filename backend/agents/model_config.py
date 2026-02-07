"""
Model Configuration for Multi-Agent System
Cost-optimized model selection per agent role

Strategy:
- Critical paths (requirements, code gen): Use reliable paid models (GPT-4o mini is cheap)
- Non-critical paths (testing, fix): Use free models with fallback
"""

# OpenRouter model identifiers
MODELS = {
    # Requirements Agent - needs reliable parsing (cheap paid model)
    "requirements": "openai/gpt-4o-mini",
    
    # Code Generation Agent - Frontend/UI code (cheap paid model)
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation Agent - Backend/SQL code (free when available)
    "code_generation_backend": "qwen/qwen3-coder:free",
    
    # Tester Agent - conversational testing (free)
    "tester": "meta-llama/llama-3.3-70b-instruct:free",
    
    # Fix Agent - bug fixes (free)
    "fix": "meta-llama/llama-3.3-70b-instruct:free",
    
    # Orchestrator Agent (not used for LLM calls)
    "orchestrator": "openai/gpt-4o-mini",
    
    # Deployment Agent (not used for LLM calls)
    "deployment": "openai/gpt-4o-mini",
}

# Fallback models when primary is unavailable
FALLBACK_MODELS = {
    "qwen/qwen3-coder:free": "openai/gpt-4o-mini",
    "meta-llama/llama-3.3-70b-instruct:free": "openai/gpt-4o-mini",
    "mistralai/mistral-small-3.1-24b-instruct:free": "openai/gpt-4o-mini",
}

# Model-specific settings
MODEL_SETTINGS = {
    "openai/gpt-4o-mini": {
        "max_tokens": 16000,
        "temperature": 0.7,
    },
    "qwen/qwen3-coder:free": {
        "max_tokens": 16000,
        "temperature": 0.3,
    },
    "meta-llama/llama-3.3-70b-instruct:free": {
        "max_tokens": 8192,
        "temperature": 0.5,
    },
    "mistralai/mistral-small-3.1-24b-instruct:free": {
        "max_tokens": 8192,
        "temperature": 0.7,
    },
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
