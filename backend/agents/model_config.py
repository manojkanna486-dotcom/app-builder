"""
Model Configuration for Multi-Agent System
Cost-optimized model selection per agent role

Pricing Reference (OpenRouter):
- Orchestrator: Mistral Small (free/cheap)
- Dev/UI (Frontend): GPT-4o mini ($0.15/M tokens)
- Backend: DeepSeek Coder ($0.14/M tokens)
- Tester/Fix: Llama 3.1 8B (free tier)
- Requirements: Google Gemini Flash (free tier)
"""

# OpenRouter model identifiers - using verified working models
MODELS = {
    # Orchestrator Agent - workflow management, decision making
    "orchestrator": "google/gemini-2.0-flash-exp:free",
    
    # Requirements Agent - prompt parsing (needs good reasoning)
    "requirements": "google/gemini-2.0-flash-exp:free",
    
    # Code Generation Agent - Frontend/UI code
    "code_generation_frontend": "openai/gpt-4o-mini",
    
    # Code Generation Agent - Backend/SQL code
    "code_generation_backend": "deepseek/deepseek-coder",
    
    # Tester Agent - conversational testing (free)
    "tester": "google/gemini-2.0-flash-exp:free",
    
    # Fix Agent - bug fixes (free)
    "fix": "google/gemini-2.0-flash-exp:free",
    
    # Deployment Agent - deployment tasks
    "deployment": "google/gemini-2.0-flash-exp:free",
}

# Model-specific settings
MODEL_SETTINGS = {
    "google/gemini-2.0-flash-exp:free": {
        "max_tokens": 8192,
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
    return MODELS.get(agent_type, "google/gemini-2.0-flash-exp:free")

def get_model_settings(model_id: str) -> dict:
    """Get model-specific settings"""
    return MODEL_SETTINGS.get(model_id, {"max_tokens": 4096, "temperature": 0.7})
