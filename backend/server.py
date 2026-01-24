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

class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    summary: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_version: int = 0

class VersionFile(BaseModel):
    path: str
    content: str

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

class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    role: str  # user or assistant
    content: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PromptRequest(BaseModel):
    prompt: str

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

SYSTEM_PROMPT = """You are an expert React developer. Generate multi-file React applications using Tailwind CSS.

CRITICAL OUTPUT RULES:
1. Return ONLY raw JSON - NO markdown code blocks (no ```)
2. ALWAYS create 4-8 separate component files
3. Never put all code in a single file

REQUIRED JSON FORMAT:
{"files":[{"path":"App.jsx","content":"code here"},{"path":"components/Header.jsx","content":"code here"}],"summary":"description"}

FILE STRUCTURE (REQUIRED):
- App.jsx: Main entry - imports and composes components only
- components/Header.jsx: Header/navbar
- components/Sidebar.jsx: Sidebar navigation (if applicable)
- components/Feed.jsx or components/Main.jsx: Main content area
- components/Card.jsx: Reusable card component
- components/Footer.jsx: Footer component

CODE RULES:
1. Use Tailwind CSS for all styling
2. Use functional components with hooks
3. Each component exports default function
4. App.jsx imports all components using: import Header from './components/Header'
5. React is available globally - no need to import React
6. Make UI modern, professional, responsive

EXAMPLE OUTPUT:
{"files":[{"path":"App.jsx","content":"import Header from './components/Header';\\nimport Feed from './components/Feed';\\n\\nfunction App() {\\n  return (\\n    <div className=\\"min-h-screen bg-gray-100\\">\\n      <Header />\\n      <Feed />\\n    </div>\\n  );\\n}\\n\\nexport default App;"},{"path":"components/Header.jsx","content":"function Header() {\\n  return <header className=\\"bg-white shadow p-4\\">Header</header>;\\n}\\nexport default Header;"},{"path":"components/Feed.jsx","content":"function Feed() {\\n  return <main className=\\"p-4\\">Content</main>;\\n}\\nexport default Feed;"}],"summary":"Created app with header and feed"}"""

UPDATE_SYSTEM_PROMPT = """You are an expert React developer. You update existing React code based on user requests.

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
    
    try:
        if latest_version and latest_version.get("files"):
            # UPDATE existing code
            current_code = ""
            for f in latest_version["files"]:
                current_code += f"// File: {f['path']}\n{f['content']}\n\n"
            
            # Use string replacement instead of .format() to avoid issues with { } in code
            system_content = UPDATE_SYSTEM_PROMPT.replace("{current_code}", current_code).replace("{user_request}", request.prompt)
            
            messages = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Update the code based on this request: {request.prompt}"}
            ]
        else:
            # CREATE new code
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
        
        # Validate files structure
        for i, f in enumerate(files):
            if not isinstance(f, dict):
                raise ValueError(f"File {i} is not a dict: {type(f)}")
            if "path" not in f:
                raise ValueError(f"File {i} missing 'path': {f.keys()}")
            if "content" not in f:
                raise ValueError(f"File {i} missing 'content': {f.keys()}")
            logger.info(f"File {i}: {f['path']} ({len(f['content'])} chars)")
        
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
    
    # Build messages
    if latest_version and latest_version.get("files"):
        current_code = ""
        for f in latest_version["files"]:
            current_code += f"// File: {f['path']}\n{f['content']}\n\n"
        system_content = UPDATE_SYSTEM_PROMPT.replace("{current_code}", current_code).replace("{user_request}", request.prompt)
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"Update the code based on this request: {request.prompt}"}
        ]
        is_update = True
    else:
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
            # Send initial status
            yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing request...'})}\n\n"
            await asyncio.sleep(0.1)
            
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
                        yield f"data: {json.dumps({'type': 'status', 'message': f'Writing {paths[-1]}...'})}\n\n"
                
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
    """Generate HTML for iframe preview"""
    
    version = await database.get_latest_version(project_id)
    
    if not version or not version.get("files"):
        # Return placeholder
        return {"html": get_placeholder_html()}
    
    # Pass all files to the preview generator
    html = generate_preview_html_multifile(version["files"])
    return {"html": html}

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

def generate_preview_html_multifile(files: list) -> str:
    """Generate HTML with multiple React components for preview"""
    
    # Sort files: components first, then App.jsx last (so it can use components)
    sorted_files = []
    app_file = None
    
    for f in files:
        if f["path"] == "App.jsx" or f["path"].endswith("/App.jsx"):
            app_file = f
        else:
            sorted_files.append(f)
    
    if app_file:
        sorted_files.append(app_file)
    elif files:
        sorted_files = files
    
    # Build all component code
    all_code_parts = []
    for f in sorted_files:
        cleaned = clean_component_code(f["content"])
        # Add a comment marker for debugging
        all_code_parts.append(f"// === File: {f['path']} ===\n{cleaned}")
    
    all_code = "\n\n".join(all_code_parts)
    
    # Build HTML template with string concatenation to avoid f-string brace issues
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
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

