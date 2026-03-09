"""
Requirements Clarification Agent
Extracts requirements from user prompts and generates clarifying questions.
"""

import json
import logging
import re
import httpx
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


REQUIREMENT_EXTRACTION_PROMPT = """You are an expert requirements analyst for a web app builder. 
Analyze the user's request and extract detailed, testable requirements.

User Request: "{user_prompt}"

Your task:
1. Extract ALL explicit and implicit requirements
2. Identify any ambiguous or missing details
3. Generate clarifying questions for unclear areas
4. Categorize each requirement

Return a JSON object with this EXACT structure:
{{
  "project_summary": "Brief 1-sentence description of what the user wants to build",
  "requirements": [
    {{
      "id": "REQ-001",
      "category": "ui|auth|data|api|logic|style",
      "description": "Clear description of the requirement",
      "priority": "must-have|should-have|nice-to-have",
      "testable": true,
      "validation_criteria": "How to verify this requirement is met"
    }}
  ],
  "clarifying_questions": [
    {{
      "id": "Q1",
      "question": "The clarifying question",
      "context": "Why this question matters",
      "options": ["Option A", "Option B", "Option C"],
      "default": "Suggested default if user skips"
    }}
  ],
  "assumptions": [
    "Assumption 1 if user doesn't specify",
    "Assumption 2"
  ],
  "technical_considerations": [
    "Tech consideration 1",
    "Tech consideration 2"
  ]
}}

IMPORTANT CATEGORIES:
- ui: Visual components, layout, buttons, forms, navigation
- auth: Login, signup, user sessions, permissions
- data: Database operations, CRUD, data fetching
- api: External API calls, integrations
- logic: Business logic, calculations, validations
- style: Colors, themes, animations, responsiveness

ALWAYS include these implicit requirements:
1. Responsive design (mobile, tablet, desktop)
2. Error handling for user actions
3. Loading states for async operations
4. Accessible UI elements

Return ONLY valid JSON, no markdown."""


RESPONSIVE_REQUIREMENTS = [
    {
        "id": "REQ-RESP-001",
        "category": "style",
        "description": "Fully responsive layout that works on mobile (320px+), tablet (768px+), and desktop (1024px+)",
        "priority": "must-have",
        "testable": True,
        "validation_criteria": "App displays correctly on all screen sizes without horizontal scroll"
    },
    {
        "id": "REQ-RESP-002", 
        "category": "style",
        "description": "Touch-friendly UI elements with minimum 44px tap targets on mobile",
        "priority": "must-have",
        "testable": True,
        "validation_criteria": "All interactive elements are easily tappable on mobile devices"
    },
    {
        "id": "REQ-RESP-003",
        "category": "style",
        "description": "Flexible typography that scales appropriately across devices",
        "priority": "must-have",
        "testable": True,
        "validation_criteria": "Text is readable without zooming on all devices"
    }
]


class ClarificationAgent:
    """
    Agent that extracts requirements and generates clarifying questions
    before code generation begins.
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
    
    async def analyze_prompt(self, user_prompt: str, project_context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Analyze user prompt and extract requirements with clarifying questions.
        
        Args:
            user_prompt: The user's request
            project_context: Optional context about the project (e.g., connected Supabase)
            
        Returns:
            Dict with requirements, questions, and assumptions
        """
        try:
            prompt = REQUIREMENT_EXTRACTION_PROMPT.format(user_prompt=user_prompt)
            
            # Add context if available
            if project_context:
                if project_context.get("supabase_connected"):
                    prompt += "\n\nCONTEXT: User has Supabase connected. Include auth and database requirements."
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000
                    }
                )
                
                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    
                    # Parse JSON response
                    try:
                        result = json.loads(content)
                    except json.JSONDecodeError:
                        # Try to extract JSON from response
                        json_match = re.search(r'\{[\s\S]*\}', content)
                        if json_match:
                            result = json.loads(json_match.group())
                        else:
                            result = self._create_default_analysis(user_prompt)
                    
                    # Always add responsive requirements
                    result["requirements"] = result.get("requirements", []) + RESPONSIVE_REQUIREMENTS
                    
                    # Add standard clarifying questions if none generated
                    if not result.get("clarifying_questions"):
                        result["clarifying_questions"] = self._generate_default_questions(user_prompt)
                    
                    return result
                    
        except Exception as e:
            logger.error(f"Error analyzing prompt: {e}")
        
        return self._create_default_analysis(user_prompt)
    
    def _create_default_analysis(self, user_prompt: str) -> Dict[str, Any]:
        """Create default analysis if LLM fails"""
        return {
            "project_summary": user_prompt[:100],
            "requirements": [
                {
                    "id": "REQ-001",
                    "category": "ui",
                    "description": user_prompt,
                    "priority": "must-have",
                    "testable": True,
                    "validation_criteria": "App renders and functions as described"
                }
            ] + RESPONSIVE_REQUIREMENTS,
            "clarifying_questions": self._generate_default_questions(user_prompt),
            "assumptions": [
                "Modern, clean UI design",
                "Standard web accessibility practices",
                "Responsive design for all devices"
            ],
            "technical_considerations": [
                "Using React with Tailwind CSS",
                "Supabase for backend (if connected)"
            ]
        }
    
    def _generate_default_questions(self, user_prompt: str) -> List[Dict]:
        """Generate default clarifying questions based on prompt analysis"""
        questions = []
        prompt_lower = user_prompt.lower()
        
        # Color/Style questions
        questions.append({
            "id": "Q-STYLE",
            "question": "What color theme would you prefer?",
            "context": "This affects the overall look and feel of your app",
            "options": ["Dark theme (modern)", "Light theme (clean)", "Blue professional", "Custom (describe in chat)"],
            "default": "Dark theme (modern)"
        })
        
        # Auth questions if relevant keywords
        if any(word in prompt_lower for word in ['user', 'login', 'account', 'profile', 'auth', 'sign']):
            questions.append({
                "id": "Q-AUTH",
                "question": "What authentication method do you need?",
                "context": "Determines how users will sign up and log in",
                "options": ["Email/Password", "Social login (Google)", "Both", "No authentication needed"],
                "default": "Email/Password"
            })
        
        # Data persistence questions
        if any(word in prompt_lower for word in ['save', 'store', 'data', 'list', 'crud', 'database', 'create', 'delete']):
            questions.append({
                "id": "Q-DATA",
                "question": "Should data persist between sessions?",
                "context": "Determines if we need database storage",
                "options": ["Yes, save to database", "No, local/session only", "Let me decide later"],
                "default": "Yes, save to database"
            })
        
        # Layout questions
        questions.append({
            "id": "Q-LAYOUT",
            "question": "What's the primary device for your users?",
            "context": "Helps optimize the layout priority",
            "options": ["Mobile-first", "Desktop-first", "Equal priority for both"],
            "default": "Equal priority for both"
        })
        
        return questions
    
    async def refine_requirements(self, original_analysis: Dict, user_answers: Dict[str, str]) -> Dict[str, Any]:
        """
        Refine requirements based on user's answers to clarifying questions.
        
        Args:
            original_analysis: The initial analysis
            user_answers: Dict mapping question IDs to user's chosen answers
            
        Returns:
            Updated analysis with refined requirements
        """
        refined = original_analysis.copy()
        
        # Apply user answers to requirements
        for q_id, answer in user_answers.items():
            if q_id == "Q-STYLE":
                refined["style_preference"] = answer
                if "dark" in answer.lower():
                    refined["requirements"].append({
                        "id": "REQ-STYLE-001",
                        "category": "style",
                        "description": "Dark color theme with appropriate contrast ratios",
                        "priority": "must-have",
                        "testable": True,
                        "validation_criteria": "App uses dark background with light text"
                    })
                elif "light" in answer.lower():
                    refined["requirements"].append({
                        "id": "REQ-STYLE-001",
                        "category": "style", 
                        "description": "Light color theme with clean aesthetic",
                        "priority": "must-have",
                        "testable": True,
                        "validation_criteria": "App uses light background with dark text"
                    })
            
            elif q_id == "Q-AUTH":
                if "no auth" not in answer.lower():
                    refined["requirements"].append({
                        "id": "REQ-AUTH-001",
                        "category": "auth",
                        "description": f"User authentication via {answer}",
                        "priority": "must-have",
                        "testable": True,
                        "validation_criteria": "Users can sign up and log in"
                    })
            
            elif q_id == "Q-DATA":
                if "database" in answer.lower():
                    refined["requirements"].append({
                        "id": "REQ-DATA-001",
                        "category": "data",
                        "description": "Persistent data storage with Supabase",
                        "priority": "must-have",
                        "testable": True,
                        "validation_criteria": "Data persists after page refresh"
                    })
            
            elif q_id == "Q-LAYOUT":
                refined["layout_priority"] = answer
        
        # Mark clarifying questions as answered
        refined["questions_answered"] = True
        refined["user_answers"] = user_answers
        
        return refined
    
    def format_requirements_for_display(self, analysis: Dict) -> str:
        """Format requirements for user-friendly display"""
        output = []
        
        output.append(f"## Project Summary\n{analysis.get('project_summary', 'N/A')}\n")
        
        output.append("## Requirements\n")
        for req in analysis.get("requirements", []):
            priority_emoji = "🔴" if req["priority"] == "must-have" else "🟡" if req["priority"] == "should-have" else "🟢"
            output.append(f"{priority_emoji} **{req['id']}** ({req['category']}): {req['description']}")
        
        if analysis.get("assumptions"):
            output.append("\n## Assumptions")
            for assumption in analysis["assumptions"]:
                output.append(f"• {assumption}")
        
        return "\n".join(output)
    
    def format_questions_for_display(self, analysis: Dict) -> List[Dict]:
        """Format clarifying questions for frontend display"""
        return analysis.get("clarifying_questions", [])
