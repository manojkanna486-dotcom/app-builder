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

async def call_openrouter(messages: List[Dict], stream: bool = False):
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
        "stream": stream,
        "max_tokens": 8000,
        "temperature": 0.7
    }
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        if stream:
            async with client.stream("POST", f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data != "[DONE]":
                            yield data
        else:
            response = await client.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, headers=headers)
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

OUTPUT FORMAT:
Return a JSON object with this exact structure:
{
  "files": [
    {
      "path": "App.jsx",
      "content": "// Full React component code here"
    }
  ],
  "summary": "Brief description of what was built"
}

IMPORTANT:
- The main entry file MUST be named "App.jsx"
- All code must be self-contained in the files provided
- Do not use external imports except React (which is available globally)
- Use inline Tailwind styles, no external CSS files needed
- Make the UI modern, clean, and professional"""

UPDATE_SYSTEM_PROMPT = """You are an expert React developer. You update existing React code based on user requests.

CURRENT CODE:
{current_code}

USER REQUEST:
{user_request}

RULES:
1. ONLY modify what the user asked for
2. Keep all existing functionality intact
3. Maintain the same code structure and patterns
4. Use Tailwind CSS for styling
5. Return the COMPLETE updated code

OUTPUT FORMAT:
Return a JSON object with this exact structure:
{
  "files": [
    {
      "path": "App.jsx", 
      "content": "// Complete updated React component code"
    }
  ],
  "summary": "Brief description of changes made",
  "changes": ["List of specific changes made"]
}"""

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
            
            messages = [
                {"role": "system", "content": UPDATE_SYSTEM_PROMPT.format(
                    current_code=current_code,
                    user_request=request.prompt
                )},
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
        
        # Extract JSON from response
        try:
            # Try to find JSON in the response
            json_start = content.find("{")
            json_end = content.rfind("}") + 1
            if json_start != -1 and json_end > json_start:
                json_str = content[json_start:json_end]
                result = json.loads(json_str)
            else:
                raise ValueError("No JSON found")
        except json.JSONDecodeError:
            # If JSON parsing fails, create a simple response
            result = {
                "files": [{"path": "App.jsx", "content": content}],
                "summary": "Generated code"
            }
        
        files = result.get("files", [])
        summary = result.get("summary", "")
        
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
    
    # Get App.jsx content
    app_content = ""
    for f in version["files"]:
        if f["path"] == "App.jsx" or f["path"].endswith("App.jsx"):
            app_content = f["content"]
            break
    
    if not app_content:
        app_content = version["files"][0]["content"] if version["files"] else ""
    
    html = generate_preview_html(app_content)
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

def generate_preview_html(react_code: str) -> str:
    """Generate HTML with embedded React code for preview"""
    
    # Escape backticks and special chars for embedding in template literal
    escaped_code = react_code.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    
    return f"""<!DOCTYPE html>
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
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', sans-serif; }}
        #root {{ min-height: 100vh; }}
        .error-boundary {{ 
            padding: 20px; 
            background: #fef2f2; 
            color: #dc2626;
            border-radius: 8px;
            margin: 20px;
        }}
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const {{ useState, useEffect, useRef, useCallback, useMemo }} = React;
        
        // Error Boundary Component
        class ErrorBoundary extends React.Component {{
            constructor(props) {{
                super(props);
                this.state = {{ hasError: false, error: null }};
            }}
            static getDerivedStateFromError(error) {{
                return {{ hasError: true, error }};
            }}
            render() {{
                if (this.state.hasError) {{
                    return (
                        <div className="error-boundary">
                            <h3 className="font-semibold mb-2">Something went wrong</h3>
                            <pre className="text-sm overflow-auto">{{this.state.error?.message}}</pre>
                        </div>
                    );
                }}
                return this.props.children;
            }}
        }}
        
        // User's Generated Code
        {escaped_code}
        
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
