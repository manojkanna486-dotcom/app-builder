"""
Model Configuration for Multi-Agent System
Cost-optimized model selection per agent role

Pricing Reference:
- Orchestrator: Mistral 7B ($0.20/M tokens)
- Dev/UI (Frontend): GPT-4o mini ($0.15/M tokens)
- Backend: DeepSeek Coder ($0.14/M tokens)
- Tester/Fix: Llama 3.1 8B (free)
- Deploy: Mistral 7B ($0.20/M tokens)
"""

# OpenRouter model identifiers
MODELS = {
    # Orchestrator Agent - workflow management, decision making
    "orchestrator": "mistralai/mistral-7b-instruct:free",
    
    # Requirements Agent - prompt parsing (uses orchestrator model)
    "requirements": "mistralai/mistral-7b-instruct:free",
    
    # Code Generation Agent - Frontend/UI code
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation Agent - Backend/SQL code
    "code_generation_backend": "deepseek/deepseek-coder",
    
    # Tester Agent - conversational testing (free)
    "tester": "meta-llama/llama-3.1-8b-instruct:free",
    
    # Fix Agent - bug fixes (free)
    "fix": "meta-llama/llama-3.1-8b-instruct:free",
    
    # Deployment Agent - deployment tasks
    "deployment": "mistralai/mistral-7b-instruct:free",
}

# Model-specific settings
MODEL_SETTINGS = {
    "mistralai/mistral-7b-instruct:free": {
        "max_tokens": 4096,
        "temperature": 0.7,
    },
    "openai/gpt-4o-mini": {
        "max_tokens": 16000,
        "temperature": 0.7,
    },
    "deepseek/deepseek-coder": {
        "max_tokens": 16000,
        "temperature": 0.3,  # Lower temp for more precise code
    },
    "meta-llama/llama-3.1-8b-instruct:free": {
        "max_tokens": 8192,
        "temperature": 0.5,
    },
}

def get_model(agent_type: str) -> str:
    """Get the model ID for a given agent type"""
    return MODELS.get(agent_type, "mistralai/mistral-7b-instruct:free")

def get_model_settings(model_id: str) -> dict:
    """Get model-specific settings"""
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 4096, "temperature": 0.7})
