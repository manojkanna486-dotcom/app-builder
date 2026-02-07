"""
Model Configuration for Multi-Agent System
Cost-optimized model selection per agent role

Using verified OpenRouter free models + GPT-4o mini for code generation
"""

# OpenRouter model identifiers - verified working models
MODELS = {
    # Orchestrator Agent - workflow management (free)
    "orchestrator": "mistralai/mistral-small-3.1-24b-instruct:free",
    
    # Requirements Agent - prompt parsing (free, good reasoning)
    "requirements": "mistralai/mistral-small-3.1-24b-instruct:free",
    
    # Code Generation Agent - Frontend/UI code (paid, high quality)
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation Agent - Backend/SQL code  
    "code_generation_backend": "qwen/qwen3-coder:free",
    
    # Tester Agent - conversational testing (free)
    "tester": "meta-llama/llama-3.3-70b-instruct:free",
    
    # Fix Agent - bug fixes (free)
    "fix": "meta-llama/llama-3.3-70b-instruct:free",
    
    # Deployment Agent - deployment tasks (free)
    "deployment": "mistralai/mistral-small-3.1-24b-instruct:free",
}

# Model-specific settings
MODEL_SETTINGS = {
    "mistralai/mistral-small-3.1-24b-instruct:free": {
        "max_tokens": 8192,
        "temperature": 0.7,
    },
    "openai/gpt-4o-mini": {
        "max_tokens": 16000,
        "temperature": 0.7,
    },
    "qwen/qwen3-coder:free": {
        "max_tokens": 16000,
        "temperature": 0.3,  # Lower temp for more precise code
    },
    "meta-llama/llama-3.3-70b-instruct:free": {
        "max_tokens": 8192,
        "temperature": 0.5,
    },
}

def get_model(agent_type: str) -> str:
    """Get the model ID for a given agent type"""
    return MODELS.get(agent_type, "mistralai/mistral-small-3.1-24b-instruct:free")

def get_model_settings(model_id: str) -> dict:
    """Get model-specific settings"""
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 4096, "temperature": 0.7})
