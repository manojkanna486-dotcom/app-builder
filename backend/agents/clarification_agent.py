"""
Clarification Agent - Analyzes prompts and extracts requirements
Asks minimal clarifying questions before generation
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger(__name__)

# Standard requirements for all apps
STANDARD_REQUIREMENTS = [
    "Responsive design (mobile-first)",
    "Clean, modern UI with consistent styling",
    "Proper error handling and loading states",
    "Form validation where applicable"
]

class ClarificationAgent:
    """Agent that analyzes prompts and extracts/clarifies requirements"""
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def analyze_prompt(self, prompt: str, project_context: Optional[Dict] = None) -> Dict:
        """
        Analyze the user's prompt and extract requirements.
        Returns structured requirements and optional clarifying questions.
        """
        system_prompt = """You are a requirements analyst for a web app builder.
Your job is to analyze the user's prompt and:
1. Extract clear, specific requirements
2. Identify what database tables/schema are needed
3. Identify what features/pages are needed
4. Ask 1-2 ESSENTIAL clarifying questions ONLY if something is genuinely ambiguous

Tech stack is FIXED: React frontend + Supabase backend (PostgreSQL + Edge Functions)

Output JSON format:
{
    "app_name": "suggested app name",
    "app_description": "brief description",
    "requirements": [
        {"id": "REQ-001", "category": "feature|ui|data|auth", "description": "specific requirement", "priority": "high|medium|low"}
    ],
    "database_schema": {
        "tables": [
            {"name": "table_name", "columns": [{"name": "col", "type": "text|int|uuid|timestamp|boolean|jsonb", "nullable": false, "default": null}], "rls_enabled": true}
        ]
    },
    "pages": ["page1", "page2"],
    "clarifying_questions": [
        {"id": "Q1", "question": "essential question?", "options": ["option1", "option2"]}
    ],
    "is_clear": true/false
}

Rules:
- Always include id, created_at, updated_at columns in tables
- Enable RLS (Row Level Security) by default
- Keep questions minimal - only ask if TRULY ambiguous
- If prompt is clear, set is_clear: true and leave clarifying_questions empty
- Include user authentication requirements if the app involves user-specific data
"""

        user_message = f"""Analyze this prompt and extract requirements:

PROMPT: {prompt}

{f"EXISTING PROJECT CONTEXT: {json.dumps(project_context)}" if project_context else "This is a NEW project."}

Extract requirements, suggest database schema, and only ask questions if something is genuinely unclear."""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message}
                        ],
                        "max_tokens": 4000,
                        "temperature": 0.3
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Clarification API error: {response.text}")
                    return self._fallback_analysis(prompt)
                
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                # Extract JSON from response
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    result = json.loads(json_match.group(), strict=False)
                    # Add standard requirements
                    for std_req in STANDARD_REQUIREMENTS:
                        result["requirements"].append({
                            "id": f"STD-{len(result['requirements'])+1:03d}",
                            "category": "ui",
                            "description": std_req,
                            "priority": "medium"
                        })
                    return result
                else:
                    return self._fallback_analysis(prompt)
                    
        except Exception as e:
            logger.error(f"Clarification agent error: {e}")
            return self._fallback_analysis(prompt)
    
    def _fallback_analysis(self, prompt: str) -> Dict:
        """Fallback when LLM analysis fails"""
        words = prompt.lower().split()
        app_name = "My App"
        
        # Try to extract app name from common patterns
        for keyword in ["build", "create", "make"]:
            if keyword in words:
                idx = words.index(keyword)
                if idx + 2 < len(words):
                    app_name = " ".join(words[idx+1:idx+3]).title()
                    break
        
        return {
            "app_name": app_name,
            "app_description": prompt[:100],
            "requirements": [
                {"id": "REQ-001", "category": "feature", "description": prompt, "priority": "high"}
            ] + [
                {"id": f"STD-{i+1:03d}", "category": "ui", "description": req, "priority": "medium"}
                for i, req in enumerate(STANDARD_REQUIREMENTS)
            ],
            "database_schema": {"tables": []},
            "pages": ["Home"],
            "clarifying_questions": [
                {"id": "Q1", "question": "What are the main features you need?", "options": []}
            ],
            "is_clear": False
        }
    
    async def refine_requirements(self, original_analysis: Dict, user_answers: Dict[str, str]) -> Dict:
        """Refine requirements based on user's answers to clarifying questions"""
        
        # Start with original requirements
        refined = original_analysis.copy()
        refined["user_answers"] = user_answers
        refined["is_clear"] = True
        refined["clarifying_questions"] = []
        
        # Add any new requirements based on answers
        for question_id, answer in user_answers.items():
            if answer:
                refined["requirements"].append({
                    "id": f"ANS-{question_id}",
                    "category": "feature",
                    "description": f"Based on user preference: {answer}",
                    "priority": "high"
                })
        
        return refined


def format_requirements_for_storage(analysis: Dict) -> Dict:
    """Format requirements for database storage"""
    return {
        "app_name": analysis.get("app_name", "App"),
        "app_description": analysis.get("app_description", ""),
        "requirements": analysis.get("requirements", []),
        "database_schema": analysis.get("database_schema", {}),
        "pages": analysis.get("pages", []),
        "user_answers": analysis.get("user_answers", {}),
        "created_at": None  # Will be set by database
    }
