from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
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

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

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
    """Call OpenRouter API"""
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
        "max_tokens": 8000,
        "temperature": 0.7
    }
    
    async with httpx.AsyncClient(timeout=120.0) as http_client:
        response = await http_client.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers)
        if response.status_code != 200:
            logger.error(f"OpenRouter error: {response.text}")
            raise HTTPException(status_code=500, detail=f"LLM error: {response.text}")
        return response.json()

# ==================== CODE GENERATION PROMPTS ====================

SYSTEM_PROMPT = """You are an expert React developer. You generate clean, modern React code using Tailwind CSS.

RULES:
1. Generate ONLY valid React JSX code
2. Use Tailwind CSS for all styling
3. Use modern React patterns (hooks, functional components)
4. Make components responsive and visually appealing
5. Include proper error handling
6. Use semantic HTML
7. For complex apps, split code into multiple components/files

OUTPUT FORMAT:
Return a JSON object with this exact structure:
{
  "files": [
    {
      "path": "App.jsx",
      "content": "// Main App component - imports and uses other components"
    },
    {
      "path": "components/Button.jsx",
      "content": "// Reusable Button component"
    }
  ],
  "summary": "Brief description of what was built"
}

FILE ORGANIZATION:
- App.jsx: Main entry point (REQUIRED)
- components/*.jsx: Reusable UI components
- hooks/*.jsx: Custom React hooks
- utils/*.js: Utility functions

IMPORTANT:
- The main entry file MUST be named "App.jsx"
- Components can import other components using: import ComponentName from './components/ComponentName'
- Do not use external npm packages except React (available globally)
- Use inline Tailwind styles
- Make the UI modern, clean, and professional
- For simple apps, a single App.jsx is fine
- For complex apps with multiple features, create separate component files"""

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
    return {"message": "App Builder API v1"}

@api_router.post("/projects", response_model=Project)
async def create_project(data: ProjectCreate):
    project = Project(name=data.name, description=data.description)
    doc = project.model_dump()
    await db.projects.insert_one(doc)
    return project

@api_router.get("/projects", response_model=List[Project])
async def get_projects():
    projects = await db.projects.find({}, {"_id": 0}).to_list(100)
    return projects

@api_router.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    result = await db.projects.delete_one({"id": project_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Project not found")
    # Also delete related data
    await db.versions.delete_many({"project_id": project_id})
    await db.chat_messages.delete_many({"project_id": project_id})
    return {"status": "deleted"}

# ==================== VERSION ROUTES ====================

@api_router.get("/projects/{project_id}/versions", response_model=List[Version])
async def get_versions(project_id: str):
    versions = await db.versions.find({"project_id": project_id}, {"_id": 0}).sort("version_number", -1).to_list(100)
    return versions

@api_router.get("/projects/{project_id}/versions/latest")
async def get_latest_version(project_id: str):
    version = await db.versions.find_one(
        {"project_id": project_id, "status": "success"},
        {"_id": 0},
        sort=[("version_number", -1)]
    )
    if not version:
        return {"version": None, "files": []}
    return version

# ==================== CHAT ROUTES ====================

@api_router.get("/projects/{project_id}/messages", response_model=List[ChatMessage])
async def get_messages(project_id: str):
    messages = await db.chat_messages.find({"project_id": project_id}, {"_id": 0}).sort("created_at", 1).to_list(1000)
    return messages

@api_router.post("/projects/{project_id}/messages")
async def add_message(project_id: str, data: dict):
    message = ChatMessage(
        project_id=project_id,
        role=data.get("role", "user"),
        content=data.get("content", "")
    )
    doc = message.model_dump()
    await db.chat_messages.insert_one(doc)
    return message

# ==================== CODE GENERATION ====================

@api_router.post("/projects/{project_id}/generate")
async def generate_code(project_id: str, request: PromptRequest):
    """Generate or update code based on user prompt"""
    
    # Get project
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Save user message
    user_msg = ChatMessage(project_id=project_id, role="user", content=request.prompt)
    await db.chat_messages.insert_one(user_msg.model_dump())
    
    # Get latest successful version
    latest_version = await db.versions.find_one(
        {"project_id": project_id, "status": "success"},
        {"_id": 0},
        sort=[("version_number", -1)]
    )
    
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
        await db.versions.insert_one(version.model_dump())
        
        # Update project
        await db.projects.update_one(
            {"id": project_id},
            {"$set": {
                "current_version": new_version_number,
                "summary": summary or project.get("summary", ""),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Save assistant message
        assistant_msg = ChatMessage(
            project_id=project_id,
            role="assistant",
            content=f"✓ {summary or 'Code generated successfully'}"
        )
        await db.chat_messages.insert_one(assistant_msg.model_dump())
        
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
        await db.versions.insert_one(version.model_dump())
        
        # Save error message
        error_msg = ChatMessage(
            project_id=project_id,
            role="assistant", 
            content=f"❌ Error: {str(e)}"
        )
        await db.chat_messages.insert_one(error_msg.model_dump())
        
        raise HTTPException(status_code=500, detail=str(e))

# ==================== PREVIEW GENERATION ====================

@api_router.get("/projects/{project_id}/preview")
async def get_preview_html(project_id: str):
    """Generate HTML for iframe preview"""
    
    version = await db.versions.find_one(
        {"project_id": project_id, "status": "success"},
        {"_id": 0},
        sort=[("version_number", -1)]
    )
    
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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
