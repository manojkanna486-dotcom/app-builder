from fastapi import FastAPI, APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
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
import zipfile
import io
import secrets
import hashlib
import base64
import re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Database abstraction - supports MongoDB and Supabase PostgreSQL
from database import get_database, DatabaseInterface
database: DatabaseInterface = None

# Testing Agent for generated apps
from testing_agent import TestingAgent, MAX_RETRY_ATTEMPTS

# Clarification Agent for requirement extraction
from clarification_agent import ClarificationAgent, RESPONSIVE_REQUIREMENTS

# OpenRouter config
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Initialize agents
testing_agent = None
clarification_agent = None

# Supabase OAuth config
SUPABASE_OAUTH_CLIENT_ID = os.environ.get('SUPABASE_OAUTH_CLIENT_ID')
SUPABASE_OAUTH_CLIENT_SECRET = os.environ.get('SUPABASE_OAUTH_CLIENT_SECRET')
SUPABASE_OAUTH_REDIRECT_URI = os.environ.get('SUPABASE_OAUTH_REDIRECT_URI')
SUPABASE_OAUTH_AUTH_URL = "https://api.supabase.com/v1/oauth/authorize"
SUPABASE_OAUTH_TOKEN_URL = "https://api.supabase.com/v1/oauth/token"
SUPABASE_MANAGEMENT_API = "https://api.supabase.com/v1"

# In-memory store for OAuth PKCE state only (short-lived, needed during OAuth flow)
# Tokens are now stored in database for persistence
oauth_pkce_states = {}

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== OAUTH TOKEN HELPERS ====================

async def get_valid_oauth_token(token_state: str) -> Optional[dict]:
    """
    Get OAuth token from database and refresh if expired.
    Returns token_data with valid access_token or None if invalid.
    """
    token_data = await database.get_oauth_token(token_state)
    if not token_data:
        return None
    
    # Check if token is expired (Supabase tokens expire in 1 hour)
    created_at = token_data.get("created_at", "")
    if created_at:
        try:
            created_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - created_time).total_seconds()
            
            # If token is more than 50 minutes old, refresh it
            if age_seconds > 3000 and token_data.get("refresh_token"):
                refreshed = await refresh_oauth_token(token_state, token_data["refresh_token"])
                if refreshed:
                    return refreshed
        except Exception as e:
            logger.warning(f"Error checking token age: {e}")
    
    return token_data

async def refresh_oauth_token(token_state: str, refresh_token: str) -> Optional[dict]:
    """Refresh an expired OAuth token using the refresh_token"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                SUPABASE_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": SUPABASE_OAUTH_CLIENT_ID,
                    "client_secret": SUPABASE_OAUTH_CLIENT_SECRET,
                }
            )
            
            if response.status_code in [200, 201]:
                tokens = response.json()
                new_token_data = {
                    "access_token": tokens.get("access_token"),
                    "refresh_token": tokens.get("refresh_token", refresh_token),
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                
                # Update in database
                await database.store_oauth_token(token_state, new_token_data)
                logger.info(f"Successfully refreshed OAuth token for state: {token_state}")
                return new_token_data
            else:
                logger.error(f"Failed to refresh token: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        logger.error(f"Error refreshing OAuth token: {e}")
        return None

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
    # OAuth-added fields for project isolation
    supabase_project_ref: Optional[str] = None
    supabase_project_name: Optional[str] = None
    supabase_region: Optional[str] = None
    supabase_connected_at: Optional[str] = None

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
    enable_testing: bool = True  # Enable auto-testing by default
    max_test_retries: int = 3    # Max retry attempts
    confirmed_requirements: Optional[Dict] = None  # Pre-confirmed requirements from clarification
    user_answers: Optional[Dict[str, str]] = None  # Answers to clarifying questions

class GenerationTask(BaseModel):
    """Background generation task tracking"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    prompt: str
    status: str = "pending"  # pending, analyzing, generating, validating, migrating, deploying, completed, failed
    progress: int = 0  # 0-100
    current_step: str = ""
    error: Optional[str] = None
    version_number: Optional[int] = None
    files: Optional[List[Dict]] = None
    summary: Optional[str] = None
    migration_result: Optional[Dict] = None
    deploy_result: Optional[Dict] = None
    test_results: Optional[Dict] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None

# In-memory store for active generation tasks (for quick lookups)
active_generation_tasks: Dict[str, asyncio.Task] = {}

class ClarifyRequest(BaseModel):
    prompt: str

class ConfirmRequirementsRequest(BaseModel):
    analysis: Dict
    user_answers: Dict[str, str]

class SupabaseConnectRequest(BaseModel):
    url: str
    anon_key: str
    service_role_key: Optional[str] = None

class VercelDeployRequest(BaseModel):
    vercel_token: str
    project_name: Optional[str] = None

class SupabaseProjectCreate(BaseModel):
    name: str
    organization_id: str
    db_pass: str
    region: str = "us-east-1"
    
    @property
    def validate_db_pass(self):
        """Validate database password meets Supabase requirements"""
        if len(self.db_pass) < 8:
            return False, "Password must be at least 8 characters"
        return True, ""

# ==================== SUPABASE OAUTH ====================

def generate_pkce_pair():
    """Generate PKCE code verifier and challenge"""
    code_verifier = secrets.token_urlsafe(32)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip('=')
    return code_verifier, code_challenge

@api_router.get("/auth/supabase/login")
async def supabase_oauth_login(project_id: str = Query(..., description="App Builder project ID to connect")):
    """Initiate Supabase OAuth flow"""
    if not SUPABASE_OAUTH_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Supabase OAuth not configured")
    
    # Generate state and PKCE
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce_pair()
    
    # Store state with project_id and code_verifier (short-lived, in-memory is fine)
    oauth_pkce_states[state] = {
        "project_id": project_id,
        "code_verifier": code_verifier,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Build authorization URL with required scopes
    # Scopes needed: projects:read, organizations:read
    from urllib.parse import urlencode
    
    params = {
        "client_id": SUPABASE_OAUTH_CLIENT_ID,
        "redirect_uri": SUPABASE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "projects:read organizations:read",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256"
    }
    
    auth_url = f"{SUPABASE_OAUTH_AUTH_URL}?{urlencode(params)}"
    logger.info(f"Redirecting to Supabase OAuth: {auth_url[:150]}...")
    
    return RedirectResponse(url=auth_url)

@api_router.get("/auth/supabase/callback")
async def supabase_oauth_callback(code: str = Query(...), state: str = Query(...)):
    """Handle Supabase OAuth callback"""
    
    # Verify state (PKCE states are short-lived, in-memory)
    if state not in oauth_pkce_states:
        logger.error(f"Invalid OAuth state: {state}")
        # Redirect to frontend with error
        return RedirectResponse(url="/?error=invalid_state")
    
    state_data = oauth_pkce_states.pop(state)
    project_id = state_data["project_id"]
    code_verifier = state_data["code_verifier"]
    
    try:
        # Exchange code for token
        async with httpx.AsyncClient(timeout=30.0) as client:
            token_response = await client.post(
                SUPABASE_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": SUPABASE_OAUTH_REDIRECT_URI,
                    "client_id": SUPABASE_OAUTH_CLIENT_ID,
                    "client_secret": SUPABASE_OAUTH_CLIENT_SECRET,
                    "code_verifier": code_verifier
                }
            )
        
        # Check for success (200 or 201)
        if token_response.status_code not in [200, 201]:
            logger.error(f"Token exchange failed: {token_response.status_code} - {token_response.text}")
            return RedirectResponse(url=f"/?error=token_exchange_failed")
        
        tokens = token_response.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        
        logger.info(f"OAuth token exchange successful for project {project_id}")
        
        # Store tokens in DATABASE for persistence (survives server restarts)
        token_state = secrets.token_urlsafe(16)
        await database.store_oauth_token(token_state, {
            "project_id": project_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
        })
        
        logger.info(f"OAuth successful for project {project_id}, token_state: {token_state}")
        
        # Redirect to frontend with token state
        # Use the same domain as the redirect URI
        frontend_url = SUPABASE_OAUTH_REDIRECT_URI.replace("/api/auth/supabase/callback", "")
        redirect_url = f"{frontend_url}/builder/{project_id}?supabase_auth={token_state}"
        logger.info(f"Redirecting to: {redirect_url}")
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return RedirectResponse(url=f"/?error=oauth_failed")

@api_router.get("/auth/supabase/projects")
async def list_supabase_projects(token_state: str = Query(...)):
    """List user's Supabase projects using OAuth token"""
    
    # Get token from database (with auto-refresh if expired)
    token_data = await get_valid_oauth_token(token_state)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconnect your Supabase account.")
    
    access_token = token_data["access_token"]
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SUPABASE_MANAGEMENT_API}/projects",
                headers={"Authorization": f"Bearer {access_token}"}
            )
        
        if response.status_code != 200:
            logger.error(f"Failed to list projects: {response.text}")
            raise HTTPException(status_code=400, detail="Failed to list projects")
        
        projects = response.json()
        
        # Return simplified project list
        return {
            "projects": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "region": p.get("region"),
                    "organization_id": p.get("organization_id"),
                    "status": p.get("status"),
                    "created_at": p.get("created_at")
                }
                for p in projects
            ],
            "project_id": token_data["project_id"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/auth/supabase/organizations")
async def list_supabase_organizations(token_state: str = Query(...)):
    """List user's Supabase organizations"""
    
    # Get token from database (with auto-refresh if expired)
    token_data = await get_valid_oauth_token(token_state)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconnect your Supabase account.")
    
    access_token = token_data["access_token"]
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{SUPABASE_MANAGEMENT_API}/organizations",
                headers={"Authorization": f"Bearer {access_token}"}
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to list organizations")
        
        return {"organizations": response.json()}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/auth/supabase/projects/create")
async def create_supabase_project(request: SupabaseProjectCreate, token_state: str = Query(...)):
    """Create a new Supabase project"""
    
    # Get token from database (with auto-refresh if expired)
    token_data = await get_valid_oauth_token(token_state)
    if not token_data:
        logger.error(f"Token state not found or expired: {token_state}")
        raise HTTPException(status_code=401, detail="Session expired. Please reconnect your Supabase account.")
    
    access_token = token_data["access_token"]
    
    logger.info(f"Creating Supabase project: {request.name} in org {request.organization_id}")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # Increased timeout for project creation
            response = await client.post(
                f"{SUPABASE_MANAGEMENT_API}/projects",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "name": request.name,
                    "organization_id": request.organization_id,
                    "db_pass": request.db_pass,
                    "region": request.region,
                    "plan": "free"  # Explicitly set to free plan
                }
            )
        
        logger.info(f"Supabase API response: {response.status_code}")
        
        if response.status_code not in [200, 201]:
            error_detail = response.text
            logger.error(f"Failed to create project: {error_detail}")
            
            # Parse error for user-friendly message
            try:
                error_json = response.json()
                if "message" in error_json:
                    error_detail = error_json["message"]
                elif "error" in error_json:
                    error_detail = error_json["error"]
            except:
                pass
            
            raise HTTPException(status_code=400, detail=f"Supabase error: {error_detail}")
        
        result = response.json()
        logger.info(f"Project created successfully: {result.get('id', 'unknown')}")
        return result
        
    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.error("Timeout creating Supabase project")
        raise HTTPException(status_code=504, detail="Request timed out. Supabase project creation can take a while. Please try again.")
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create project: {str(e)}")

@api_router.post("/auth/supabase/connect/{supabase_project_ref}")
async def connect_supabase_project(supabase_project_ref: str, token_state: str = Query(...)):
    """Connect a Supabase project to an App Builder project - fetches credentials automatically"""
    
    # Get token from database (with auto-refresh if expired)
    token_data = await get_valid_oauth_token(token_state)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired token. Please reconnect your Supabase account.")
    
    access_token = token_data["access_token"]
    app_project_id = token_data.get("project_id")
    
    # SECURITY: Verify the user has access to this specific project
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First verify this project belongs to the user by checking their project list
            verify_response = await client.get(
                f"{SUPABASE_MANAGEMENT_API}/projects",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if verify_response.status_code != 200:
                raise HTTPException(status_code=403, detail="Cannot verify project ownership")
            
            user_projects = verify_response.json()
            project_ids = [p.get("id") for p in user_projects]
            
            if supabase_project_ref not in project_ids:
                logger.error(f"SECURITY: Attempted to connect unauthorized project {supabase_project_ref}")
                raise HTTPException(status_code=403, detail="You don't have access to this project")
            
            # Get project details
            project_response = await client.get(
                f"{SUPABASE_MANAGEMENT_API}/projects/{supabase_project_ref}",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if project_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get project details")
            
            project_info = project_response.json()
            
            # Get API keys
            keys_response = await client.get(
                f"{SUPABASE_MANAGEMENT_API}/projects/{supabase_project_ref}/api-keys",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if keys_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to get API keys")
            
            api_keys = keys_response.json()
            
            # Find anon and service_role keys
            anon_key = None
            service_role_key = None
            for key in api_keys:
                if key.get("name") == "anon":
                    anon_key = key.get("api_key")
                elif key.get("name") == "service_role":
                    service_role_key = key.get("api_key")
        
        # Build Supabase URL
        supabase_url = f"https://{supabase_project_ref}.supabase.co"
        
        # Update the App Builder project with Supabase credentials
        app_project = await database.get_project(app_project_id)
        if not app_project:
            raise HTTPException(status_code=404, detail="App Builder project not found")
        
        # Store ONLY this project's credentials - strict isolation
        await database.update_project(app_project_id, {
            "supabase_connected": True,
            "supabase_url": supabase_url,
            "supabase_anon_key": anon_key,
            "supabase_service_key": service_role_key,
            "supabase_project_ref": supabase_project_ref,  # Store the ref for all future operations
            "supabase_project_name": project_info.get("name"),
            "supabase_region": project_info.get("region"),
            "supabase_connected_at": datetime.now(timezone.utc).isoformat()
        })
        
        # Clean up token from database (no longer needed)
        await database.delete_oauth_token(token_state)
        
        logger.info(f"Connected Supabase project {supabase_project_ref} to App Builder project {app_project_id}")
        
        return {
            "connected": True,
            "supabase_url": supabase_url,
            "project_name": project_info.get("name"),
            "region": project_info.get("region")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error connecting project: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==================== SUPABASE PROJECT ISOLATION HELPER ====================

async def run_migrations_internal(project_id: str, files: list) -> dict:
    """
    Internal function to run SQL migrations after code generation.
    Executes SQL directly against the connected Supabase project.
    """
    try:
        project = await database.get_project(project_id)
        if not project or not project.get("supabase_connected"):
            return {"status": "skipped", "message": "No Supabase connected"}
        
        supabase_url = project.get("supabase_url")
        service_key = project.get("supabase_service_key")
        project_ref = project.get("supabase_project_ref")
        project_name = project.get("supabase_project_name", "")
        
        if not service_key:
            return {"status": "skipped", "message": "No service key available"}
        
        # Find SQL files
        sql_files = [f for f in files if f.get("file_type") == "sql" or f.get("path", "").endswith(".sql")]
        
        if not sql_files:
            return {"status": "skipped", "message": "No SQL migrations found"}
        
        results = []
        for sql_file in sql_files:
            sql_content = sql_file.get("content", "")
            file_path = sql_file.get("path", "unknown")
            
            try:
                # Execute SQL using Supabase's pg-meta query endpoint
                # This is the internal API that Supabase dashboard uses
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # Try the pg-meta query endpoint
                    pg_meta_url = f"{supabase_url}/pg/query"
                    
                    response = await client.post(
                        pg_meta_url,
                        headers={
                            "apikey": service_key,
                            "Authorization": f"Bearer {service_key}",
                            "Content-Type": "application/json"
                        },
                        json={"query": sql_content}
                    )
                    
                    if response.status_code in [200, 201]:
                        results.append({
                            "file": file_path,
                            "status": "success",
                            "message": "Migration executed successfully"
                        })
                        logger.info(f"Migration {file_path} executed successfully on {project_name}")
                    elif response.status_code == 404:
                        # pg-meta endpoint not available, try alternative approach
                        # Use the REST RPC endpoint with a temporary function
                        logger.info(f"pg-meta not available, trying REST API for {file_path}")
                        
                        # For simple DDL statements, we can sometimes use the REST API
                        # But most will need manual execution
                        results.append({
                            "file": file_path,
                            "status": "pending",
                            "message": "Ready for execution - click 'Run Migration' or execute in SQL Editor",
                            "sql_preview": sql_content[:200] + "..." if len(sql_content) > 200 else sql_content
                        })
                    else:
                        error_text = response.text
                        try:
                            error_json = response.json()
                            error_text = error_json.get("message", error_json.get("error", error_text))
                        except:
                            pass
                        
                        results.append({
                            "file": file_path,
                            "status": "error",
                            "message": f"Migration failed: {error_text[:100]}",
                            "sql_preview": sql_content[:200] + "..." if len(sql_content) > 200 else sql_content
                        })
                        logger.error(f"Migration {file_path} failed: {error_text}")
                        
            except Exception as e:
                logger.error(f"Migration error for {file_path}: {e}")
                results.append({
                    "file": file_path,
                    "status": "error",
                    "message": f"Execution error: {str(e)[:100]}"
                })
        
        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = sum(1 for r in results if r["status"] == "error")
        pending_count = sum(1 for r in results if r["status"] == "pending")
        
        status = "completed" if error_count == 0 and pending_count == 0 else "partial" if success_count > 0 else "pending"
        
        return {
            "status": status,
            "total": len(results),
            "success": success_count,
            "errors": error_count,
            "pending": pending_count,
            "results": results,
            "project_ref": project_ref,
            "sql_editor_url": f"https://supabase.com/dashboard/project/{project_ref}/sql/new"
        }
        
    except Exception as e:
        logger.error(f"Migration internal error: {e}")
        return {"status": "error", "message": str(e)}


async def deploy_edge_functions_internal(project_id: str, files: list) -> dict:
    """
    Internal function to deploy Edge Functions after code generation.
    Uses Supabase Management API to deploy functions.
    """
    try:
        project = await database.get_project(project_id)
        if not project or not project.get("supabase_connected"):
            return {"status": "skipped", "message": "No Supabase connected"}
        
        project_ref = project.get("supabase_project_ref")
        service_key = project.get("supabase_service_key")
        supabase_url = project.get("supabase_url")
        
        # Find Edge Function files
        edge_functions = [f for f in files if f.get("file_type") == "edge_function" or "supabase/functions" in f.get("path", "")]
        
        if not edge_functions:
            return {"status": "skipped", "message": "No Edge Functions found"}
        
        # Group by function name
        functions_by_name = {}
        for f in edge_functions:
            path = f.get("path", "")
            # Extract function name from path like "supabase/functions/hello/index.ts"
            parts = path.split("/")
            if "functions" in parts:
                func_idx = parts.index("functions")
                if func_idx + 1 < len(parts):
                    func_name = parts[func_idx + 1]
                    if func_name not in functions_by_name:
                        functions_by_name[func_name] = []
                    functions_by_name[func_name].append(f)
        
        results = []
        for func_name, func_files in functions_by_name.items():
            # Get the main function file (index.ts)
            main_file = next((f for f in func_files if "index.ts" in f.get("path", "")), func_files[0] if func_files else None)
            
            if not main_file:
                results.append({
                    "function": func_name,
                    "status": "error",
                    "message": "No index.ts found for function"
                })
                continue
            
            function_code = main_file.get("content", "")
            
            try:
                # Try to deploy via Management API
                # Note: This may require additional OAuth scopes
                async with httpx.AsyncClient(timeout=60.0) as client:
                    # Check if function exists
                    check_url = f"{SUPABASE_MANAGEMENT_API}/projects/{project_ref}/functions/{func_name}"
                    
                    # For now, prepare for CLI deployment as Management API has limitations
                    results.append({
                        "function": func_name,
                        "status": "ready",
                        "files": [f.get("path") for f in func_files],
                        "message": f"Function '{func_name}' ready for deployment",
                        "deploy_command": f"supabase functions deploy {func_name} --project-ref {project_ref}"
                    })
                    logger.info(f"Edge Function '{func_name}' prepared for deployment")
                    
            except Exception as e:
                logger.error(f"Error deploying function {func_name}: {e}")
                results.append({
                    "function": func_name,
                    "status": "error",
                    "message": str(e)[:100]
                })
        
        success_count = sum(1 for r in results if r["status"] in ["success", "ready"])
        
        return {
            "status": "ready" if success_count > 0 else "error",
            "total": len(results),
            "success": success_count,
            "functions": results,
            "deploy_command": f"supabase functions deploy --project-ref {project_ref}",
            "message": f"{success_count} function(s) ready for deployment"
        }
        
    except Exception as e:
        logger.error(f"Edge function deployment error: {e}")
        return {"status": "error", "message": str(e)}


async def get_connected_supabase_project(app_project_id: str) -> dict:
    """
    Get the connected Supabase project for an App Builder project.
    This ensures ALL operations only happen on the specifically connected project.
    
    Returns:
        dict with supabase_url, supabase_anon_key, supabase_service_key, supabase_project_ref
    
    Raises:
        HTTPException if no Supabase project is connected
    """
    project = await database.get_project(app_project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if not project.get("supabase_connected"):
        raise HTTPException(status_code=400, detail="No Supabase project connected. Please connect a Supabase project first.")
    
    supabase_project_ref = project.get("supabase_project_ref")
    if not supabase_project_ref:
        raise HTTPException(status_code=400, detail="Supabase project reference not found. Please reconnect Supabase.")
    
    return {
        "url": project.get("supabase_url"),
        "anon_key": project.get("supabase_anon_key"),
        "service_key": project.get("supabase_service_key"),
        "project_ref": supabase_project_ref,
        "project_name": project.get("supabase_project_name")
    }

@api_router.post("/projects/{project_id}/supabase/run-migration")
async def run_supabase_migration(project_id: str):
    """
    Run SQL migrations on the CONNECTED Supabase project only.
    STRICT ISOLATION: This ONLY operates on the connected project.
    """
    # Get the connected Supabase project - this ensures isolation
    supabase = await get_connected_supabase_project(project_id)
    
    # Get the latest version with SQL files
    version = await database.get_latest_version(project_id)
    if not version or not version.get("files"):
        raise HTTPException(status_code=404, detail="No code generated yet")
    
    # Find SQL migration files
    sql_files = [f for f in version["files"] if f.get("file_type") == "sql" or f.get("path", "").endswith(".sql")]
    
    if not sql_files:
        raise HTTPException(status_code=404, detail="No SQL migrations found in the generated code")
    
    # Execute migrations on the CONNECTED project only
    results = []
    
    for sql_file in sql_files:
        sql_content = sql_file.get("content", "")
        file_path = sql_file.get("path", "unknown")
        
        try:
            # Use the Supabase REST API to run SQL
            # This uses the service_key which has admin privileges on THIS project only
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{supabase['url']}/rest/v1/rpc/exec_sql",
                    headers={
                        "apikey": supabase["service_key"] or supabase["anon_key"],
                        "Authorization": f"Bearer {supabase['service_key'] or supabase['anon_key']}",
                        "Content-Type": "application/json"
                    },
                    json={"query": sql_content}
                )
                
                if response.status_code in [200, 201]:
                    results.append({"file": file_path, "status": "success"})
                    logger.info(f"Migration {file_path} executed successfully on {supabase['project_name']}")
                else:
                    # Try direct PostgreSQL connection as fallback
                    results.append({
                        "file": file_path, 
                        "status": "pending",
                        "message": "Please run this migration manually in Supabase SQL Editor"
                    })
                    
        except Exception as e:
            logger.error(f"Migration error for {file_path}: {e}")
            results.append({
                "file": file_path,
                "status": "error",
                "message": str(e)
            })
    
    return {
        "project_ref": supabase["project_ref"],
        "project_name": supabase["project_name"],
        "migrations": results
    }

@api_router.post("/projects/{project_id}/migrations/approve")
async def approve_and_run_migrations(project_id: str):
    """
    Approve and run pending migrations after user confirmation.
    STRICT ISOLATION: This ONLY operates on the connected Supabase project.
    """
    # Get project with pending migrations
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    pending_migrations = project.get("pending_migrations", [])
    if not pending_migrations:
        raise HTTPException(status_code=404, detail="No pending migrations to run")
    
    # Ensure Supabase is connected
    if not project.get("supabase_connected"):
        raise HTTPException(status_code=400, detail="Supabase not connected")
    
    supabase_url = project.get("supabase_url")
    service_key = project.get("supabase_service_key")
    project_ref = project.get("supabase_project_ref")
    project_name = project.get("supabase_project_name", "")
    
    if not service_key:
        return {
            "status": "pending",
            "message": "No service key available. Please run migrations manually in Supabase SQL Editor.",
            "sql_editor_url": f"https://supabase.com/dashboard/project/{project_ref}/sql/new"
        }
    
    results = []
    success_count = 0
    pending_count = 0
    
    for migration in pending_migrations:
        sql_content = migration.get("full_sql", "")
        file_path = migration.get("file", "unknown")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Try the pg-meta query endpoint
                pg_meta_url = f"{supabase_url}/pg/query"
                
                response = await client.post(
                    pg_meta_url,
                    headers={
                        "apikey": service_key,
                        "Authorization": f"Bearer {service_key}",
                        "Content-Type": "application/json"
                    },
                    json={"query": sql_content}
                )
                
                if response.status_code in [200, 201]:
                    results.append({
                        "file": file_path,
                        "status": "success",
                        "message": "Migration executed successfully"
                    })
                    success_count += 1
                    logger.info(f"Migration {file_path} executed successfully on {project_name}")
                elif response.status_code == 404:
                    # pg-meta not available
                    results.append({
                        "file": file_path,
                        "status": "pending",
                        "message": "Please run in Supabase SQL Editor",
                        "sql_preview": sql_content[:200] + "..." if len(sql_content) > 200 else sql_content
                    })
                    pending_count += 1
                else:
                    error_text = response.text
                    try:
                        error_json = response.json()
                        error_text = error_json.get("message", error_json.get("error", error_text))
                    except:
                        pass
                    
                    results.append({
                        "file": file_path,
                        "status": "error",
                        "message": f"Error: {error_text}"
                    })
                    
        except Exception as e:
            logger.error(f"Migration error for {file_path}: {e}")
            results.append({
                "file": file_path,
                "status": "error",
                "message": str(e)
            })
    
    # Clear pending migrations after processing
    await database.update_project(project_id, {
        "pending_migrations": None,
        "pending_migrations_version": None,
        "last_migration_run": datetime.now(timezone.utc).isoformat()
    })
    
    # Determine overall status
    if success_count == len(pending_migrations):
        status = "completed"
    elif success_count > 0:
        status = "partial"
    elif pending_count > 0:
        status = "pending"
    else:
        status = "error"
    
    return {
        "status": status,
        "success": success_count,
        "pending": pending_count,
        "total": len(pending_migrations),
        "results": results,
        "project_name": project_name,
        "sql_editor_url": f"https://supabase.com/dashboard/project/{project_ref}/sql/new"
    }

@api_router.post("/projects/{project_id}/migrations/skip")
async def skip_migrations(project_id: str):
    """
    Skip pending migrations (user chose not to run them).
    """
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Clear pending migrations
    await database.update_project(project_id, {
        "pending_migrations": None,
        "pending_migrations_version": None
    })
    
    return {"status": "skipped", "message": "Migrations skipped by user"}

@api_router.get("/projects/{project_id}/supabase/info")
async def get_supabase_info(project_id: str):
    """Get information about the connected Supabase project (isolated)"""
    try:
        supabase = await get_connected_supabase_project(project_id)
        return {
            "connected": True,
            "project_ref": supabase["project_ref"],
            "project_name": supabase["project_name"],
            "url": supabase["url"]
        }
    except HTTPException as e:
        if e.status_code == 400:
            return {"connected": False}
        raise

# ==================== DIFF-BASED CODE ANALYSIS ====================

async def analyze_affected_files(files: list, summary: str, user_request: str) -> dict:
    """
    Analyze which files need to be modified based on user request.
    This is Pass 1 of the incremental generation approach.
    """
    file_list = [f"{f['path']} ({f.get('file_type', 'frontend')})" for f in files]
    
    prompt = INTENT_DIFF_PROMPT.replace("{summary}", summary or "No summary available")
    prompt = prompt.replace("{file_list}", "\n".join(file_list))
    prompt = prompt.replace("{request}", user_request)
    
    messages = [
        {"role": "system", "content": "You are a code analysis assistant. Return only valid JSON."},
        {"role": "user", "content": prompt}
    ]
    
    try:
        result = await call_openrouter(messages)
        if result:
            # Parse JSON from response
            content = result.get("content", "")
            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            return json.loads(content.strip())
    except Exception as e:
        logger.error(f"Error analyzing affected files: {e}")
    
    # Fallback: assume all files affected
    return {
        "change_type": "unknown",
        "affected_files": [f["path"] for f in files],
        "new_files": [],
        "scope": "major",
        "description": "Could not determine scope, sending all files"
    }

def get_files_content(files: list, file_paths: list) -> str:
    """Get content of specific files for the diff-based prompt"""
    content_parts = []
    for f in files:
        if f["path"] in file_paths:
            file_type = f.get("file_type", "frontend")
            content_parts.append(f"// File: {f['path']} (type: {file_type})\n{f['content']}")
    return "\n\n".join(content_parts)

# ==================== CONVERSATION CONTEXT ====================

MAX_CONTEXT_MESSAGES = 20  # Max messages before summarization
MAX_CONTEXT_CHARS = 8000   # Approximate char limit for context

async def build_conversation_context(project_id: str, current_prompt: str) -> tuple:
    """
    Build conversation context from chat history.
    Returns (context_messages, conversation_summary)
    
    If history is too long, summarizes older messages.
    """
    messages = await database.get_messages(project_id)
    
    if not messages:
        return [], ""
    
    # Sort by created_at (oldest first)
    messages = sorted(messages, key=lambda m: m.get("created_at", ""))
    
    # Calculate total context size
    total_chars = sum(len(m.get("content", "")) for m in messages)
    
    # If within limits, return all messages
    if len(messages) <= MAX_CONTEXT_MESSAGES and total_chars <= MAX_CONTEXT_CHARS:
        context_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["content"] and not m["content"].startswith("✅")  # Skip status messages
        ]
        return context_messages, ""
    
    # Need to summarize - split into older (to summarize) and recent (to keep)
    recent_count = min(5, len(messages))  # Keep last 5 messages
    older_messages = messages[:-recent_count] if recent_count > 0 else messages
    recent_messages = messages[-recent_count:] if recent_count > 0 else []
    
    # Summarize older messages
    summary = await summarize_conversation(older_messages)
    
    # Build context with summary + recent messages
    context_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in recent_messages
        if m["content"] and not m["content"].startswith("✅")
    ]
    
    return context_messages, summary


async def summarize_conversation(messages: list) -> str:
    """
    Summarize a list of conversation messages.
    Returns a concise summary of what was discussed and built.
    """
    if not messages:
        return ""
    
    # Build conversation text
    conversation_text = "\n".join([
        f"{m['role'].upper()}: {m['content'][:500]}"  # Truncate long messages
        for m in messages
        if m.get("content")
    ])
    
    # Limit input size
    if len(conversation_text) > 6000:
        conversation_text = conversation_text[:6000] + "\n... (truncated)"
    
    summary_prompt = f"""Summarize this conversation history concisely. Focus on:
1. What features/changes were requested
2. What was built/modified
3. Any important decisions or preferences mentioned

Conversation:
{conversation_text}

Return a brief summary (max 500 chars) that captures the key context needed for future development."""

    try:
        result = await call_openrouter([
            {"role": "system", "content": "You are a summarization assistant. Be concise."},
            {"role": "user", "content": summary_prompt}
        ])
        
        if result:
            summary = result.get("content", "")
            # Truncate if too long
            if len(summary) > 600:
                summary = summary[:600] + "..."
            return summary
    except Exception as e:
        logger.error(f"Error summarizing conversation: {e}")
    
    # Fallback: simple extraction
    user_requests = [m["content"][:100] for m in messages if m["role"] == "user"]
    return f"Previous requests: {'; '.join(user_requests[-3:])}"


def build_context_prompt(conversation_summary: str, recent_messages: list) -> str:
    """
    Build a context string to prepend to the system prompt.
    """
    context_parts = []
    
    if conversation_summary:
        context_parts.append(f"CONVERSATION HISTORY SUMMARY:\n{conversation_summary}")
    
    if recent_messages:
        recent_text = "\n".join([
            f"- {m['role'].upper()}: {m['content'][:200]}..."
            if len(m['content']) > 200 else f"- {m['role'].upper()}: {m['content']}"
            for m in recent_messages[-3:]  # Last 3 messages
        ])
        context_parts.append(f"RECENT MESSAGES:\n{recent_text}")
    
    if context_parts:
        return "\n\n".join(context_parts) + "\n\n---\n\n"
    return ""

# ==================== OPENROUTER LLM ====================

async def call_openrouter(messages: List[Dict]):
    """Call OpenRouter API (non-streaming) - returns content dict"""
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
            return None
        
        data = response.json()
        # Extract content from OpenRouter response structure
        try:
            content = data["choices"][0]["message"]["content"]
            return {"content": content}
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to extract content from OpenRouter response: {e}")
            return None

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

IMPORTANT - MOCK DATA APPROACH:
Since no backend is connected yet, you MUST use realistic mock data:
1. Create a mockData.js file with realistic sample data
2. Use useState to manage the mock data
3. Implement full CRUD operations on the mock data (add, edit, delete work locally)
4. Design the data structure to easily connect to a real database later
5. Add a "Demo Mode" badge to indicate data is local/mock

MOCK DATA EXAMPLE:
```javascript
// In mockData.js
export const initialTweets = [
  { id: 1, user: '@johndoe', content: 'Hello world!', likes: 42, createdAt: '2h' },
  { id: 2, user: '@janedoe', content: 'Building amazing apps!', likes: 128, createdAt: '4h' },
];
```

RESPONSIVE DESIGN (MANDATORY - ALL APPS MUST BE FULLY RESPONSIVE):
1. Mobile-first approach: Design for 320px screens first, then scale up
2. Breakpoints: sm:640px, md:768px, lg:1024px, xl:1280px
3. Flexible layouts: Use flex/grid with responsive classes (flex-col sm:flex-row)
4. Touch-friendly: Minimum 44px tap targets, adequate spacing between interactive elements
5. Responsive typography: text-sm sm:text-base lg:text-lg
6. Responsive spacing: p-4 sm:p-6 lg:p-8
7. Hide/show elements: Use hidden sm:block or sm:hidden as needed
8. Responsive images: Use w-full max-w-[size] object-cover
9. Mobile navigation: Hamburger menu on mobile, full nav on desktop
10. Test mentally: Ensure layout works on phone, tablet, and desktop

DESIGN EXCELLENCE REQUIREMENTS:
1. Use modern UI patterns (glass morphism, subtle gradients, micro-interactions)
2. Create visually striking color schemes - avoid generic blue/gray
3. Add thoughtful spacing, typography hierarchy, and visual rhythm
4. Include hover states, transitions, and delightful animations
5. Use professional-grade design like Dribbble/Behance showcase projects

OUTPUT FORMAT (RAW JSON ONLY - NO MARKDOWN):
{"files":[{"path":"App.jsx","content":"code"},{"path":"data/mockData.js","content":"code"},{"path":"components/X.jsx","content":"code"}],"summary":"description"}

FILE STRUCTURE (ALWAYS MULTIPLE FILES):
- App.jsx: Clean entry point composing components
- data/mockData.js: Realistic sample data for the app
- components/Header.jsx: Navigation with search, user menu (responsive hamburger)
- components/Sidebar.jsx: Navigation sidebar (collapsible on mobile)
- components/[Feature].jsx: Feature-specific components
- components/Card.jsx: Reusable card component
- components/MobileNav.jsx: Mobile navigation component (if complex nav)

UI BEST PRACTICES:
- Use Tailwind's design system consistently
- Add shadows, rounded corners, proper padding
- Include loading states and empty states
- Use icons (Lucide React icons: import { Icon } from 'lucide-react')
- Create visual hierarchy with font sizes and weights
- Use whitespace generously
- Add subtle background patterns or gradients
- ALWAYS use responsive Tailwind classes (sm:, md:, lg:, xl:)
- Show "Demo Mode" indicator when using mock data

COLOR PALETTE EXAMPLES (choose based on app type):
- Professional/Corporate: Slate, Blue, White
- Creative/Fun: Purple, Pink, Orange gradients
- Health/Wellness: Green, Teal, Soft pastels
- Finance/Business: Navy, Gold, Clean whites
- Social/Community: Vibrant gradients, Purple to Pink
- E-commerce: Trust colors (Blue), Action colors (Orange/Red)

CRITICAL: Return ONLY raw JSON. No markdown code blocks. ALL layouts MUST be responsive. ALL CRUD operations must work with mock data."""

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
FILE LIST: {file_list}
USER REQUEST: {request}

Return JSON:
{{
  "change_type": "ui_change|feature_add|bug_fix|refactor|new_feature",
  "affected_files": ["Exact file paths that need modifications"],
  "new_files": ["New file paths to create, if any"],
  "scope": "minor|moderate|major",
  "description": "Brief description of what needs to change"
}}

RULES:
- Only list files that ACTUALLY need changes
- Be conservative - don't include files that don't need modification
- For UI changes, typically only the component file needs changes
- For new features, identify the minimal set of files"""

# Diff-based update prompt - only sends affected files
DIFF_UPDATE_PROMPT = """You are an elite developer. Make ONLY the requested changes.

FILES TO MODIFY:
{affected_files_content}

USER REQUEST: {user_request}

RULES:
1. Return ONLY the files that changed (not unchanged files)
2. Return complete file content for each modified file
3. You can add new files if needed
4. Keep changes minimal and focused

OUTPUT FORMAT (JSON only):
{{
  "files": [
    {{"path": "filename", "content": "complete file content", "file_type": "frontend|edge_function|sql", "action": "modified|created"}}
  ],
  "summary": "Brief description of changes",
  "changes": ["List of specific changes made"]
}}

IMPORTANT: Only return files you actually modified or created. Unchanged files should NOT be included."""

DIFF_UPDATE_FULLSTACK_PROMPT = """You are an elite full-stack developer. Make ONLY the requested changes.

SUPABASE PROJECT URL: {supabase_url}

FILES TO MODIFY:
{affected_files_content}

USER REQUEST: {user_request}

RULES:
1. Return ONLY the files that changed (not unchanged files)
2. Return complete file content for each modified file
3. Add new Edge Functions or SQL migrations only if needed
4. Keep changes minimal and focused

OUTPUT FORMAT (JSON only):
{{
  "files": [
    {{"path": "filename", "content": "complete file content", "file_type": "frontend|edge_function|sql", "action": "modified|created"}}
  ],
  "summary": "Brief description of changes",
  "changes": ["List of specific changes made"],
  "new_tables": ["Any new database tables created"]
}}

IMPORTANT: Only return files you actually modified or created. Unchanged files should NOT be included."""

# ==================== FULL-STACK GENERATION PROMPTS ====================

FULLSTACK_SYSTEM_PROMPT = """You are an elite full-stack developer. Generate complete web applications with:
- React frontend (JSX with Tailwind CSS) - MUST BE FULLY RESPONSIVE
- Supabase Edge Functions backend (TypeScript/Deno)
- PostgreSQL database schema (SQL)

The user has connected their Supabase project. Generate production-ready code.

RESPONSIVE DESIGN (MANDATORY - ALL APPS MUST BE FULLY RESPONSIVE):
1. Mobile-first approach: Design for 320px screens first, then scale up
2. Breakpoints: sm:640px, md:768px, lg:1024px, xl:1280px
3. Flexible layouts: Use flex/grid with responsive classes (flex-col sm:flex-row)
4. Touch-friendly: Minimum 44px tap targets, adequate spacing between interactive elements
5. Responsive typography: text-sm sm:text-base lg:text-lg
6. Responsive spacing: p-4 sm:p-6 lg:p-8
7. Hide/show elements: Use hidden sm:block or sm:hidden as needed
8. Mobile navigation: Hamburger menu on mobile, full nav on desktop

IMPORTANT - PROJECT ISOLATION:
- All code must ONLY operate on the connected Supabase project
- The Supabase URL below is the ONLY database this app should connect to
- Never include code that accesses any other Supabase projects

SUPABASE PROJECT URL: {supabase_url}

OUTPUT FORMAT (RAW JSON ONLY - NO MARKDOWN):
{{
  "files": [
    {{"path": "App.jsx", "content": "...", "file_type": "frontend"}},
    {{"path": "components/Header.jsx", "content": "...", "file_type": "frontend"}},
    {{"path": "components/MobileNav.jsx", "content": "...", "file_type": "frontend"}},
    {{"path": "supabase/functions/api/index.ts", "content": "...", "file_type": "edge_function"}},
    {{"path": "supabase/migrations/001_initial.sql", "content": "...", "file_type": "sql"}}
  ],
  "summary": "Brief description",
  "database_tables": ["table1", "table2"]
}}

FILE STRUCTURE:
1. Frontend (React/JSX):
   - App.jsx: Main component with routing (responsive layout)
   - components/Header.jsx: Navigation with hamburger menu for mobile
   - components/MobileNav.jsx: Mobile navigation drawer
   - components/*.jsx: Feature components (all responsive)
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
- Use Tailwind CSS with RESPONSIVE classes (sm:, md:, lg:, xl:)
- ALL layouts must work on mobile, tablet, and desktop

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

CRITICAL: Return ONLY raw JSON. No markdown code blocks. ALL layouts MUST be responsive."""

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
        if not response:
            logger.error("Auto-fix: No response from LLM")
            return None, None
        
        content = response.get("content", "")
        if not content:
            logger.error("Auto-fix: Empty content from LLM")
            return None, None
        
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
    """Analyze a prompt and extract requirements with clarifying questions"""
    
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
    
    # Use ClarificationAgent if available
    if clarification_agent:
        try:
            context = {
                "supabase_connected": project.get("supabase_connected", False),
                "project_name": project.get("name", ""),
                "existing_summary": project.get("summary", "")
            }
            
            analysis = await clarification_agent.analyze_prompt(request.prompt, context)
            
            # Return with clarification questions
            questions = analysis.get("clarifying_questions", [])
            requirements = analysis.get("requirements", [])
            
            return {
                "needs_clarification": len(questions) > 0,
                "questions": questions,
                "requirements": requirements,
                "project_summary": analysis.get("project_summary", ""),
                "assumptions": analysis.get("assumptions", []),
                "technical_considerations": analysis.get("technical_considerations", []),
                "formatted_requirements": clarification_agent.format_requirements_for_display(analysis),
                "analysis": analysis
            }
        except Exception as e:
            logger.error(f"Clarification agent error: {e}")
            # Fall back to no clarification
            return {"needs_clarification": False}
    
    # Fallback: Use basic clarification prompt
    messages = [
        {"role": "system", "content": CLARIFICATION_PROMPT.replace("{prompt}", request.prompt)},
        {"role": "user", "content": f"Analyze this request: {request.prompt}"}
    ]
    
    try:
        response = await call_openrouter(messages)
        if not response:
            logger.error("Test agent: No response from LLM")
            return {"status": "FAIL", "passed": 0, "failed": 0, "total": 0, "details": []}
        
        content = response.get("content", "")
        
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
        
        if not response:
            logger.error("Clarification: No response from LLM")
            return ClarificationResponse(
                requirements={},
                clarifying_questions=[],
                suggested_features=[],
                is_clear=True,
                original_prompt=request.prompt
            )
        
        # Parse response
        content = response.get("content", "")
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

# ==================== REQUIREMENT CLARIFICATION ====================

@api_router.post("/projects/{project_id}/clarify")
async def clarify_requirements(project_id: str, request: ClarifyRequest):
    """
    Analyze user prompt and extract requirements with clarifying questions.
    Call this BEFORE generate/stream to get user confirmation.
    """
    if not clarification_agent:
        raise HTTPException(status_code=500, detail="Clarification agent not initialized")
    
    # Get project for context
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Build context
    context = {
        "supabase_connected": project.get("supabase_connected", False),
        "project_name": project.get("name", ""),
        "existing_summary": project.get("summary", "")
    }
    
    # Analyze prompt
    analysis = await clarification_agent.analyze_prompt(request.prompt, context)
    
    return {
        "status": "success",
        "analysis": analysis,
        "questions": clarification_agent.format_questions_for_display(analysis),
        "formatted_requirements": clarification_agent.format_requirements_for_display(analysis)
    }


@api_router.post("/projects/{project_id}/confirm-requirements")
async def confirm_requirements(project_id: str, request: ConfirmRequirementsRequest):
    """
    Refine requirements based on user's answers to clarifying questions.
    Returns final requirements ready for code generation.
    """
    if not clarification_agent:
        raise HTTPException(status_code=500, detail="Clarification agent not initialized")
    
    # Refine requirements with user answers
    refined = await clarification_agent.refine_requirements(
        request.analysis, 
        request.user_answers
    )
    
    return {
        "status": "success",
        "refined_requirements": refined,
        "ready_for_generation": True
    }

# ==================== BACKGROUND GENERATION ====================

async def run_background_generation(task_id: str, project_id: str, prompt: str, enable_testing: bool = True, max_test_retries: int = 3):
    """
    Run code generation in the background.
    This function runs independently of HTTP connection.
    """
    try:
        # Get project
        project = await database.get_project(project_id)
        if not project:
            await database.update_generation_task(task_id, {
                "status": "failed",
                "error": "Project not found"
            })
            return
        
        # Update task status
        await database.update_generation_task(task_id, {
            "status": "analyzing",
            "progress": 5,
            "current_step": "Analyzing request..."
        })
        
        # Build conversation context (remembers previous messages)
        recent_messages, conversation_summary = await build_conversation_context(project_id, prompt)
        context_prompt = build_context_prompt(conversation_summary, recent_messages)
        
        logger.info(f"Built context: {len(recent_messages)} recent msgs, summary: {len(conversation_summary)} chars")
        
        # Get latest version
        latest_version = await database.get_latest_version(project_id)
        new_version_number = (latest_version["version_number"] + 1) if latest_version else 1
        
        # Check if Supabase is connected
        is_fullstack = project.get("supabase_connected", False)
        supabase_url = project.get("supabase_url", "")
        
        existing_files = latest_version.get("files", []) if latest_version else []
        
        # Determine if we should use diff-based approach
        use_diff_approach = bool(existing_files)
        
        await database.update_generation_task(task_id, {
            "status": "generating",
            "progress": 15,
            "current_step": "Generating code..." if not use_diff_approach else "Analyzing changes..."
        })
        
        messages_to_send = []
        affected_analysis = None
        
        if use_diff_approach and existing_files:
            # Diff-based approach for updates
            await database.update_generation_task(task_id, {
                "progress": 20,
                "current_step": "Identifying affected files..."
            })
            
            project_summary = project.get("summary", "")
            affected_analysis = await analyze_affected_files(existing_files, project_summary, prompt)
            
            affected_files = affected_analysis.get("affected_files", [])
            affected_content = get_files_content(existing_files, affected_files)
            
            if is_fullstack:
                system_content = DIFF_UPDATE_FULLSTACK_PROMPT.replace("{supabase_url}", supabase_url)
                system_content = system_content.replace("{affected_files_content}", affected_content or "No existing files")
                system_content = system_content.replace("{user_request}", prompt)
            else:
                system_content = DIFF_UPDATE_PROMPT.replace("{affected_files_content}", affected_content or "No existing files")
                system_content = system_content.replace("{user_request}", prompt)
            
            # Prepend conversation context to system prompt
            system_content = context_prompt + system_content
            
            messages_to_send = [
                {"role": "system", "content": system_content},
                {"role": "user", "content": f"Make the following changes: {prompt}"}
            ]
        else:
            # Full generation for new projects
            if is_fullstack:
                system_content = FULLSTACK_SYSTEM_PROMPT.replace("{supabase_url}", supabase_url)
                # Prepend conversation context
                system_content = context_prompt + system_content
                messages_to_send = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Create a full-stack application with Supabase backend: {prompt}"}
                ]
            else:
                system_content = context_prompt + SYSTEM_PROMPT
                messages_to_send = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Create a React application: {prompt}"}
                ]
        
        await database.update_generation_task(task_id, {
            "progress": 30,
            "current_step": "Generating code with AI..."
        })
        
        # Call LLM (non-streaming for background)
        result = await call_openrouter(messages_to_send)
        
        if not result:
            await database.update_generation_task(task_id, {
                "status": "failed",
                "error": "Failed to generate code from LLM"
            })
            return
        
        full_content = result.get("content", "")
        
        await database.update_generation_task(task_id, {
            "progress": 50,
            "current_step": "Parsing generated code..."
        })
        
        # Parse JSON from response
        files = []
        summary = ""
        
        try:
            json_match = re.search(r'\{[\s\S]*\}', full_content)
            if json_match:
                parsed = json.loads(json_match.group(), strict=False)
                files = parsed.get("files", [])
                summary = parsed.get("summary", "")
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            await database.update_generation_task(task_id, {
                "status": "failed",
                "error": f"Failed to parse generated code: {str(e)}"
            })
            return
        
        if not files:
            await database.update_generation_task(task_id, {
                "status": "failed",
                "error": "No files generated"
            })
            return
        
        await database.update_generation_task(task_id, {
            "progress": 60,
            "current_step": "Validating code..."
        })
        
        # Validate code
        validation_errors = validate_react_code(files)
        if validation_errors:
            fixed_files, fix_summary = await auto_fix_code(files, validation_errors, project.get("summary", ""))
            if fixed_files:
                files = fixed_files
                summary = f"{summary}. Auto-fixed: {fix_summary}"
        
        # Merge files for diff-based updates
        if use_diff_approach and existing_files:
            returned_files_map = {f["path"]: f for f in files}
            merged_files = []
            updated_paths = set()
            
            for existing_file in existing_files:
                path = existing_file["path"]
                if path in returned_files_map:
                    merged_files.append(returned_files_map[path])
                    updated_paths.add(path)
                else:
                    merged_files.append(existing_file)
            
            for f in files:
                if f["path"] not in updated_paths:
                    merged_files.append(f)
            
            files = merged_files
        
        await database.update_generation_task(task_id, {
            "progress": 70,
            "current_step": "Saving version..."
        })
        
        # Create version
        version = Version(
            project_id=project_id,
            version_number=new_version_number,
            prompt=prompt,
            files=[VersionFile(**f) if isinstance(f, dict) else f for f in files],
            status="success"
        )
        await database.create_version(version.model_dump())
        
        # Update project
        await database.update_project(project_id, {
            "current_version": new_version_number,
            "summary": summary or project.get("summary", ""),
            "updated_at": datetime.now(timezone.utc).isoformat()
        })
        
        # Run migrations if fullstack
        migration_result = None
        deploy_result = None
        
        if is_fullstack:
            sql_files = [f for f in files if f.get("file_type") == "sql" or f.get("path", "").endswith(".sql")]
            edge_functions = [f for f in files if f.get("file_type") == "edge_function" or "supabase/functions" in f.get("path", "")]
            
            if sql_files:
                await database.update_generation_task(task_id, {
                    "status": "migrating",
                    "progress": 80,
                    "current_step": "Running database migrations..."
                })
                migration_result = await run_migrations_internal(project_id, files)
            
            if edge_functions:
                await database.update_generation_task(task_id, {
                    "status": "deploying",
                    "progress": 90,
                    "current_step": "Deploying Edge Functions..."
                })
                deploy_result = await deploy_edge_functions_internal(project_id, files)
        
        # Save assistant message
        assistant_msg = ChatMessage(
            project_id=project_id,
            role="assistant",
            content=f"✅ Generated version {new_version_number}: {summary}"
        )
        await database.create_message(assistant_msg.model_dump())
        
        # Mark task as completed
        await database.update_generation_task(task_id, {
            "status": "completed",
            "progress": 100,
            "current_step": "Complete!",
            "version_number": new_version_number,
            "files": files,
            "summary": summary,
            "migration_result": migration_result,
            "deploy_result": deploy_result,
            "completed_at": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Background generation completed for project {project_id}, version {new_version_number}")
        
    except Exception as e:
        logger.error(f"Background generation error: {e}")
        await database.update_generation_task(task_id, {
            "status": "failed",
            "error": str(e)
        })
    finally:
        # Remove from active tasks
        if project_id in active_generation_tasks:
            del active_generation_tasks[project_id]


@api_router.post("/projects/{project_id}/generate/background")
async def start_background_generation(project_id: str, request: PromptRequest, background_tasks: BackgroundTasks):
    """
    Start code generation in the background.
    Returns immediately with a task ID that can be polled for status.
    """
    # Get project
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Check if there's already an active generation for this project
    active_task = await database.get_active_task_for_project(project_id)
    if active_task:
        return {
            "status": "already_running",
            "task_id": active_task["id"],
            "message": "Generation already in progress"
        }
    
    # Save user message
    user_msg = ChatMessage(project_id=project_id, role="user", content=request.prompt)
    await database.create_message(user_msg.model_dump())
    
    # Create generation task
    task = GenerationTask(
        project_id=project_id,
        prompt=request.prompt,
        status="pending",
        current_step="Starting generation..."
    )
    await database.create_generation_task(task.model_dump())
    
    # Start background task
    async_task = asyncio.create_task(
        run_background_generation(
            task.id,
            project_id,
            request.prompt,
            request.enable_testing,
            request.max_test_retries
        )
    )
    active_generation_tasks[project_id] = async_task
    
    return {
        "status": "started",
        "task_id": task.id,
        "message": "Generation started in background"
    }


@api_router.get("/projects/{project_id}/generate/status")
async def get_generation_status(project_id: str):
    """
    Get the current generation status for a project.
    Used by frontend to poll for completion.
    """
    # First check for active task
    active_task = await database.get_active_task_for_project(project_id)
    if active_task:
        return {
            "status": active_task["status"],
            "task_id": active_task["id"],
            "progress": active_task.get("progress", 0),
            "current_step": active_task.get("current_step", ""),
            "is_running": True
        }
    
    # Check for recently completed task
    latest_task = await database.get_latest_task_for_project(project_id)
    if latest_task:
        return {
            "status": latest_task["status"],
            "task_id": latest_task["id"],
            "progress": latest_task.get("progress", 100),
            "current_step": latest_task.get("current_step", ""),
            "is_running": False,
            "version_number": latest_task.get("version_number"),
            "summary": latest_task.get("summary"),
            "error": latest_task.get("error"),
            "completed_at": latest_task.get("completed_at")
        }
    
    return {
        "status": "idle",
        "is_running": False,
        "message": "No generation in progress"
    }


@api_router.get("/projects/{project_id}/generate/task/{task_id}")
async def get_generation_task(project_id: str, task_id: str):
    """Get details of a specific generation task"""
    task = await database.get_generation_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task["project_id"] != project_id:
        raise HTTPException(status_code=403, detail="Task does not belong to this project")
    
    return task

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
    
    # Variables to track affected files for diff-based generation
    existing_files = latest_version.get("files", []) if latest_version else []
    affected_analysis = None
    use_diff_approach = False
    
    # Build messages based on project type
    if latest_version and latest_version.get("files"):
        # For updates, use diff-based approach
        use_diff_approach = True
        
        # Pass 1: Analyze which files need changes (done in stream_generator for async)
        # We'll do this inside the stream generator
    else:
        # New project - no diff approach needed
        use_diff_approach = False
    
    async def stream_generator():
        nonlocal affected_analysis, use_diff_approach
        full_content = ""
        files_detected = []
        messages_to_send = []
        
        try:
            # Send initial status based on project type
            yield f"data: {json.dumps({'type': 'status', 'message': 'Analyzing request...'})}\n\n"
            await asyncio.sleep(0.1)
            
            # Build conversation context (remembers previous messages)
            recent_messages, conversation_summary = await build_conversation_context(project_id, request.prompt)
            context_prompt = build_context_prompt(conversation_summary, recent_messages)
            
            if conversation_summary:
                yield f"data: {json.dumps({'type': 'status', 'message': '📚 Loaded conversation context...'})}\n\n"
            
            if use_diff_approach and existing_files:
                # DIFF-BASED APPROACH: Analyze which files need changes first
                yield f"data: {json.dumps({'type': 'status', 'message': '🔍 Analyzing which files need changes...'})}\n\n"
                
                project_summary = project.get("summary", "")
                affected_analysis = await analyze_affected_files(existing_files, project_summary, request.prompt)
                
                affected_files = affected_analysis.get("affected_files", [])
                new_files = affected_analysis.get("new_files", [])
                scope = affected_analysis.get("scope", "unknown")
                
                # Log the analysis for debugging
                logger.info(f"Diff analysis: scope={scope}, affected={len(affected_files)}, new={len(new_files)}, total_existing={len(existing_files)}")
                
                yield f"data: {json.dumps({'type': 'status', 'message': f'📝 Scope: {scope} - {len(affected_files)} file(s) to modify'})}\n\n"
                
                # Get content of only affected files
                affected_content = get_files_content(existing_files, affected_files)
                
                # Use diff-based prompt (much smaller context)
                if is_fullstack:
                    system_content = DIFF_UPDATE_FULLSTACK_PROMPT.replace("{supabase_url}", supabase_url)
                    system_content = system_content.replace("{affected_files_content}", affected_content or "No existing files to modify")
                    system_content = system_content.replace("{user_request}", request.prompt)
                else:
                    system_content = DIFF_UPDATE_PROMPT.replace("{affected_files_content}", affected_content or "No existing files to modify")
                    system_content = system_content.replace("{user_request}", request.prompt)
                
                # Prepend conversation context
                system_content = context_prompt + system_content
                
                messages_to_send = [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": f"Make the following changes: {request.prompt}"}
                ]
                
                yield f"data: {json.dumps({'type': 'status', 'message': '🚀 Generating changes (incremental mode)...'})}\n\n"
            else:
                # Full generation for new projects
                if is_fullstack:
                    yield f"data: {json.dumps({'type': 'status', 'message': '🚀 Generating full-stack app (Frontend + Edge Functions + Database)...'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'status', 'message': 'Generating code structure...'})}\n\n"
                
                if is_fullstack:
                    system_content = context_prompt + FULLSTACK_SYSTEM_PROMPT.replace("{supabase_url}", supabase_url)
                    messages_to_send = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": f"Create a full-stack application with Supabase backend: {request.prompt}"}
                    ]
                else:
                    system_content = context_prompt + SYSTEM_PROMPT
                    messages_to_send = [
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": f"Create a React application: {request.prompt}"}
                    ]
            
            # Stream from LLM
            async for chunk in call_openrouter_stream(messages_to_send):
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
            
            # MERGE FILES: For diff-based updates, merge changed files with unchanged files
            if use_diff_approach and existing_files:
                yield f"data: {json.dumps({'type': 'status', 'message': '🔄 Merging changes with existing files...'})}\n\n"
                
                # Create a map of returned files by path
                returned_files_map = {f["path"]: f for f in files}
                
                # Start with existing files and update/add as needed
                merged_files = []
                updated_paths = set()
                
                for existing_file in existing_files:
                    path = existing_file["path"]
                    if path in returned_files_map:
                        # File was modified - use new version
                        merged_files.append(returned_files_map[path])
                        updated_paths.add(path)
                    else:
                        # File unchanged - keep existing
                        merged_files.append(existing_file)
                
                # Add any new files
                for f in files:
                    if f["path"] not in updated_paths:
                        merged_files.append(f)
                        updated_paths.add(f["path"])
                
                files = merged_files
                logger.info(f"Merged files: {len(existing_files)} existing + {len(returned_files_map)} modified/new = {len(files)} total")
            
            # ==================== TESTING AGENT ====================
            test_results = None
            if request.enable_testing and testing_agent:
                yield f"data: {json.dumps({'type': 'status', 'message': '🧪 Running automated tests...'})}\n\n"
                
                # Get Supabase config for testing
                test_supabase_config = None
                if project.get("supabase_connected"):
                    test_supabase_config = {
                        "url": project.get("supabase_url", ""),
                        "anon_key": project.get("supabase_anon_key", "")
                    }
                
                # Extract requirements from prompt
                requirements = await testing_agent.extract_requirements(request.prompt)
                yield f"data: {json.dumps({'type': 'status', 'message': f'📋 Found {len(requirements)} testable requirement(s)'})}\n\n"
                
                # Run testing loop with retries
                attempt = 0
                max_attempts = min(request.max_test_retries, MAX_RETRY_ATTEMPTS)
                current_files = files
                current_summary = summary
                
                while attempt < max_attempts:
                    attempt += 1
                    
                    # Run tests
                    test_results = await testing_agent.run_tests(current_files, requirements, test_supabase_config)
                    
                    if test_results["status"] == "PASS":
                        passed_count = test_results.get("passed", 0)
                        total_count = test_results.get("total", 0)
                        yield f"data: {json.dumps({'type': 'status', 'message': f'✅ All tests passed ({passed_count}/{total_count})'})}\n\n"
                        yield f"data: {json.dumps({'type': 'test_result', 'status': 'PASS', 'attempt': attempt, 'results': test_results})}\n\n"
                        break
                    else:
                        failed_count = test_results.get("failed", 0)
                        total_count = test_results.get("total", 0)
                        
                        if attempt < max_attempts:
                            yield f"data: {json.dumps({'type': 'status', 'message': f'⚠️ Tests failed ({failed_count}/{total_count}). Attempt {attempt}/{max_attempts}. Fixing issues...'})}\n\n"
                            yield f"data: {json.dumps({'type': 'test_result', 'status': 'FAIL', 'attempt': attempt, 'results': test_results, 'retrying': True})}\n\n"
                            
                            # Generate fix prompt
                            fix_prompt = await testing_agent.generate_fix_prompt(request.prompt, current_files, test_results)
                            
                            # Regenerate with fix prompt
                            yield f"data: {json.dumps({'type': 'status', 'message': '🔧 Regenerating code to fix issues...'})}\n\n"
                            
                            # Call LLM to fix issues
                            fix_messages = [
                                {"role": "system", "content": SYSTEM_PROMPT if not is_fullstack else FULLSTACK_SYSTEM_PROMPT.replace("{supabase_url}", supabase_url)},
                                {"role": "user", "content": fix_prompt}
                            ]
                            
                            fix_content = ""
                            async for chunk in call_openrouter_stream(fix_messages):
                                fix_content += chunk
                            
                            # Parse fixed code
                            try:
                                fix_result = json.loads(fix_content, strict=False)
                                if fix_result.get("files"):
                                    current_files = fix_result["files"]
                                    current_summary = fix_result.get("summary", current_summary)
                                    # Re-apply file types
                                    for f in current_files:
                                        path = f.get("path", "")
                                        if ".sql" in path:
                                            f["file_type"] = "sql"
                                        elif "supabase/functions" in path or path.endswith(".ts"):
                                            f["file_type"] = "edge_function"
                                        elif not f.get("file_type"):
                                            f["file_type"] = "frontend"
                            except:
                                # Try to extract JSON from response
                                import re
                                json_match = re.search(r'\{[\s\S]*"files"[\s\S]*\}', fix_content)
                                if json_match:
                                    try:
                                        fix_result = json.loads(json_match.group(), strict=False)
                                        if fix_result.get("files"):
                                            current_files = fix_result["files"]
                                            current_summary = fix_result.get("summary", current_summary)
                                    except:
                                        pass
                        else:
                            yield f"data: {json.dumps({'type': 'status', 'message': f'❌ Tests still failing after {max_attempts} attempts ({failed_count}/{total_count} failed)'})}\n\n"
                            yield f"data: {json.dumps({'type': 'test_result', 'status': 'FAIL', 'attempt': attempt, 'results': test_results, 'retrying': False, 'max_attempts_reached': True})}\n\n"
                
                # Update files and summary if tests resulted in fixes
                if current_files != files:
                    files = current_files
                    summary = current_summary
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Saving version...'})}\n\n"
            
            # Create version
            version = Version(
                project_id=project_id,
                version_number=new_version_number,
                prompt=request.prompt,
                files=[VersionFile(**f) for f in files],
                status="success",
                delta_plan={"summary": summary, "test_results": test_results}
            )
            await database.create_version(version.model_dump())
            
            # Update project
            await database.update_project(project_id, {
                "current_version": new_version_number,
                "summary": summary or project.get("summary", ""),
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
            
            # Save assistant message
            test_status_msg = ""
            if test_results:
                if test_results["status"] == "PASS":
                    test_status_msg = f" (✅ All {test_results.get('total', 0)} tests passed)"
                else:
                    test_status_msg = f" (⚠️ {test_results.get('failed', 0)} tests failed)"
            
            assistant_msg = ChatMessage(
                project_id=project_id,
                role="assistant",
                content=f"✓ {summary or 'Code generated successfully'}{test_status_msg}"
            )
            await database.create_message(assistant_msg.model_dump())
            
            # AUTO-RUN MIGRATIONS AND DEPLOY FUNCTIONS (if Supabase connected)
            migration_result = None
            deploy_result = None
            
            if is_fullstack:
                # Check for SQL migrations
                sql_files = [f for f in files if f.get("file_type") == "sql" or f.get("path", "").endswith(".sql")]
                edge_functions = [f for f in files if f.get("file_type") == "edge_function" or "supabase/functions" in f.get("path", "")]
                
                # AUTO-RUN MIGRATIONS (now automatic after code validation passes)
                if sql_files:
                    yield f"data: {json.dumps({'type': 'status', 'message': '🗄️ Running database migrations automatically...'})}\n\n"
                    
                    migration_result = await run_migrations_internal(project_id, files)
                    
                    if migration_result.get("status") == "completed":
                        success_count = migration_result.get("success", 0)
                        status_msg = f"✅ {success_count} migration(s) executed successfully!"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'migration_result', 'status': 'success', 'results': migration_result})}\n\n"
                    elif migration_result.get("status") == "partial":
                        success_count = migration_result.get("success", 0)
                        pending_count = migration_result.get("pending", 0)
                        status_msg = f"⚠️ {success_count} migration(s) executed, {pending_count} pending manual execution"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'migration_result', 'status': 'partial', 'results': migration_result})}\n\n"
                    elif migration_result.get("status") == "pending":
                        sql_editor_url = migration_result.get("sql_editor_url", "")
                        status_msg = f"📝 Migrations ready for manual execution"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'migration_result', 'status': 'pending', 'results': migration_result, 'sql_editor_url': sql_editor_url})}\n\n"
                    elif migration_result.get("status") == "skipped":
                        skip_reason = migration_result.get("message", "")
                        status_msg = f"ℹ️ Migrations skipped: {skip_reason}"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                    else:
                        error_msg = migration_result.get("message", "Unknown error")
                        status_msg = f"❌ Migration error: {error_msg}"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'migration_result', 'status': 'error', 'message': error_msg})}\n\n"
                
                # AUTO-DEPLOY EDGE FUNCTIONS
                if edge_functions:
                    yield f"data: {json.dumps({'type': 'status', 'message': '⚡ Deploying Edge Functions automatically...'})}\n\n"
                    deploy_result = await deploy_edge_functions_internal(project_id, files)
                    
                    if deploy_result.get("status") == "deployed":
                        func_count = deploy_result.get("success", deploy_result.get("total", 0))
                        status_msg = f"✅ {func_count} Edge Function(s) deployed successfully!"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'deploy_result', 'status': 'deployed', 'results': deploy_result})}\n\n"
                    elif deploy_result.get("status") == "ready":
                        func_count = deploy_result.get("total", 0)
                        status_msg = f"📦 {func_count} Edge Function(s) ready for manual deployment"
                        yield f"data: {json.dumps({'type': 'status', 'message': status_msg})}\n\n"
                        yield f"data: {json.dumps({'type': 'deploy_result', 'status': 'ready', 'results': deploy_result})}\n\n"
                    else:
                        error_msg = deploy_result.get("message", "Deployment failed")
                        yield f"data: {json.dumps({'type': 'status', 'message': f'❌ Edge Function error: {error_msg}'})}\n\n"
            
            # Send final result with migration/deploy/test info
            final_result = {
                'type': 'complete', 
                'version': new_version_number, 
                'files': files, 
                'summary': summary
            }
            if migration_result:
                final_result['migration'] = migration_result
            if deploy_result:
                final_result['deployment'] = deploy_result
            if test_results:
                final_result['test_results'] = test_results
                
            yield f"data: {json.dumps(final_result)}\n\n"
            
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

@api_router.get("/projects/{project_id}/export")
async def export_project_zip(project_id: str):
    """Export project as a downloadable ZIP file ready for Vercel/Netlify deployment"""
    
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    version = await database.get_latest_version(project_id)
    if not version or not version.get("files"):
        raise HTTPException(status_code=404, detail="No code to export")
    
    # Get Supabase config
    supabase_url = project.get("supabase_url", "YOUR_SUPABASE_URL")
    supabase_anon_key = project.get("supabase_anon_key", "YOUR_SUPABASE_ANON_KEY")
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    
    project_name = project.get("name", "app").lower().replace(" ", "-")
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add frontend files
        for f in version["files"]:
            file_type = f.get("file_type", "frontend")
            path = f.get("path", "")
            content = f.get("content", "")
            
            if file_type == "frontend" or path.endswith(".jsx"):
                # Put frontend files in src/
                zf.writestr(f"src/{path}", content)
            elif file_type == "edge_function" or "supabase/functions" in path:
                # Keep edge functions in supabase/ folder
                zf.writestr(path, content)
            elif file_type == "sql" or path.endswith(".sql"):
                # Keep SQL migrations in supabase/ folder
                zf.writestr(path, content)
        
        # Add package.json for React app
        package_json = {
            "name": project_name,
            "version": "1.0.0",
            "private": True,
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0",
                "react-scripts": "5.0.1",
                "@supabase/supabase-js": "^2.39.0"
            },
            "scripts": {
                "start": "react-scripts start",
                "build": "react-scripts build",
                "test": "react-scripts test",
                "eject": "react-scripts eject"
            },
            "browserslist": {
                "production": [">0.2%", "not dead", "not op_mini all"],
                "development": ["last 1 chrome version", "last 1 firefox version", "last 1 safari version"]
            }
        }
        zf.writestr("package.json", json.dumps(package_json, indent=2))
        
        # Add .env.example
        env_example = f"""# Supabase Configuration
REACT_APP_SUPABASE_URL={supabase_url}
REACT_APP_SUPABASE_ANON_KEY={supabase_anon_key}
"""
        zf.writestr(".env.example", env_example)
        zf.writestr(".env", env_example)  # Also include actual .env
        
        # Add index.html
        index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#000000" />
    <title>""" + project.get("name", "App") + """</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <noscript>You need to enable JavaScript to run this app.</noscript>
    <div id="root"></div>
</body>
</html>"""
        zf.writestr("public/index.html", index_html)
        
        # Add src/index.js
        index_js = """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
"""
        zf.writestr("src/index.js", index_js)
        
        # Add README with deployment instructions
        readme = f"""# {project.get("name", "App")}

Generated by App Builder

## Quick Start

1. Install dependencies:
   ```bash
   npm install
   ```

2. Set up environment variables:
   - Copy `.env.example` to `.env`
   - Update Supabase credentials if needed

3. Run locally:
   ```bash
   npm start
   ```

## Deploy to Vercel

1. Push this folder to a GitHub repository
2. Go to [vercel.com](https://vercel.com) and import your repo
3. Add environment variables in Vercel dashboard:
   - `REACT_APP_SUPABASE_URL`
   - `REACT_APP_SUPABASE_ANON_KEY`
4. Deploy!

## Deploy to Netlify

1. Push this folder to a GitHub repository
2. Go to [netlify.com](https://netlify.com) and import your repo
3. Set build command: `npm run build`
4. Set publish directory: `build`
5. Add environment variables in Netlify dashboard
6. Deploy!

## Supabase Setup

If you haven't already, run the SQL migration in your Supabase dashboard:
- Go to SQL Editor
- Paste contents of `supabase/migrations/*.sql`
- Run the query

## Files Structure

- `src/` - React frontend code
- `supabase/functions/` - Supabase Edge Functions (deploy via Supabase CLI)
- `supabase/migrations/` - Database schema (run in Supabase SQL Editor)
"""
        zf.writestr("README.md", readme)
        
        # Add .gitignore
        gitignore = """node_modules/
build/
.env
.env.local
.DS_Store
"""
        zf.writestr(".gitignore", gitignore)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={project_name}.zip"
        }
    )

@api_router.post("/projects/{project_id}/sandbox")
async def create_codesandbox(project_id: str):
    """Create a CodeSandbox from the project code"""
    
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    version = await database.get_latest_version(project_id)
    if not version or not version.get("files"):
        raise HTTPException(status_code=404, detail="No code to export")
    
    # Get Supabase config
    supabase_url = project.get("supabase_url", "")
    supabase_anon_key = project.get("supabase_anon_key", "")
    
    # Build files for CodeSandbox
    sandbox_files = {}
    
    # Add frontend files
    for f in version["files"]:
        file_type = f.get("file_type", "frontend")
        path = f.get("path", "")
        content = f.get("content", "")
        
        if file_type == "frontend" or path.endswith(".jsx"):
            # CodeSandbox uses src/ prefix
            sandbox_files[f"src/{path}"] = {"content": content}
    
    # Add package.json
    package_json = {
        "name": project.get("name", "app").lower().replace(" ", "-"),
        "version": "1.0.0",
        "main": "src/index.js",
        "dependencies": {
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "react-scripts": "5.0.1",
            "@supabase/supabase-js": "^2.39.0"
        },
        "scripts": {
            "start": "react-scripts start",
            "build": "react-scripts build"
        }
    }
    sandbox_files["package.json"] = {"content": json.dumps(package_json, indent=2)}
    
    # Add index.html
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{project.get("name", "App")}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <div id="root"></div>
</body>
</html>"""
    sandbox_files["public/index.html"] = {"content": index_html}
    
    # Add src/index.js
    index_js = f"""import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

// Supabase config (injected)
window.SUPABASE_URL = '{supabase_url}';
window.SUPABASE_ANON_KEY = '{supabase_anon_key}';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
"""
    sandbox_files["src/index.js"] = {"content": index_js}
    
    # Create the parameters object for CodeSandbox
    parameters = {"files": sandbox_files}
    
    # Use CodeSandbox define API
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://codesandbox.io/api/v1/sandboxes/define?json=1",
            json=parameters,
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code != 200:
            logger.error(f"CodeSandbox error: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to create sandbox")
        
        result = response.json()
        sandbox_id = result.get("sandbox_id")
        
        return {
            "sandbox_id": sandbox_id,
            "url": f"https://codesandbox.io/s/{sandbox_id}",
            "embed_url": f"https://codesandbox.io/embed/{sandbox_id}?fontsize=14&theme=dark&view=preview"
        }

@api_router.post("/projects/{project_id}/deploy/vercel")
async def deploy_to_vercel(project_id: str, request: VercelDeployRequest):
    """Deploy project directly to Vercel"""
    import hashlib
    import base64
    
    project = await database.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    version = await database.get_latest_version(project_id)
    if not version or not version.get("files"):
        raise HTTPException(status_code=404, detail="No code to deploy")
    
    # Get Supabase config
    supabase_url = project.get("supabase_url", "")
    supabase_anon_key = project.get("supabase_anon_key", "")
    
    project_name = request.project_name or project.get("name", "app").lower().replace(" ", "-").replace("(", "").replace(")", "")
    
    # Build files for Vercel deployment
    vercel_files = []
    
    # Add frontend files
    for f in version["files"]:
        file_type = f.get("file_type", "frontend")
        path = f.get("path", "")
        content = f.get("content", "")
        
        if file_type == "frontend" or path.endswith(".jsx"):
            vercel_files.append({
                "file": f"src/{path}",
                "data": content
            })
        elif file_type == "sql" or path.endswith(".sql"):
            # Include SQL for reference
            vercel_files.append({
                "file": path if path.startswith("supabase/") else f"supabase/migrations/{path}",
                "data": content
            })
    
    # Add package.json
    package_json = json.dumps({
        "name": project_name,
        "version": "1.0.0",
        "private": True,
        "dependencies": {
            "react": "^18.2.0",
            "react-dom": "^18.2.0",
            "react-scripts": "5.0.1",
            "@supabase/supabase-js": "^2.39.0"
        },
        "scripts": {
            "start": "react-scripts start",
            "build": "react-scripts build"
        },
        "browserslist": {
            "production": [">0.2%", "not dead"],
            "development": ["last 1 chrome version"]
        }
    }, indent=2)
    vercel_files.append({"file": "package.json", "data": package_json})
    
    # Add index.html
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{project.get("name", "App")}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
    <div id="root"></div>
</body>
</html>"""
    vercel_files.append({"file": "public/index.html", "data": index_html})
    
    # Add src/index.js
    index_js = """import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
"""
    vercel_files.append({"file": "src/index.js", "data": index_js})
    
    # Prepare Vercel API request
    vercel_payload = {
        "name": project_name,
        "files": vercel_files,
        "projectSettings": {
            "framework": "create-react-app",
            "buildCommand": "npm run build",
            "outputDirectory": "build"
        },
        "target": "production"
    }
    
    # Add environment variables if Supabase is connected
    if supabase_url and supabase_anon_key:
        vercel_payload["env"] = {
            "REACT_APP_SUPABASE_URL": supabase_url,
            "REACT_APP_SUPABASE_ANON_KEY": supabase_anon_key
        }
    
    # Deploy to Vercel
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            "https://api.vercel.com/v13/deployments",
            json=vercel_payload,
            headers={
                "Authorization": f"Bearer {request.vercel_token}",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code not in [200, 201]:
            error_detail = response.json() if response.text else "Unknown error"
            logger.error(f"Vercel deployment failed: {error_detail}")
            raise HTTPException(status_code=400, detail=f"Vercel deployment failed: {error_detail}")
        
        result = response.json()
        
        # Save deployment info to project
        await database.update_project(project_id, {
            "vercel_deployment_url": f"https://{result.get('url', '')}",
            "vercel_project_id": result.get('projectId'),
            "last_deployed": datetime.now(timezone.utc).isoformat()
        })
        
        return {
            "success": True,
            "url": f"https://{result.get('url', '')}",
            "projectId": result.get("projectId"),
            "deploymentId": result.get("id"),
            "status": result.get("readyState", "BUILDING")
        }

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
    
    # Remove import statements (general)
    cleaned = re.sub(r'^import\s+.*?[\'"].*?[\'"];?\s*$', '', code, flags=re.MULTILINE)
    cleaned = re.sub(r'^import\s+\{[^}]*\}\s+from\s+[\'"].*?[\'"];?\s*$', '', cleaned, flags=re.MULTILINE)
    
    # Remove export statements but keep the content
    cleaned = re.sub(r'^export\s+default\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^export\s+', '', cleaned, flags=re.MULTILINE)
    
    # Remove Supabase client initialization - we provide our own with correct credentials
    # Remove: const supabaseUrl = '...'
    cleaned = re.sub(r"const supabaseUrl\s*=\s*['\"][^'\"]*['\"];?\s*\n?", '', cleaned)
    # Remove: const supabaseAnonKey = '...'
    cleaned = re.sub(r"const supabaseAnonKey\s*=\s*['\"][^'\"]*['\"];?\s*\n?", '', cleaned)
    # Remove: const supabase = createClient(...)
    cleaned = re.sub(r"const supabase\s*=\s*createClient\([^)]*\);?\s*\n?", '', cleaned)
    # Remove: const supabaseClient = createClient(...)
    cleaned = re.sub(r"const supabaseClient\s*=\s*createClient\([^)]*\);?\s*\n?", '', cleaned)
    # Remove: export const supabase = createClient(...)
    cleaned = re.sub(r"export\s+const\s+supabase\s*=\s*createClient\([^)]*\);?\s*\n?", '', cleaned)
    
    # Escape script closing tags
    cleaned = cleaned.replace("</script>", "<\\/script>")
    
    return cleaned.strip()

def is_supabase_client_file(file_path: str, content: str) -> bool:
    """Check if a file is the supabaseClient configuration file"""
    if 'supabaseClient' in file_path.lower():
        return True
    # Check content for patterns like export const supabase = createClient
    if 'createClient' in content and ('export const supabase' in content or 'export const supabaseClient' in content):
        return True
    return False

def generate_preview_html_multifile(files: list, supabase_config: dict = None) -> str:
    """Generate HTML with multiple React components for preview"""
    
    # Check if this is a full-stack app (has Supabase files)
    has_supabase = any('supabase' in f.get('path', '').lower() or '@supabase' in f.get('content', '') for f in files)
    
    # Sort files: components first, then App.jsx last (so it can use components)
    # Skip non-frontend files (edge functions, sql) AND supabaseClient files for preview
    sorted_files = []
    app_file = None
    
    for f in files:
        file_path = f.get("path", "")
        file_content = f.get("content", "")
        file_type = f.get("file_type", "frontend")
        
        # Skip non-frontend files
        if file_type in ["edge_function", "sql"]:
            continue
        if file_path.endswith(".ts") or file_path.endswith(".sql"):
            continue
        
        # Skip .env files - they are not JavaScript
        if ".env" in file_path:
            continue
        
        # Skip non-JSX/JS files that might have been incorrectly marked as frontend
        if not (file_path.endswith(".jsx") or file_path.endswith(".js") or file_path.endswith(".tsx")):
            continue
        
        # CRITICAL: Skip supabaseClient.js - we provide our own with correct credentials
        # BUT never skip App.jsx - it's the main app file even if it creates supabase client
        if is_supabase_client_file(file_path, file_content) and file_path != "App.jsx" and not file_path.endswith("/App.jsx"):
            continue
        
        # Identify App.jsx and ensure it's added last for proper component resolution
        if file_path == "App.jsx" or file_path.endswith("/App.jsx"):
            app_file = f
        else:
            sorted_files.append(f)
    
    if app_file:
        sorted_files.append(app_file)
    elif files:
        # If no App.jsx found, use frontend files only (with proper filtering)
        sorted_files = [f for f in files 
                        if f.get("file_type", "frontend") == "frontend" 
                        and not is_supabase_client_file(f.get("path", ""), f.get("content", ""))
                        and ".env" not in f.get("path", "")
                        and (f.get("path", "").endswith(".jsx") or f.get("path", "").endswith(".js") or f.get("path", "").endswith(".tsx"))]
    
    # Build all component code - with duplicate detection
    all_code_parts = []
    defined_components = set()  # Track component names already defined
    
    for f in sorted_files:
        # Double-check: skip any .env files that somehow got through
        if ".env" in f.get("path", ""):
            continue
        
        file_path = f.get("path", "")
        cleaned = clean_component_code(f["content"])
        
        # Extract component name from file path (e.g., Header.jsx -> Header)
        component_name = None
        if file_path.endswith(".jsx") or file_path.endswith(".tsx"):
            # Get filename without extension
            filename = file_path.split("/")[-1]
            component_name = filename.replace(".jsx", "").replace(".tsx", "")
        
        # Check if this component is already defined (duplicate detection)
        if component_name and component_name != "App":
            if component_name in defined_components:
                logger.warning(f"Skipping duplicate component: {component_name} from {file_path}")
                continue
            defined_components.add(component_name)
        
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
        // Supabase client setup for preview - CORRECT credentials from connected project
        const {{ createClient }} = supabase;
        
        // CORRECT Supabase credentials from connected project
        const SUPABASE_URL = '{sb_url}';
        const SUPABASE_ANON_KEY = '{sb_key}';
        
        // Create the official Supabase client with CORRECT credentials
        // This replaces any supabaseClient.js that was skipped
        const supabaseClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
        
        // CRITICAL: Also expose as 'supabase' - this is what App.jsx imports
        const supabase = supabaseClient;
        
        // Mock process.env for preview
        if (typeof process === 'undefined') {{
            window.process = {{ env: {{
                REACT_APP_SUPABASE_URL: SUPABASE_URL,
                REACT_APP_SUPABASE_ANON_KEY: SUPABASE_ANON_KEY
            }} }};
        }}
        
        // Override any variables that might be used for Supabase config
        const supabaseUrl = SUPABASE_URL;
        const supabaseAnonKey = SUPABASE_ANON_KEY;
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
        
        // Mock Lucide Icons (common icons used in generated code)
        const createIcon = (path) => ({ className = "", size = 24, ...props }) => (
            <svg xmlns="http://www.w3.org/2000/svg" width={size} height={size} viewBox="0 0 24 24" fill="none" 
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" 
                 className={className} {...props}>
                {path}
            </svg>
        );
        
        // Common Lucide icons
        const Plus = createIcon(<><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></>);
        const Minus = createIcon(<line x1="5" y1="12" x2="19" y2="12"/>);
        const X = createIcon(<><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>);
        const Check = createIcon(<polyline points="20 6 9 17 4 12"/>);
        const Trash2 = createIcon(<><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></>);
        const Edit = createIcon(<><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>);
        const Search = createIcon(<><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>);
        const Menu = createIcon(<><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></>);
        const Home = createIcon(<><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></>);
        const User = createIcon(<><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>);
        const Settings = createIcon(<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></>);
        const Heart = createIcon(<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>);
        const Star = createIcon(<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>);
        const Calendar = createIcon(<><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></>);
        const Clock = createIcon(<><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></>);
        const Mail = createIcon(<><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></>);
        const Phone = createIcon(<><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></>);
        const LogOut = createIcon(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></>);
        const LogIn = createIcon(<><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></>);
        const Sun = createIcon(<><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></>);
        const Moon = createIcon(<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>);
        const ChevronRight = createIcon(<polyline points="9 18 15 12 9 6"/>);
        const ChevronLeft = createIcon(<polyline points="15 18 9 12 15 6"/>);
        const ChevronDown = createIcon(<polyline points="6 9 12 15 18 9"/>);
        const ChevronUp = createIcon(<polyline points="18 15 12 9 6 15"/>);
        const ArrowRight = createIcon(<><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></>);
        const ArrowLeft = createIcon(<><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></>);
        const Loader2 = createIcon(<><line x1="12" y1="2" x2="12" y2="6"/><line x1="12" y1="18" x2="12" y2="22"/><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"/><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"/><line x1="2" y1="12" x2="6" y2="12"/><line x1="18" y1="12" x2="22" y2="12"/><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"/><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"/></>);
        const RefreshCw = createIcon(<><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></>);
        const Calculator = createIcon(<><rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="6" x2="16" y2="6"/><line x1="8" y1="14" x2="8" y2="14"/><line x1="12" y1="14" x2="12" y2="14"/><line x1="16" y1="14" x2="16" y2="14"/><line x1="8" y1="18" x2="8" y2="18"/><line x1="12" y1="18" x2="12" y2="18"/><line x1="16" y1="18" x2="16" y2="18"/><line x1="8" y1="10" x2="16" y2="10"/></>);
        const Code = createIcon(<><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></>);
        const Download = createIcon(<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></>);
        const Upload = createIcon(<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></>);
        const Eye = createIcon(<><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></>);
        const EyeOff = createIcon(<><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></>);
        const Lock = createIcon(<><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></>);
        const Unlock = createIcon(<><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></>);
        const AlertCircle = createIcon(<><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>);
        const CheckCircle = createIcon(<><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></>);
        const Info = createIcon(<><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></>);
        const RotateCcw = createIcon(<><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></>);
        const MousePointer = createIcon(<><path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/><path d="M13 13l6 6"/></>);
        const TrendingUp = createIcon(<><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></>);
        const TrendingDown = createIcon(<><polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/></>);
        const Database = createIcon(<><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></>);
        const Zap = createIcon(<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>);
        const Play = createIcon(<polygon points="5 3 19 12 5 21 5 3"/>);
        const Pause = createIcon(<><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></>);
        const SkipForward = createIcon(<><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/></>);
        const SkipBack = createIcon(<><polygon points="19 20 9 12 19 4 19 20"/><line x1="5" y1="19" x2="5" y2="5"/></>);
        const Volume2 = createIcon(<><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></>);
        const VolumeX = createIcon(<><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></>);
        const FileText = createIcon(<><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></>);
        const Folder = createIcon(<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>);
        const Image = createIcon(<><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></>);
        const Send = createIcon(<><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></>);
        const MessageCircle = createIcon(<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>);
        const Bell = createIcon(<><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></>);
        const Share2 = createIcon(<><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></>);
        const Copy = createIcon(<><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></>);
        const Clipboard = createIcon(<><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></>);
        const Filter = createIcon(<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>);
        const MoreHorizontal = createIcon(<><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></>);
        const MoreVertical = createIcon(<><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></>);
        const ExternalLink = createIcon(<><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></>);
        const Link = createIcon(<><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></>);
        const Globe = createIcon(<><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></>);
        const MapPin = createIcon(<><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></>);
        const Briefcase = createIcon(<><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></>);
        const Award = createIcon(<><circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/></>);
        const Gift = createIcon(<><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></>);
        const ShoppingCart = createIcon(<><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></>);
        const CreditCard = createIcon(<><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></>);
        const DollarSign = createIcon(<><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></>);
        const Percent = createIcon(<><line x1="19" y1="5" x2="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/></>);
        const Tag = createIcon(<><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></>);
        const Bookmark = createIcon(<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>);
        const Flag = createIcon(<><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></>);
        const Layers = createIcon(<><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></>);
        const Box = createIcon(<><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></>);
        const Package = createIcon(<><line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></>);
        const Truck = createIcon(<><rect x="1" y="3" width="15" height="13"/><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/></>);
        const Activity = createIcon(<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>);
        const BarChart = createIcon(<><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></>);
        const PieChart = createIcon(<><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></>);
        const Target = createIcon(<><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></>);
        const Crosshair = createIcon(<><circle cx="12" cy="12" r="10"/><line x1="22" y1="12" x2="18" y2="12"/><line x1="6" y1="12" x2="2" y2="12"/><line x1="12" y1="6" x2="12" y2="2"/><line x1="12" y1="22" x2="12" y2="18"/></>);
        const Compass = createIcon(<><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></>);
        const Navigation = createIcon(<polygon points="3 11 22 2 13 21 11 13 3 11"/>);
        const Bot = createIcon(<><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></>);
        const Sparkles = createIcon(<><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/><path d="M5 3v4"/><path d="M19 17v4"/><path d="M3 5h4"/><path d="M17 19h4"/></>);
        const Wand2 = createIcon(<><path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72Z"/><path d="m14 7 3 3"/><path d="M5 6v4"/><path d="M19 14v4"/><path d="M10 2v2"/><path d="M7 8H3"/><path d="M21 16h-4"/><path d="M11 3H9"/></>);
        const Github = createIcon(<><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></>);
        const Twitter = createIcon(<path d="M22 4s-.7 2.1-2 3.4c1.6 10-9.4 17.3-18 11.6 2.2.1 4.4-.6 6-2C3 15.5.5 9.6 3 5c2.2 2.6 5.6 4.1 9 4-.9-4.2 4-6.6 7-3.8 1.1 0 3-1.2 3-1.2z"/>);
        const Linkedin = createIcon(<><path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/></>);
        const Instagram = createIcon(<><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/></>);
        const Facebook = createIcon(<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/>);
        const Youtube = createIcon(<><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"/><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"/></>);
        const Wifi = createIcon(<><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></>);
        const WifiOff = createIcon(<><line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.58 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></>);
        const Bluetooth = createIcon(<><polyline points="6.5 6.5 17.5 17.5 12 23 12 1 17.5 6.5 6.5 17.5"/></>);
        const Battery = createIcon(<><rect x="1" y="6" width="18" height="12" rx="2" ry="2"/><line x1="23" y1="13" x2="23" y2="11"/></>);
        const BatteryCharging = createIcon(<><path d="M5 18H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3.19M15 6h2a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-3.19"/><line x1="23" y1="13" x2="23" y2="11"/><polyline points="11 6 7 12 13 12 9 18"/></>);
        const Printer = createIcon(<><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></>);
        const Mic = createIcon(<><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></>);
        const MicOff = createIcon(<><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></>);
        const Camera = createIcon(<><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></>);
        const CameraOff = createIcon(<><line x1="1" y1="1" x2="23" y2="23"/><path d="M21 21H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3m3-3h6l2 3h4a2 2 0 0 1 2 2v9.34m-7.72-2.06a4 4 0 1 1-5.56-5.56"/></>);
        const Video = createIcon(<><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></>);
        const VideoOff = createIcon(<><path d="M16 16v1a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2m5.66 0H14a2 2 0 0 1 2 2v3.34l1 1L23 7v10"/><line x1="1" y1="1" x2="23" y2="23"/></>);
        const Headphones = createIcon(<><path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/></>);
        const Music = createIcon(<><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></>);
        const Radio = createIcon(<><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14"/></>);
        const Tv = createIcon(<><rect x="2" y="7" width="20" height="15" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/></>);
        const Monitor = createIcon(<><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></>);
        const Smartphone = createIcon(<><rect x="5" y="2" width="14" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></>);
        const Tablet = createIcon(<><rect x="4" y="2" width="16" height="20" rx="2" ry="2"/><line x1="12" y1="18" x2="12.01" y2="18"/></>);
        const Laptop = createIcon(<><path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.28 2.55a1 1 0 0 1-.9 1.45H3.62a1 1 0 0 1-.9-1.45L4 16"/></>);
        const Server = createIcon(<><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></>);
        const HardDrive = createIcon(<><line x1="22" y1="12" x2="2" y2="12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/><line x1="6" y1="16" x2="6.01" y2="16"/><line x1="10" y1="16" x2="10.01" y2="16"/></>);
        const Cpu = createIcon(<><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></>);
        const Terminal = createIcon(<><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></>);
        const Hash = createIcon(<><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></>);
        const AtSign = createIcon(<><circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-3.92 7.94"/></>);
        
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
    global database, testing_agent, clarification_agent
    database = get_database()
    await database.init()
    logger.info(f"Database initialized: {os.environ.get('DB_TYPE', 'mongodb')}")
    
    # Initialize agents
    if OPENROUTER_API_KEY:
        testing_agent = TestingAgent(OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
        clarification_agent = ClarificationAgent(OPENROUTER_API_KEY, OPENROUTER_BASE_URL)
        logger.info("Testing Agent and Clarification Agent initialized")

@app.on_event("shutdown")
async def shutdown_db_client():
    if database:
        await database.close()

