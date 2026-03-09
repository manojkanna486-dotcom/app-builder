"""
Requirements Agent - Converts user prompts into structured requirements.json
MUST DO: Parse prompts, generate requirements, validate completeness
MUST NOT: Write code, assume unclear requirements (must flag ambiguity)
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import httpx

from .model_config import get_model, get_model_settings

logger = logging.getLogger(__name__)


class RequirementsAgent:
    """
    Converts user prompt into structured requirements.
    
    Output: requirements.json with:
    - Features
    - Pages  
    - User roles
    - Data models
    - Permissions
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def parse_prompt(self, prompt: str, existing_requirements: Optional[Dict] = None, agent_context: Optional[Dict] = None) -> Dict:
        """
        Parse user prompt into structured requirements.
        Returns requirements.json structure.
        """
        
        system_prompt = """You are a Requirements Agent for a web app builder.

Your ONLY job is to convert user prompts into structured requirements.json

You MUST:
1. Parse the prompt into clear, specific requirements
2. Identify all features needed
3. Identify all pages/screens needed
4. Identify user roles (if applicable)
5. Define data models with fields and types
6. Define permissions/access rules
7. Flag ANY ambiguity - do NOT assume

You MUST NOT:
- Write any code
- Make assumptions about unclear requirements
- Add features not explicitly requested

OUTPUT FORMAT (requirements.json):
{
    "app_name": "App Name",
    "app_description": "Brief description",
    "version": "1.0.0",
    "created_at": "ISO timestamp",
    
    "features": [
        {
            "id": "F001",
            "name": "Feature Name",
            "description": "What it does",
            "priority": "high|medium|low",
            "user_story": "As a [role], I want to [action] so that [benefit]"
        }
    ],
    
    "pages": [
        {
            "id": "P001",
            "name": "Page Name",
            "route": "/route",
            "description": "Page purpose",
            "features": ["F001"],
            "auth_required": true|false
        }
    ],
    
    "user_roles": [
        {
            "id": "R001",
            "name": "Role Name",
            "permissions": ["permission1", "permission2"]
        }
    ],
    
    "data_models": [
        {
            "id": "D001",
            "name": "ModelName",
            "table_name": "model_names",
            "fields": [
                {"name": "id", "type": "uuid", "primary_key": true},
                {"name": "field_name", "type": "text|int|boolean|timestamp|uuid|jsonb", "nullable": false, "default": null}
            ],
            "relationships": [
                {"type": "belongs_to|has_many|has_one", "model": "OtherModel", "foreign_key": "other_id"}
            ],
            "rls_enabled": true
        }
    ],
    
    "permissions": [
        {
            "model": "ModelName",
            "role": "Role Name",
            "actions": ["create", "read", "update", "delete"],
            "condition": "user_id = auth.uid()"
        }
    ],
    
    "ambiguities": [
        {
            "id": "A001",
            "question": "Clarifying question?",
            "options": ["Option 1", "Option 2"],
            "default": "Option 1"
        }
    ],
    
    "is_complete": true|false
}

RULES:
- Always include id, created_at, updated_at in data models
- Always enable RLS (Row Level Security) for all tables
- If prompt mentions users/auth, add user authentication feature
- If anything is unclear, add to "ambiguities" array and set is_complete: false
- Be thorough - missing requirements cause broken apps
"""

        # Build context information
        context_info = ""
        if agent_context:
            supabase_status = "connected" if agent_context.get("supabase", {}).get("connected") else "not connected"
            context_info = f"""
CONTEXT:
- Agent: {agent_context.get('agent_name', 'requirements')}
- Supabase: {supabase_status}
- Existing files: {agent_context.get('codebase_size', 0)}
"""

        user_message = f"""Parse this prompt into requirements.json:

PROMPT: {prompt}
{context_info}
{f"EXISTING REQUIREMENTS TO UPDATE: {json.dumps(existing_requirements)}" if existing_requirements else "This is a NEW app."}

Parse thoroughly. Flag any ambiguities."""

        # Get model config
        model = get_model("requirements")
        settings = get_model_settings(model)
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                import asyncio
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_message}
                            ],
                            "max_tokens": settings["max_tokens"],
                            "temperature": 0.2
                        }
                    )
                    
                    # Retry on 503 Service Unavailable or 429 Rate Limited
                    if response.status_code in [503, 429]:
                        last_error = f"Service unavailable/rate limited ({response.status_code})"
                        logger.warning(f"Requirements API {response.status_code} error, retrying in 5 seconds (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(5)
                        continue
                    
                    if response.status_code != 200:
                        logger.error(f"Requirements API error: {response.text}")
                        # Try fallback to creating minimal requirements
                        last_error = f"API error: {response.status_code}"
                        continue
                    
                    data = response.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    # Extract JSON from response
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        requirements = json.loads(json_match.group(), strict=False)
                        requirements["created_at"] = datetime.now(timezone.utc).isoformat()
                        return self._validate_requirements(requirements)
                    else:
                        return self._create_minimal_requirements(prompt)
                        
            except Exception as e:
                logger.error(f"Requirements agent error: {e}")
                last_error = str(e)
        
        logger.error(f"Requirements parsing failed after {max_retries} attempts: {last_error}")
        return self._create_minimal_requirements(prompt)
    
    async def resolve_ambiguities(self, requirements: Dict, answers: Dict[str, str]) -> Dict:
        """
        Update requirements based on user answers to ambiguities.
        """
        
        # Mark ambiguities as resolved
        for ambiguity in requirements.get("ambiguities", []):
            amb_id = ambiguity["id"]
            if amb_id in answers:
                ambiguity["resolved"] = True
                ambiguity["answer"] = answers[amb_id]
        
        # Check if all ambiguities resolved
        all_resolved = all(
            a.get("resolved", False) 
            for a in requirements.get("ambiguities", [])
        )
        
        if all_resolved:
            requirements["is_complete"] = True
            requirements["ambiguities"] = []  # Clear resolved ambiguities
        
        requirements["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        return requirements
    
    def _validate_requirements(self, requirements: Dict) -> Dict:
        """Validate and fill in missing fields"""
        
        # Ensure required fields exist
        if "features" not in requirements:
            requirements["features"] = []
        if "pages" not in requirements:
            requirements["pages"] = []
        if "data_models" not in requirements:
            requirements["data_models"] = []
        if "user_roles" not in requirements:
            requirements["user_roles"] = []
        if "permissions" not in requirements:
            requirements["permissions"] = []
        if "ambiguities" not in requirements:
            requirements["ambiguities"] = []
        
        # Ensure all data models have required fields
        for model in requirements["data_models"]:
            fields = model.get("fields", [])
            field_names = [f["name"] for f in fields]
            
            # Add id if missing
            if "id" not in field_names:
                fields.insert(0, {
                    "name": "id",
                    "type": "uuid",
                    "primary_key": True,
                    "default": "gen_random_uuid()"
                })
            
            # Add timestamps if missing
            if "created_at" not in field_names:
                fields.append({
                    "name": "created_at",
                    "type": "timestamp",
                    "nullable": False,
                    "default": "now()"
                })
            if "updated_at" not in field_names:
                fields.append({
                    "name": "updated_at",
                    "type": "timestamp",
                    "nullable": False,
                    "default": "now()"
                })
            
            model["fields"] = fields
            
            # Ensure RLS is enabled
            if "rls_enabled" not in model:
                model["rls_enabled"] = True
        
        # Set completeness based on ambiguities
        requirements["is_complete"] = len(requirements.get("ambiguities", [])) == 0
        
        return requirements
    
    def _create_minimal_requirements(self, prompt: str) -> Dict:
        """Create minimal requirements when parsing fails"""
        
        return {
            "app_name": "New App",
            "app_description": prompt[:200],
            "version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "features": [
                {
                    "id": "F001",
                    "name": "Main Feature",
                    "description": prompt,
                    "priority": "high",
                    "user_story": f"As a user, I want to {prompt[:50]}..."
                }
            ],
            "pages": [
                {
                    "id": "P001",
                    "name": "Home",
                    "route": "/",
                    "description": "Main page",
                    "features": ["F001"],
                    "auth_required": False
                }
            ],
            "user_roles": [],
            "data_models": [],
            "permissions": [],
            "ambiguities": [
                {
                    "id": "A001",
                    "question": "Could you provide more details about the features you need?",
                    "options": [],
                    "default": None
                }
            ],
            "is_complete": False
        }
    
    def get_requirements_summary(self, requirements: Dict) -> str:
        """Generate a human-readable summary of requirements"""
        
        features = requirements.get("features", [])
        pages = requirements.get("pages", [])
        models = requirements.get("data_models", [])
        ambiguities = requirements.get("ambiguities", [])
        
        summary = f"""
## {requirements.get('app_name', 'App')}
{requirements.get('app_description', '')}

### Features ({len(features)})
{chr(10).join(f"- {f['name']}: {f['description']}" for f in features)}

### Pages ({len(pages)})
{chr(10).join(f"- {p['name']} ({p['route']})" for p in pages)}

### Data Models ({len(models)})
{chr(10).join(f"- {m['name']}: {len(m.get('fields', []))} fields" for m in models)}
"""
        
        if ambiguities:
            summary += f"""
### ⚠️ Clarifications Needed ({len(ambiguities)})
{chr(10).join(f"- {a['question']}" for a in ambiguities)}
"""
        
        return summary.strip()
