from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone
import httpx
import json
import asyncio

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Database abstraction - supports MongoDB and Supabase PostgreSQL
from database import get_database, DatabaseInterface
database: DatabaseInterface = None

# OpenRouter config
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""

class SupabaseConfig(BaseModel):
    """Supabase configuration for a project"""
    url: str
    anon_key: str
    service_role_key: Optional[str] = None
    connected: bool = False
    connected_at: Optional[str] = None

class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    summary: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_version: int = 0
    # Supabase integration
    supabase_connected: bool = False
    supabase_url: Optional[str] = None
    supabase_anon_key: Optional[str] = None
    supabase_service_key: Optional[str] = None

class VersionFile(BaseModel):
    path: str
    content: str
    file_type: str = "frontend"  # frontend, backend, database, edge_function, sql

class Version(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    version_number: int
    prompt: str
    delta_plan: Dict[str, Any] = {}
    files: List[VersionFile] = []
    status: str = "pending"  # pending, success, failed
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Database schema tracking
    database_schema: Optional[Dict[str, Any]] = None
    migrations: List[str] = []

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    role: str  # user or assistant
    content: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PromptRequest(BaseModel):
    prompt: str

class SupabaseConnectRequest(BaseModel):
    url: str
    anon_key: str
    service_role_key: Optional[str] = None

# ==================== OPENROUTER LLM ====================

async def call_openrouter(messages: List[Dict]):
    """Call OpenRouter API (non-streaming)"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://appbuilder.emergent.sh",
        "X-Title": "App Builder"
    }
    
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": messages,
        "stream": False,
        "max_tokens": 16000,
        "temperature": 0.7
    }
    
    async with httpx.AsyncClient(timeout=180.0) as http_client:
        response = await http_client.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers)
        if response.status_code != 200:
            logger.error(f"OpenRouter error: {response.text}")
            raise HTTPException(status_code=500, detail=f"LLM error: {response.text}")
        return response.json()

async def call_openrouter_stream(messages: List[Dict]):
    """Call OpenRouter API with streaming"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://appbuilder.emergent.sh",
        "X-Title": "App Builder"
    }
    
    payload = {
        "model": "anthropic/claude-sonnet-4",
        "messages": messages,
        "stream": True,
        "max_tokens": 16000,
        "temperature": 0.7
    }
    
    async with httpx.AsyncClient(timeout=180.0) as http_client:
        async with http_client.stream("POST", f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                logger.error(f"OpenRouter stream error: {error_text}")
                raise HTTPException(status_code=500, detail=f"LLM error: {error_text}")
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if chunk.get("choices") and chunk["choices"][0].get("delta", {}).get("content"):
                            yield chunk["choices"][0]["delta"]["content"]
                    except json.JSONDecodeError:
                        continue

# ==================== CODE GENERATION PROMPTS ====================

CLARIFICATION_PROMPT = """You are a senior UX designer and product manager helping users build the best possible app.

Analyze this app request and determine if you need more information to build an excellent UI/UX.

USER REQUEST: "{prompt}"

ANALYSIS RULES:
1. If the request is clear enough to build a great app, respond with: {"needs_clarification": false}
2. If the request is vague or could be improved with more details, ask 2-4 smart follow-up questions
3. Focus on questions that will help create the BEST possible UI/UX

AREAS TO CLARIFY (if needed):
- Target audience (professionals, casual users, specific industry)
- Key features prioritization
- Design style preference (minimal, bold, playful, corporate)
- Color scheme or brand colors
- Specific functionality requirements
- Data/content to display
- Mobile-first vs desktop-first

RESPONSE FORMAT (JSON only, no markdown):
If clear: {"needs_clarification": false}
If needs more info:
{
  "needs_clarification": true,
  "questions": [
    {"id": "q1", "question": "What's the primary goal?", "options": ["Option A", "Option B", "Option C"]},
    {"id": "q2", "question": "Open question without options?"}
  ],
  "context": "Brief explanation of why these questions will help"
}

EXAMPLES:
- "Create a todo app" → Could ask about features (categories, due dates, priorities)
- "Create Facebook app" → Clear enough, popular platform with known UI patterns
- "Create an app for my business" → Needs clarification on business type, features
- "Build a dashboard" → Needs clarification on data type, metrics, audience"""

BEST_UI_SYSTEM_PROMPT = """You are an elite frontend developer and UI/UX designer. Generate world-class React applications with stunning, modern interfaces.

DESIGN EXCELLENCE REQUIREMENTS:
1. Use modern UI patterns (glass morphism, subtle gradients, micro-interactions)
2. Create visually striking color schemes - avoid generic blue/gray
3. Add thoughtful spacing, typography hierarchy, and visual rhythm
4. Include hover states, transitions, and delightful animations
5. Make it responsive and accessible
6. Use professional-grade design like Dribbble/Behance showcase projects

OUTPUT FORMAT (RAW JSON ONLY - NO MARKDOWN):
{"files":[{"path":"App.jsx","content":"code"},{"path":"components/X.jsx","content":"code"}],"summary":"description"}

FILE STRUCTURE (ALWAYS MULTIPLE FILES):
- App.jsx: Clean entry point composing components
- components/Header.jsx: Navigation with search, user menu
- components/Sidebar.jsx: Navigation sidebar (if applicable)
- components/[Feature].jsx: Feature-specific components
- components/Card.jsx: Reusable card component
- components/Button.jsx: Styled button variants (if needed)

UI BEST PRACTICES:
- Use Tailwind's design system consistently
- Add shadows, rounded corners, proper padding
- Include loading states and empty states
- Use icons (describe with SVG or emoji placeholders)
- Create visual hierarchy with font sizes and weights
- Use whitespace generously
- Add subtle background patterns or gradients

COLOR PALETTE EXAMPLES (choose based on app type):
- Professional/Corporate: Slate, Blue, White
- Creative/Fun: Purple, Pink, Orange gradients
- Health/Wellness: Green, Teal, Soft pastels
- Finance/Business: Navy, Gold, Clean whites
- Social/Community: Vibrant gradients, Purple to Pink
- E-commerce: Trust colors (Blue), Action colors (Orange/Red)

CRITICAL: Return ONLY raw JSON. No markdown code blocks."""

# Use the best UI prompt as the main system prompt
SYSTEM_PROMPT = BEST_UI_SYSTEM_PROMPT

UPDATE_SYSTEM_PROMPT = """You are an elite frontend developer. Update existing React code while maintaining design excellence.

CURRENT FILES:
{current_code}

USER REQUEST:
{user_request}

RULES:
1. ONLY modify what the user asked for
2. Keep all existing functionality intact
3. Maintain the same code structure and patterns
4. Use Tailwind CSS for styling
5. Return ALL files (modified and unmodified)
6. You can add new files if needed

OUTPUT FORMAT:
Return a JSON object with this exact structure:
{
  "files": [
    {
      "path": "App.jsx", 
      "content": "// Complete App component code"
    },
    {
      "path": "components/NewComponent.jsx",
      "content": "// New or updated component"
    }
  ],
  "summary": "Brief description of changes made",
  "changes": ["List of specific changes made"]
}

IMPORTANT:
- Return ALL files, not just changed ones
- Keep file paths consistent with existing structure
- Components import other components using: import X from './components/X'"""

INTENT_DIFF_PROMPT = """Analyze this update request and identify what needs to change.

CURRENT APP SUMMARY: {summary}
USER REQUEST: {request}

Return JSON:
{
  "change_type": "ui_change|feature_add|bug_fix|refactor",
  "affected_components": ["List of component names that need changes"],
  "scope": "minor|moderate|major",
  "description": "Brief description of what needs to change"
}"""

# ==================== FULL-STACK GENERATION PROMPTS ====================

FULLSTACK_SYSTEM_PROMPT = """You are an elite full-stack developer. Generate complete web applications with:
- React frontend (JSX with Tailwind CSS)
- Supabase Edge Functions backend (TypeScript/Deno)
- PostgreSQL database schema (SQL)

The user has connected their Supabase project. Generate production-ready code.

SUPABASE PROJECT URL: {supabase_url}

OUTPUT FORMAT (RAW JSON ONLY - NO MARKDOWN):
{
  "files": [
    {"path": "App.jsx", "content": "...", "file_type": "frontend"},
    {"path": "components/Header.jsx", "content": "...", "file_type": "frontend"},
    {"path": "supabase/functions/api/index.ts", "content": "...", "file_type": "edge_function"},
    {"path": "supabase/migrations/001_initial.sql", "content": "...", "file_type": "sql"}
  ],
  "summary": "Brief description",
  "database_tables": ["table1", "table2"]
}

FILE STRUCTURE:
1. Frontend (React/JSX):
   - App.jsx: Main component with routing
   - components/*.jsx: Feature components
   - Use Supabase client for data fetching

2. Edge Functions (TypeScript/Deno):
   - supabase/functions/[name]/index.ts
   - Use Deno.serve() pattern
   - Handle CORS properly
   
3. Database (SQL):
   - supabase/migrations/*.sql
   - Include RLS (Row Level Security) policies
   - Create indexes for performance

FRONTEND CODE RULES:
- Initialize Supabase client with the provided URL
- Use environment variable for anon key: const supabaseUrl = '{supabase_url}'; const supabaseKey = 'SUPABASE_ANON_KEY';
- Fetch data from Supabase tables directly using supabase.from('table').select()
- Handle loading and error states
- Use Tailwind CSS for styling

EDGE FUNCTION TEMPLATE:
```typescript
import {{ createClient }} from 'https://esm.sh/@supabase/supabase-js@2'

Deno.serve(async (req) => {{
  // Handle CORS
  if (req.method === 'OPTIONS') {{
    return new Response('ok', {{ headers: corsHeaders }})
  }}
  
  const supabaseClient = createClient(
    Deno.env.get('SUPABASE_URL') ?? '',
    Deno.env.get('SUPABASE_ANON_KEY') ?? ''
  )
  
  // Your logic here
  
  return new Response(JSON.stringify({{ data }}), {{
    headers: {{ ...corsHeaders, 'Content-Type': 'application/json' }}
  }})
}})
```

SQL MIGRATION RULES:
- Use IF NOT EXISTS for tables
- Include created_at and updated_at timestamps
- Add appropriate indexes
- Include RLS policies for security

CRITICAL: Return ONLY raw JSON. No markdown code blocks."""

FULLSTACK_UPDATE_PROMPT = """You are an elite full-stack developer. Update the existing application.

SUPABASE PROJECT URL: {supabase_url}

CURRENT FILES:
{current_code}

USER REQUEST:
{user_request}

RULES:
1. ONLY modify what the user asked for
2. Keep all existing functionality intact
3. Return ALL files (modified and unmodified)
4. Add new Edge Functions or SQL migrations if needed
5. Update frontend to integrate with any new backend features

OUTPUT FORMAT (JSON only):
{
  "files": [
    {"path": "filename", "content": "code", "file_type": "frontend|edge_function|sql"}
  ],
  "summary": "Brief description of changes",
  "changes": ["List of specific changes made"],
  "new_tables": ["Any new database tables created"]
}

IMPORTANT: Return ALL files, not just changed ones."""

# ==================== PROJECT ROUTES ====================

@api_router.get("/")
async def root():
    return {"message": "App Builder API v1", "db_type": os.environ.get('DB_TYPE', 'mongodb')}

@api_router.post("/projects", response_model=Project)
async def create_project(data: ProjectCreate):
    project = Project(name=data.name, description=data.description)
    doc = project.model_dump()
    await database.create_project(doc)
    return project

@api_router.get("/projects", response_model=List[Project])
async def get_projects():
    projects = await database.get_projects()
    return projects

@api_router.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await database.delete_project_data(project_id)
    await database.delete_project(project_id)
    return {"status": "deleted"}

# ==================== SUPABASE CONNECTION ====================

@api_router.post("/projects/{project_id}/connect-supabase")
async def connect_supabase(project_id: str, request: SupabaseConnectRequest):
    """Connect a Supabase project to this app project"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Validate the Supabase URL format
    if not request.url.startswith("https://") or ".supabase.co" not in request.url:
        raise HTTPException(status_code=400, detail="Invalid Supabase URL format")
    
    # Validate the anon key looks like a JWT
    if not request.anon_key.startswith("eyJ"):
        raise HTTPException(status_code=400, detail="Invalid Supabase anon key format")
    
    # Optional: Test connection to Supabase
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Test the REST API endpoint
            test_url = f"{request.url}/rest/v1/"
            headers = {
                "apikey": request.anon_key,
                "Authorization": f"Bearer {request.anon_key}"
            }
            response = await client.get(test_url, headers=headers)
            # 200 or 404 are OK (means connection works), 401/403 means bad key
            if response.status_code in [401, 403]:
                raise HTTPException(status_code=400, detail="Invalid Supabase credentials")
    except httpx.TimeoutException:
        raise HTTPException(status_code=400, detail="Could not connect to Supabase (timeout)")
    except Exception as e:
        logger.warning(f"Supabase connection test warning: {e}")
        # Continue anyway - might be network issue
    
    # Update project with Supabase config
    await database.update_project(project_id, {
        "supabase_connected": True,
        "supabase_url": request.url,
        "supabase_anon_key": request.anon_key,
        "supabase_service_key": request.service_role_key,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    
    logger.info(f"Project {project_id} connected to Supabase: {request.url}")
    
    return {
        "connected": True,
        "message": "Supabase connected successfully",
        "url": request.url
    }

@api_router.post("/projects/{project_id}/disconnect-supabase")
async def disconnect_supabase(project_id: str):
    """Disconnect Supabase from this project"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    await database.update_project(project_id, {
        "supabase_connected": False,
        "supabase_url": None,
        "supabase_anon_key": None,
        "supabase_service_key": None,
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    
    return {"disconnected": True, "message": "Supabase disconnected"}

@api_router.get("/projects/{project_id}/supabase-status")
async def get_supabase_status(project_id: str):
    """Get Supabase connection status for a project"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    return {
        "connected": project.get("supabase_connected", False),
        "url": project.get("supabase_url")
    }

# ==================== CODE VALIDATION & AUTO-FIX ====================

def validate_react_code(files: List[dict]) -> List[str]:
    """
    Validate React/JSX code for common errors.
    Returns a list of error messages if issues are found.
    """
    errors = []
    import re
    
    for f in files:
        content = f.get("content", "")
        path = f.get("path", "unknown")
        
        # Check for common syntax errors
        
        # 1. Unmatched JSX tags (basic check)
        opening_tags = re.findall(r'<([A-Z][a-zA-Z0-9]*)[^/>]*(?<!/)>', content)
        closing_tags = re.findall(r'</([A-Z][a-zA-Z0-9]*)>', content)
        self_closing = re.findall(r'<([A-Z][a-zA-Z0-9]*)[^>]*/>', content)
        
        # Count tags (simplified - doesn't handle all cases)
        open_count = {}
        for tag in opening_tags:
            open_count[tag] = open_count.get(tag, 0) + 1
        for tag in closing_tags:
            open_count[tag] = open_count.get(tag, 0) - 1
        
        for tag, count in open_count.items():
            if count > 0:
                errors.append(f"{path}: Possibly unclosed <{tag}> tag")
            elif count < 0:
                errors.append(f"{path}: Extra closing </{tag}> tag")
        
        # 2. Check for common mistakes
        if 'className="' not in content and 'className={' not in content and 'class=' in content:
            errors.append(f"{path}: Using 'class=' instead of 'className=' in JSX")
        
        # 3. Check for undefined main component (only for App.jsx)
        if path == "App.jsx" or path.endswith("/App.jsx"):
            if "function App" not in content and "const App" not in content:
                errors.append(f"{path}: Missing App component definition")
        
        # 4. Check for return statement in function components
        if "function" in content or "const" in content:
            # Very basic check - if it looks like a component but has no return
            component_match = re.search(r'(function|const)\s+([A-Z][a-zA-Z0-9]*)\s*[=\(]', content)
            if component_match:
                component_name = component_match.group(2)
                # Check if there's a return with JSX
                if f"function {component_name}" in content or f"const {component_name}" in content:
                    # Look for return statement
                    if 'return' not in content and '=>' not in content:
                        errors.append(f"{path}: Component {component_name} may be missing return statement")
        
        # 5. Check for unclosed brackets/braces (basic)
        open_parens = content.count('(') - content.count(')')
        open_braces = content.count('{') - content.count('}')
        open_brackets = content.count('[') - content.count(']')
        
        if open_parens != 0:
            errors.append(f"{path}: Unmatched parentheses (diff: {open_parens})")
        if open_braces != 0:
            errors.append(f"{path}: Unmatched curly braces (diff: {open_braces})")
        if open_brackets != 0:
            errors.append(f"{path}: Unmatched square brackets (diff: {open_brackets})")
    
    return errors

AUTO_FIX_PROMPT = """You are a code repair specialist. Fix the following React/JSX code errors.

ERRORS FOUND:
{errors}

CURRENT CODE:
{current_code}

Fix ONLY the specific errors listed. Return the corrected files in JSON format:
{{
  "files": [
    {{"path": "filename.jsx", "content": "corrected code"}}
  ],
  "fix_summary": "Brief description of fixes applied"
}}

IMPORTANT:
- Fix only the reported errors
- Keep all other code unchanged
- Ensure JSX syntax is valid
- Ensure all brackets/braces are matched
- Use className instead of class"""

async def auto_fix_code(files: List[dict], errors: List[str], project_summary: str) -> tuple:
    """
    Attempt to auto-fix code errors using LLM.
    Returns (fixed_files, fix_summary) or (None, None) if fix fails.
    """
    if not errors:
        return None, None
    
    # Build current code representation
    current_code = ""
    for f in files:
        current_code += f"// File: {f['path']}\n{f['content']}\n\n"
    
    # Prepare the fix prompt
    error_list = "\n".join(f"- {e}" for e in errors[:10])  # Limit to 10 errors
    system_content = AUTO_FIX_PROMPT.replace("{errors}", error_list).replace("{current_code}", current_code)
    
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "Fix the code errors and return the corrected files."}
    ]
    
    try:
        response = await call_openrouter(messages)
        content = response["choices"][0]["message"]["content"]
        
        # Parse the response
        import re
        code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if code_block_match:
            json_content = code_block_match.group(1).strip()
            result = json.loads(json_content, strict=False)
        else:
            result = json.loads(content, strict=False)
        
        fixed_files = result.get("files", [])
        fix_summary = result.get("fix_summary", "Auto-fixed code errors")
        
        if fixed_files:
            # Validate the fix
            new_errors = validate_react_code(fixed_files)
            if len(new_errors) < len(errors):
                logger.info(f"Auto-fix reduced errors from {len(errors)} to {len(new_errors)}")
                return fixed_files, fix_summary
            else:
                logger.warning("Auto-fix did not improve the code")
                return None, None
        
        return None, None
        
    except Exception as e:
        logger.error(f"Auto-fix failed: {e}")
        return None, None

# ==================== VERSION ROUTES ====================

@api_router.get("/projects/{project_id}/validate")
async def validate_project_code(project_id: str):
    """Validate the latest version's code and return any errors"""
    version = await database.get_latest_version(project_id)
    
    if not version or not version.get("files"):
        return {"valid": True, "errors": [], "message": "No code to validate"}
    
    errors = validate_react_code(version["files"])
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "message": "Code is valid" if not errors else f"Found {len(errors)} issue(s)"
    }

@api_router.post("/projects/{project_id}/fix")
async def fix_project_code(project_id: str):
    """Attempt to auto-fix the latest version's code errors"""
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    version = await database.get_latest_version(project_id)
    
    if not version or not version.get("files"):
        return {"fixed": False, "message": "No code to fix"}
    
    errors = validate_react_code(version["files"])
    if not errors:
        return {"fixed": False, "message": "No errors to fix"}
    
    # Attempt auto-fix
    fixed_files, fix_summary = await auto_fix_code(
        version["files"], 
        errors, 
        project.get("summary", "")
    )
    
    if fixed_files:
        # Create new version with fixed code
        new_version_number = version["version_number"] + 1
        new_version = Version(
            project_id=project_id,
            version_number=new_version_number,
            prompt="Auto-fix: " + fix_summary,
            files=[VersionFile(**f) for f in fixed_files],
            status="success",
            delta_plan={"summary": fix_summary, "auto_fixed": True}
        )
        await database.create_version(new_version.model_dump())
        
        # Update project
        await database.update_project(project_id, {
            "current_version": new_version_number,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        
        # Add chat message
        fix_msg = ChatMessage(
            project_id=project_id,
            role="assistant",
            content=f"🔧 Auto-fixed: {fix_summary}"
        )
        await database.create_message(fix_msg.model_dump())
        
        return {
            "fixed": True,
            "message": fix_summary,
            "new_version": new_version_number,
            "files": fixed_files
        }
    
    return {"fixed": False, "message": "Could not auto-fix the errors"}

@api_router.get("/projects/{project_id}/versions", response_model=List[Version])
async def get_versions(project_id: str):
    versions = await database.get_versions(project_id)
    return versions

@api_router.get("/projects/{project_id}/versions/latest")
async def get_latest_version(project_id: str):
    version = await database.get_latest_version(project_id)
    if not version:
        return {"version": None, "files": []}
    return version

# ==================== PROMPT ANALYSIS ====================

@api_router.post("/projects/{project_id}/analyze")
async def analyze_prompt(project_id: str, request: PromptRequest):
    """Analyze a prompt and determine if clarification is needed"""
    
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if this is an update (existing code) or new generation
    latest_version = await database.get_latest_version(project_id)
    is_update = latest_version and latest_version.get("files")
    
    # For updates, we generally don't need clarification
    if is_update:
        return {
            "needs_clarification": False,
            "message": "Ready to update existing code"
        }
    
    # Analyze the prompt
    messages = [
        {"role": "system", "content": CLARIFICATION_PROMPT.replace("{prompt}", request.prompt)},
        {"role": "user", "content": f"Analyze this request: {request.prompt}"}
    ]
    
    try:
        response = await call_openrouter(messages)
        content = response["choices"][0]["message"]["content"]
        
        # Parse response
        try:
            result = json.loads(content, strict=False)
        except json.JSONDecodeError:
            # Try to extract JSON
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                result = json.loads(json_match.group(), strict=False)
            else:
                result = {"needs_clarification": False}
        
        return result
        
    except Exception as e:
        logger.error(f"Prompt analysis error: {e}")
        # On error, proceed without clarification
        return {"needs_clarification": False}

class ClarificationResponse(BaseModel):
    original_prompt: str
    answers: Dict[str, str]  # question_id -> answer

@api_router.post("/projects/{project_id}/generate-with-context")
async def generate_with_context(project_id: str, data: ClarificationResponse):
    """Generate code with additional context from clarification answers"""
    
    # Build enhanced prompt from original + answers
    enhanced_prompt = data.original_prompt + "\n\nAdditional context:\n"
    for q_id, answer in data.answers.items():
        enhanced_prompt += f"- {answer}\n"
    
    # Use the regular generate endpoint logic
    request = PromptRequest(prompt=enhanced_prompt)
    
    # Forward to streaming generation
    return await generate_code_stream(project_id, request)

# ==================== CHAT ROUTES ====================

@api_router.get("/projects/{project_id}/messages", response_model=List[ChatMessage])
async def get_messages(project_id: str):
    messages = await database.get_messages(project_id)
    return messages

@api_router.post("/projects/{project_id}/messages")
async def add_message(project_id: str, data: dict):
    message = ChatMessage(
        project_id=project_id,
        role=data.get("role", "user"),
        content=data.get("content", "")
    )
    doc = message.model_dump()
    await database.create_message(doc)
    return message

# ==================== CODE GENERATION ====================

@api_router.post("/projects/{project_id}/generate")
async def generate_code(project_id: str, request: PromptRequest):
    """Generate or update code based on user prompt"""
    
    # Get project
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Save user message
    user_msg = ChatMessage(project_id=project_id, role="user", content=request.prompt)
    await database.create_message(user_msg.model_dump())
    
    # Get latest successful version
    latest_version = await database.get_latest_version(project_id)
    
    new_version_number = (latest_version["version_number"] + 1) if latest_version else 1
    
    # Check if Supabase is connected for full-stack generation
    is_fullstack = project.get("supabase_connected", False)
    supabase_url = project.get("supabase_url", "")
    
    try:
        if latest_version and latest_version.get("files"):
            # UPDATE existing code
            current_code = ""
            for f in latest_version["files"]:
                file_type = f.get("file_type", "frontend")
                current_code += f"// File: {f['path']} (type: {file_type})\n{f['content']}\n\n"
            
            if is_fullstack:
                # Full-stack update
                system_content = FULLSTACK_UPDATE_PROMPT.replace("{supabase_url}", supabase_url).replace("{current_code}", current_code).replace("{user_request}", request.prompt)
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Update the full-stack application: {request.prompt}"}
                ]
            else:
                # Frontend-only update
                system_content = UPDATE_SYSTEM_PROMPT.replace("{current_code}", current_code).replace("{user_request}", request.prompt)
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Update the code based on this request: {request.prompt}"}
                ]
        else:
            if is_fullstack:
                # New full-stack app
                system_content = FULLSTACK_SYSTEM_PROMPT.replace("{supabase_url}", supabase_url)
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Create a full-stack application with Supabase backend: {request.prompt}"}
                ]
            else:
                # New frontend-only app
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Create a React application: {request.prompt}"}
                ]
        
        # Call LLM
        response = await call_openrouter(messages)
        
        # Parse response
        content = response["choices"][0]["message"]["content"]
        logger.info(f"LLM response length: {len(content)}")
        logger.info(f"LLM response preview: {content[:300]}")
        
        # Extract JSON from response - use a robust approach
        result = None
        import re
        
        try:
            # Method 1: Try direct JSON parse of the whole response (with strict=False for newlines)
            try:
                result = json.loads(content, strict=False)
                logger.info("Direct JSON parse successful")
            except json.JSONDecodeError:
                pass
            
            # Method 2: Try to find JSON in markdown code blocks
            if result is None:
                code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
                if code_block_match:
                    try:
                        json_content = code_block_match.group(1).strip()
                        result = json.loads(json_content, strict=False)
                        logger.info("Parsed JSON from code block")
                    except json.JSONDecodeError as e:
                        logger.warning(f"JSON block parse failed: {e}")
            
            # Method 3: Find JSON object by looking for {"files"
            if result is None:
                json_starts = [m.start() for m in re.finditer(r'\{\s*"files"', content)]
                if json_starts:
                    for start_idx in json_starts:
                        try:
                            # Find balanced braces
                            depth = 0
                            in_string = False
                            escape = False
                            end_idx = start_idx
                            
                            for i, c in enumerate(content[start_idx:], start_idx):
                                if escape:
                                    escape = False
                                    continue
                                if c == '\\' and in_string:
                                    escape = True
                                    continue
                                if c == '"' and not escape:
                                    in_string = not in_string
                                    continue
                                if not in_string:
                                    if c == '{':
                                        depth += 1
                                    elif c == '}':
                                        depth -= 1
                                        if depth == 0:
                                            end_idx = i + 1
                                            break
                            
                            if end_idx > start_idx:
                                json_str = content[start_idx:end_idx]
                                result = json.loads(json_str, strict=False)
                                logger.info(f"Parsed JSON using brace matching")
                                break
                        except json.JSONDecodeError as e:
                            logger.warning(f"Brace matching JSON parse failed: {e}")
                            continue
            
            if result is None:
                raise ValueError("Could not parse JSON from response")
                
        except Exception as e:
            logger.warning(f"All JSON parse methods failed: {e}, extracting code from content")
            # Fallback: extract code from markdown or use raw content
            code_match = re.search(r'```(?:jsx?|tsx?|javascript|typescript)?\s*([\s\S]*?)\s*```', content)
            if code_match:
                code_content = code_match.group(1).strip()
                logger.info("Extracted code from markdown block")
            else:
                code_content = content
                logger.info("Using raw content as code")
            result = {
                "files": [{"path": "App.jsx", "content": code_content}],
                "summary": "Generated code"
            }
        
        files = result.get("files", [])
        summary = result.get("summary", "")
        
        logger.info(f"Parsed result - files count: {len(files)}, summary: {summary[:50] if summary else 'N/A'}")
        
        if not files:
            raise ValueError("No files in parsed result")
        
        # Check if we only got 1 file and the content looks like it has embedded JSON with multiple files
        # This handles cases where JSON parsing partially failed
        if len(files) == 1 and files[0].get("content", "").startswith("```"):
            content_check = files[0]["content"]
            # Try to extract JSON from markdown in the content
            json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?"files"[\s\S]*?\})\s*```', content_check)
            if json_match:
                try:
                    extracted = json.loads(json_match.group(1), strict=False)
                    if extracted.get("files") and len(extracted["files"]) > 1:
                        files = extracted["files"]
                        summary = extracted.get("summary", summary)
                        logger.info(f"Extracted {len(files)} files from embedded JSON")
                except:
                    pass
        
        # Validate files structure and fix file_type based on path
        for i, f in enumerate(files):
            if not isinstance(f, dict):
                raise ValueError(f"File {i} is not a dict: {type(f)}")
            if "path" not in f:
                raise ValueError(f"File {i} missing 'path': {f.keys()}")
            if "content" not in f:
                raise ValueError(f"File {i} missing 'content': {f.keys()}")
            
            # Auto-detect file_type based on path if not set correctly
            path = f.get("path", "")
            if ".sql" in path:
                f["file_type"] = "sql"
            elif "supabase/functions" in path or path.endswith(".ts"):
                f["file_type"] = "edge_function"
            elif not f.get("file_type"):
                f["file_type"] = "frontend"
            
            logger.info(f"File {i}: {f['path']} (type: {f.get('file_type')}, {len(f['content'])} chars)")
        
        # Validate code and auto-fix if needed
        validation_errors = validate_react_code(files)
        if validation_errors:
            logger.warning(f"Code validation errors found: {validation_errors}")
            # Attempt auto-fix
            fixed_files, fix_summary = await auto_fix_code(files, validation_errors, project.get("summary", ""))
            if fixed_files:
                files = fixed_files
                summary = f"{summary}. Auto-fixed: {fix_summary}"
                logger.info("Code auto-fixed successfully")
        
        # Create version
        version = Version(
            project_id=project_id,
            version_number=new_version_number,
            prompt=request.prompt,
            files=[VersionFile(**f) for f in files],
            status="success",
            delta_plan={"summary": summary, "changes": result.get("changes", [])}
        )
        await database.create_version(version.model_dump())
        
        # Update project
        await database.update_project(project_id, {
            "current_version": new_version_number,
            "summary": summary or project.get("summary", ""),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        
        # Save assistant message
        assistant_msg = ChatMessage(
            project_id=project_id,
            role="assistant",
            content=f"✓ {summary or 'Code generated successfully'}"
        )
        await database.create_message(assistant_msg.model_dump())
        
        return {
            "status": "success",
            "version": new_version_number,
            "files": [f.model_dump() for f in version.files],
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Generation error: {str(e)}")
        
        # Save error version
        version = Version(
            project_id=project_id,
            version_number=new_version_number,
            prompt=request.prompt,
            status="failed",
            delta_plan={"error": str(e)}
        )
        await database.create_version(version.model_dump())
        
        # Save error message
        error_msg = ChatMessage(
            project_id=project_id,
            role="assistant", 
            content=f"❌ Error: {str(e)}"
        )
        await database.create_message(error_msg.model_dump())
        
        raise HTTPException(status_code=500, detail=str(e))

# ==================== STREAMING GENERATION ====================

@api_router.post("/projects/{project_id}/generate/stream")
async def generate_code_stream(project_id: str, request: PromptRequest):
    """Generate code with streaming response for real-time updates"""
    
    # Get project
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Save user message
    user_msg = ChatMessage(project_id=project_id, role="user", content=request.prompt)
    await database.create_message(user_msg.model_dump())
    
    # Get latest successful version
    latest_version = await database.get_latest_version(project_id)
    new_version_number = (latest_version["version_number"] + 1) if latest_version else 1
    
    # Check if Supabase is connected for full-stack generation
    is_fullstack = project.get("supabase_connected", False)
    supabase_url = project.get("supabase_url", "")
    
    # Build messages based on project type
    if latest_version and latest_version.get("files"):
        current_code = ""
        for f in latest_version["files"]:
            file_type = f.get("file_type", "frontend")
            current_code += f"// File: {f['path']} (type: {file_type})\n{f['content']}\n\n"
        
        if is_fullstack:
            # Full-stack update
            system_content = FULLSTACK_UPDATE_PROMPT.replace("{supabase_url}", supabase_url).replace("{current_code}", current_code).replace("{user_request}", request.prompt)
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Update the full-stack application: {request.prompt}"}
            ]
        else:
            # Frontend-only update
            system_content = UPDATE_SYSTEM_PROMPT.replace("{current_code}", current_code).replace("{user_request}", request.prompt)
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Update the code based on this request: {request.prompt}"}
            ]
        is_update = True
    else:
        if is_fullstack:
            # New full-stack app
            system_content = FULLSTACK_SYSTEM_PROMPT.replace("{supabase_url}", supabase_url)
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Create a full-stack application with Supabase backend: {request.prompt}"}
            ]
        else:
            # New frontend-only app
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Create a React application: {request.prompt}"}
            ]
        is_update = False
    
    async def stream_generator():
        full_content = ""
        current_file = None
        files_detected = []
        
        try:
            # Send initial status based on project type
            yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing request...'})}\n\n"
            await asyncio.sleep(0.1)
            
            if is_fullstack:
                yield f"data: {json.dumps({'type': 'status', 'message': '🚀 Generating full-stack app (Frontend + Edge Functions + Database)...'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'status', 'message': 'Generating code structure...' if not is_update else 'Planning changes...'})}\n\n"
            
            # Stream from LLM
            async for chunk in call_openrouter_stream(messages):
                full_content += chunk
                
                # Detect file paths being written
                if '"path":' in chunk or '"path"' in full_content[-50:]:
                    # Try to extract current file being generated
                    import re
                    paths = re.findall(r'"path"\s*:\s*"([^"]+)"', full_content)
                    if paths and paths[-1] not in files_detected:
                        files_detected.append(paths[-1])
                        file_path = paths[-1]
                        # Show more context for full-stack apps
                        if is_fullstack:
                            if 'functions' in file_path:
                                yield f"data: {json.dumps({'type': 'status', 'message': f'⚡ Writing Edge Function: {file_path}...'})}\n\n"
                            elif '.sql' in file_path:
                                yield f"data: {json.dumps({'type': 'status', 'message': f'🗄️ Writing Database Migration: {file_path}...'})}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'status', 'message': f'📝 Writing {file_path}...'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'status', 'message': f'Writing {file_path}...'})}\n\n"
                
                # Send code chunk
                yield f"data: {json.dumps({'type': 'code', 'content': chunk})}\n\n"
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Processing generated code...'})}\n\n"
            
            # Parse the complete response
            result = None
            try:
                result = json.loads(full_content, strict=False)
            except json.JSONDecodeError:
                # Try to extract from markdown
                import re
                code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', full_content)
                if code_block_match:
                    try:
                        result = json.loads(code_block_match.group(1).strip(), strict=False)
                    except:
                        pass
                
                if not result:
                    # Find JSON by pattern
                    json_starts = [m.start() for m in re.finditer(r'\{\s*"files"', full_content)]
                    if json_starts:
                        for start_idx in json_starts:
                            depth = 0
                            in_string = False
                            escape = False
                            end_idx = start_idx
                            for i, c in enumerate(full_content[start_idx:], start_idx):
                                if escape:
                                    escape = False
                                    continue
                                if c == '\\' and in_string:
                                    escape = True
                                    continue
                                if c == '"' and not escape:
                                    in_string = not in_string
                                    continue
                                if not in_string:
                                    if c == '{':
                                        depth += 1
                                    elif c == '}':
                                        depth -= 1
                                        if depth == 0:
                                            end_idx = i + 1
                                            break
                            if end_idx > start_idx:
                                try:
                                    result = json.loads(full_content[start_idx:end_idx], strict=False)
                                    break
                                except:
                                    continue
            
            if not result:
                yield f"data: {json.dumps({'type': 'status', 'message': 'Extracting code from response...'})}\n\n"
                result = {
                    "files": [{"path": "App.jsx", "content": full_content}],
                    "summary": "Generated code"
                }
            
            files = result.get("files", [])
            summary = result.get("summary", "")
            
            # Auto-detect file_type based on path
            for f in files:
                path = f.get("path", "")
                if ".sql" in path:
                    f["file_type"] = "sql"
                elif "supabase/functions" in path or path.endswith(".ts"):
                    f["file_type"] = "edge_function"
                elif not f.get("file_type"):
                    f["file_type"] = "frontend"
            
            yield f"data: {json.dumps({'type': 'status', 'message': f'Validating {len(files)} file(s)...'})}\n\n"
            
            # Validate and potentially auto-fix
            validation_errors = validate_react_code(files)
            if validation_errors:
                yield f"data: {json.dumps({'type': 'status', 'message': 'Auto-fixing code issues...'})}\n\n"
                fixed_files, fix_summary = await auto_fix_code(files, validation_errors, project.get("summary", ""))
                if fixed_files:
                    files = fixed_files
                    summary = f"{summary}. Auto-fixed: {fix_summary}"
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Saving version...'})}\n\n"
            
            # Create version
            version = Version(
                project_id=project_id,
                version_number=new_version_number,
                prompt=request.prompt,
                files=[VersionFile(**f) for f in files],
                status="success",
                delta_plan={"summary": summary}
            )
            await database.create_version(version.model_dump())
            
            # Update project
            await database.update_project(project_id, {
                "current_version": new_version_number,
                "summary": summary or project.get("summary", ""),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Save assistant message
            assistant_msg = ChatMessage(
                project_id=project_id,
                role="assistant",
                content=f"✓ {summary or 'Code generated successfully'}"
            )
            await database.create_message(assistant_msg.model_dump())
            
            # Send final result
            yield f"data: {json.dumps({'type': 'complete', 'version': new_version_number, 'files': files, 'summary': summary})}\n\n"
            
        except Exception as e:
            logger.error(f"Stream generation error: {str(e)}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            
            # Save error
            error_msg = ChatMessage(
                project_id=project_id,
                role="assistant", 
                content=f"❌ Error: {str(e)}"
            )
            await database.create_message(error_msg.model_dump())
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# ==================== PREVIEW GENERATION ====================

@api_router.get("/projects/{project_id}/preview")
async def get_preview_html(project_id: str):
    """Generate HTML for iframe preview (returns JSON with html field)"""
    
    # Get project for Supabase credentials
    project = await database.get_project(project_id)
    
    version = await database.get_latest_version(project_id)
    
    if not version or not version.get("files"):
        # Return placeholder
        return {"html": get_placeholder_html()}
    
    # Get Supabase config if connected
    supabase_config = None
    if project and project.get("supabase_connected"):
        supabase_config = {
            "url": project.get("supabase_url", ""),
            "anon_key": project.get("supabase_anon_key", "")
        }
    
    # Pass all files and supabase config to the preview generator
    html = generate_preview_html_multifile(version["files"], supabase_config)
    return {"html": html}

@api_router.get("/projects/{project_id}/preview/live")
async def get_preview_live(project_id: str):
    """Serve the preview as a standalone HTML page (for opening in new tab)"""
    from fastapi.responses import HTMLResponse
    
    # Get project for Supabase credentials
    project = await database.get_project(project_id)
    
    version = await database.get_latest_version(project_id)
    
    if not version or not version.get("files"):
        return HTMLResponse(content=get_placeholder_html(), status_code=200)
    
    # Get Supabase config if connected
    supabase_config = None
    if project and project.get("supabase_connected"):
        supabase_config = {
            "url": project.get("supabase_url", ""),
            "anon_key": project.get("supabase_anon_key", "")
        }
    
    # Generate and return HTML directly
    html = generate_preview_html_multifile(version["files"], supabase_config)
    return HTMLResponse(content=html, status_code=200)

def get_placeholder_html():
    return """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { font-family: 'Inter', sans-serif; }
    </style>
</head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
    <div class="text-center p-8">
        <div class="w-16 h-16 mx-auto mb-4 rounded-xl bg-blue-100 flex items-center justify-center">
            <svg class="w-8 h-8 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path>
            </svg>
        </div>
        <h2 class="text-xl font-semibold text-gray-800 mb-2">Ready to Build</h2>
        <p class="text-gray-500">Describe what you want to create and I'll generate the code</p>
    </div>
</body>
</html>"""

def clean_component_code(code: str) -> str:
    """Clean a single component's code for embedding"""
    import re
    
    # Remove import statements
    cleaned = re.sub(r'^import\s+.*?[\'"].*?[\'"];?\s*$', '', code, flags=re.MULTILINE)
    cleaned = re.sub(r'^import\s+\{[^}]*\}\s+from\s+[\'"].*?[\'"];?\s*$', '', cleaned, flags=re.MULTILINE)
    
    # Remove export statements but keep the content
    cleaned = re.sub(r'^export\s+default\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^export\s+', '', cleaned, flags=re.MULTILINE)
    
    # Escape script closing tags
    cleaned = cleaned.replace("</script>", "<\\/script>")
    
    return cleaned.strip()

def generate_preview_html_multifile(files: list, supabase_config: dict = None) -> str:
    """Generate HTML with multiple React components for preview"""
    
    # Check if this is a full-stack app (has Supabase files)
    has_supabase = any('supabase' in f.get('path', '').lower() or '@supabase' in f.get('content', '') for f in files)
    
    # Sort files: components first, then App.jsx last (so it can use components)
    # Skip non-frontend files (edge functions, sql) for preview
    sorted_files = []
    app_file = None
    
    for f in files:
        # Skip non-frontend files
        file_type = f.get("file_type", "frontend")
        if file_type in ["edge_function", "sql"]:
            continue
        if f.get("path", "").endswith(".ts") or f.get("path", "").endswith(".sql"):
            continue
            
        if f["path"] == "App.jsx" or f["path"].endswith("/App.jsx"):
            app_file = f
        else:
            sorted_files.append(f)
    
    if app_file:
        sorted_files.append(app_file)
    elif files:
        # If no App.jsx found, use frontend files only
        sorted_files = [f for f in files if f.get("file_type", "frontend") == "frontend"]
    
    # Build all component code
    all_code_parts = []
    for f in sorted_files:
        cleaned = clean_component_code(f["content"])
        # Add a comment marker for debugging
        all_code_parts.append(f"// === File: {f['path']} ===\n{cleaned}")
    
    all_code = "\n\n".join(all_code_parts)
    
    # Add Supabase library and config if needed
    supabase_script = ""
    supabase_init = ""
    if has_supabase or supabase_config:
        supabase_script = '<script src="https://unpkg.com/@supabase/supabase-js@2"></script>'
        
        # Get actual credentials or use placeholders
        sb_url = supabase_config.get("url", "") if supabase_config else ""
        sb_key = supabase_config.get("anon_key", "") if supabase_config else ""
        
        supabase_init = f"""
        // Supabase client setup for preview
        const {{ createClient }} = supabase;
        
        // Inject Supabase credentials for preview
        const PREVIEW_SUPABASE_URL = '{sb_url}';
        const PREVIEW_SUPABASE_KEY = '{sb_key}';
        
        // Mock process.env for preview
        if (typeof process === 'undefined') {{
            window.process = {{ env: {{
                REACT_APP_SUPABASE_URL: PREVIEW_SUPABASE_URL,
                REACT_APP_SUPABASE_ANON_KEY: PREVIEW_SUPABASE_KEY
            }} }};
        }}
        """
    
    # Build HTML template with string concatenation to avoid f-string brace issues
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    """ + supabase_script + """
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; }
        #root { min-height: 100vh; }
        .error-boundary { 
            padding: 20px; 
            background: #fef2f2; 
            color: #dc2626;
            border-radius: 8px;
            margin: 20px;
        }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const { useState, useEffect, useRef, useCallback, useMemo, useContext, createContext, useReducer } = React;
        
        """ + supabase_init + """
        
        // Error Boundary Component
        class ErrorBoundary extends React.Component {
            constructor(props) {
                super(props);
                this.state = { hasError: false, error: null };
            }
            static getDerivedStateFromError(error) {
                return { hasError: true, error };
            }
            render() {
                if (this.state.hasError) {
                    return (
                        <div className="error-boundary">
                            <h3 className="font-semibold mb-2">Something went wrong</h3>
                            <pre className="text-sm overflow-auto">{this.state.error?.message}</pre>
                        </div>
                    );
                }
                return this.props.children;
            }
        }
        
        // User's Generated Components and Code
        """ + all_code + """
        
        // Render
        const container = document.getElementById('root');
        const root = ReactDOM.createRoot(container);
        root.render(
            <ErrorBoundary>
                <App />
            </ErrorBoundary>
        );
    </script>
</body>
</html>"""
    
    return html_template

# Include router and middleware
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_client():
    global database
    database = get_database()
    await database.init()
    logger.info(f"Database initialized: {os.environ.get('DB_TYPE', 'mongodb')}")

@app.on_event("shutdown")
async def shutdown_db_client():
    if database:
        await database.close()

