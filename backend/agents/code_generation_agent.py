"""
Code Generation Agent - Generates React apps (frontend-only with mock data, or full-stack with Supabase)
"""

import json
import re
import logging
import sys
from typing import Dict, List, Optional, Any, AsyncGenerator
import httpx

from .model_config import get_model, get_model_settings

logger = logging.getLogger(__name__)

PREVIEW_RULES = """
=== PREVIEW RENDERING ENVIRONMENT (CRITICAL) ===
Your generated frontend code runs inside a browser iframe using Babel Standalone (NOT a bundler).
If you violate these rules, the preview will crash with errors or show a blank white screen.

1. NO IMPORT/EXPORT STATEMENTS in frontend files:
   - Do NOT write import statements - they are stripped before rendering.
   - Do NOT write export default or export - they are stripped.
   - All components share a single global scope.

2. AVAILABLE GLOBALS (already loaded, do NOT import them):
   - React hooks: useState, useEffect, useRef, useCallback, useMemo, useContext, createContext, useReducer
   - React Router (mocked): BrowserRouter, Routes, Route, Link, NavLink, useNavigate, useLocation, useParams
   - Lucide icons: Search, Home, User, Settings, Plus, Loader2, Loader, Spinner, etc. (use directly, e.g. <Loader2 className="animate-spin" />)
   - Tailwind CSS (via CDN)

3. MAIN COMPONENT MUST BE NAMED App (const App = () => { ... })

4. COMPONENT NAMING - AVOID COLLISIONS WITH LUCIDE ICONS:
   - Do NOT name components: Calculator, Calendar, Settings, Home, User, Search, Menu, Star, Heart, etc.
   - If you need such names, prefix them: MyCalculator, AppSettings, UserProfile, etc.
   - This is the #1 cause of preview crashes.

5. DO NOT USE: import.meta.env, require(), dynamic import(), CSS modules, TypeScript in .jsx
=== END PREVIEW RULES ===
"""

# Frontend-only: modern UI with mock data (no backend)
FRONTEND_ONLY_SYSTEM_PROMPT = """You are an expert React developer. Generate a MODERN, BEAUTIFUL frontend-only app with MOCK DATA.

MODE: FRONTEND ONLY - NO BACKEND.
- Do NOT use Supabase, APIs, or any backend. Ignore backend/database requirements.
- All data MUST be mock data: useState with initial arrays/objects in React.
- Create realistic sample data (e.g. a few todos, sample users, sample items) so the UI looks fully functional.
- Data lives only in React state; CRUD is add/update/delete in state.

UI: MODERN & POLISHED.
- Use Tailwind CSS with a cohesive, modern design (gradients, shadows, rounded corners, good spacing).
- Prefer a clean aesthetic: clear hierarchy, readable typography, consistent spacing (p-4, gap-4, etc.).
- Use Lucide icons for actions and navigation.
- Include loading states with Loader2 where appropriate (e.g. simulated delay with setTimeout).
- Mobile-first responsive: flex-col sm:flex-row, grid, responsive padding/margins.
- Use semantic colors: primary actions (blue/indigo), success (green), danger (red), neutral (gray).

FILE STRUCTURE (frontend only):
- App.jsx: Main app with routing (const App = () => {...}). Single file or split into logical components in same file.
- ONLY .jsx frontend files. NO lib/supabase.js, NO migrations, NO Edge Functions.

OUTPUT FORMAT - Return valid JSON only:
{
    "files": [
        {"path": "App.jsx", "content": "complete React code with mock data", "file_type": "frontend"}
    ],
    "summary": "Brief description",
    "database_changes": [],
    "edge_functions": []
}

RULES:
- NEVER use import/export in frontend files.
- NEVER name components same as Lucide icons (use AppHome, not Home; UserProfile, not User).
- Use className (not class). Match all braces/parens.
- For loading: <Loader2 className="animate-spin" />.
- Keep all code in one or a few .jsx files; mock data defined in component or at top of file.
""" + PREVIEW_RULES

# Full-stack (Supabase) - used only when backend is connected
SYSTEM_PROMPT = """You are an expert full-stack developer specializing in React + Supabase applications.

TECH STACK (FIXED):
- Frontend: React with Tailwind CSS, Lucide React icons
- Backend: Supabase (PostgreSQL + Edge Functions + Auth)
- No mock data - all data comes from Supabase
""" + PREVIEW_RULES + """
GENERATION RULES:
1. Create production-ready code that connects directly to Supabase
2. Include proper error handling and loading states
3. Use Supabase client for all data operations
4. Implement Row Level Security (RLS) in migrations
5. Make UI responsive (mobile-first)
6. Do NOT use import/export in frontend .jsx files

FILE STRUCTURE:
- App.jsx: Main app component with routing (const App = () => {...})
- components/: Reusable UI components
- lib/supabase.js: Supabase client initialization
- supabase/migrations/: SQL migration files
- supabase/functions/: Edge Functions (Deno/TypeScript)

OUTPUT FORMAT - Return valid JSON:
{
    "files": [
        {"path": "filename.jsx or folder/filename.jsx", "content": "...", "file_type": "frontend|sql|edge_function"}
    ],
    "summary": "Brief description",
    "database_changes": [],
    "edge_functions": []
}

IMPORTANT:
- ALWAYS create lib/supabase.js when using Supabase
- NEVER use import/export in frontend component files
- NEVER name components the same as Lucide icon names
- Use className (not class). Match all braces. Use Loader2 for loading states.
"""

class CodeGenerationAgent:
    """Agent that generates React + Supabase application code"""
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def generate_code(
        self,
        requirements: Dict,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False,
        agent_context: Optional[Dict] = None,
        test_cases: Optional[List[Dict]] = None,
        max_retries: int = 3,
        conversation_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Generate complete application code based on requirements.
        If test_cases are provided (TDD flow), build code to satisfy them.
        Returns files, summary, and metadata.
        """
        import sys
        
        # Frontend-only with mock data when no Supabase connected
        use_frontend_only = not (supabase_config and supabase_config.get("url"))
        prompt = self._build_generation_prompt(
            requirements, supabase_config, existing_files, is_update, test_cases,
            use_frontend_only=use_frontend_only
        )
        system_prompt = FRONTEND_ONLY_SYSTEM_PROMPT if use_frontend_only else SYSTEM_PROMPT
        
        logger.info(f"Code generation: Starting ({'frontend-only mock' if use_frontend_only else 'full-stack'}), prompt length: {len(prompt)} chars")
        sys.stderr.flush()
        
        last_error = None
        for attempt in range(max_retries):
            try:
                logger.info(f"Code generation: Attempt {attempt + 1}/{max_retries}")
                sys.stderr.flush()
                
                # Use a fresh client with explicit timeouts
                timeout = httpx.Timeout(10.0, connect=10.0, read=300.0, write=30.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    logger.info(f"Code generation: Sending POST to OpenRouter...")
                    sys.stderr.flush()
                    
                    # Use GPT-4o mini for frontend/UI code generation
                    model = get_model("code_generation_frontend")
                    settings = get_model_settings(model)
                    
                    # Build messages with conversation history
                    messages = [{"role": "system", "content": system_prompt}]
                    # Inject conversation history for context
                    if conversation_history:
                        for msg in conversation_history[-20:]:  # Last 20 messages to stay within context limits
                            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                    messages.append({"role": "user", "content": prompt})
                    
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model,
                            "messages": messages,
                            "max_tokens": settings["max_tokens"],
                            "temperature": settings["temperature"]
                        }
                    )
                    
                    # Immediately log after response
                    print(f"Code generation: Response received, status={response.status_code}", file=sys.stderr)
                    sys.stderr.flush()
                    
                    if response.status_code == 500:
                        last_error = f"OpenRouter server error (500)"
                        logger.warning(f"Code generation: OpenRouter 500 error, retrying in 3 seconds...")
                        import asyncio
                        await asyncio.sleep(3)
                        continue
                    
                    if response.status_code != 200:
                        logger.error(f"Code generation API error: {response.text}")
                        raise Exception(f"Code generation failed: {response.status_code}")
                    
                    # Parse JSON response
                    print(f"Code generation: Parsing JSON response...", file=sys.stderr)
                    sys.stderr.flush()
                    
                    data = response.json()
                    
                    print(f"Code generation: JSON parsed, extracting content...", file=sys.stderr)
                    sys.stderr.flush()
                    
                    content = data["choices"][0]["message"]["content"]
                    print(f"Code generation: Got content ({len(content)} chars), parsing files...", file=sys.stderr)
                    sys.stderr.flush()
                    
                    # Parse the response
                    result = self._parse_generation_response(content)
                    
                    print(f"Code generation: SUCCESS - {len(result.get('files', []))} files parsed", file=sys.stderr)
                    sys.stderr.flush()
                    
                    return result
                        
            except httpx.TimeoutException as e:
                logger.warning(f"Code generation: Timeout on attempt {attempt + 1}: {e}")
                last_error = f"Request timed out: {e}"
                import asyncio
                await asyncio.sleep(2)
                continue
            except Exception as e:
                logger.error(f"Code generation error: {e}")
                import traceback
                traceback.print_exc()
                raise
        
        # All retries failed
        raise Exception(f"Code generation failed after {max_retries} attempts: {last_error}")
    
    async def generate_code_stream(
        self,
        requirements: Dict,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False,
        agent_context: Optional[Dict] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream code generation for real-time UI updates.
        Yields chunks of generated code.
        """
        use_frontend_only = not (supabase_config and supabase_config.get("url"))
        prompt = self._build_generation_prompt(
            requirements, supabase_config, existing_files, is_update,
            test_cases=None,
            use_frontend_only=use_frontend_only
        )
        system_prompt = FRONTEND_ONLY_SYSTEM_PROMPT if use_frontend_only else SYSTEM_PROMPT
        
        try:
            # Build messages with conversation history
            messages = [{"role": "system", "content": system_prompt}]
            if conversation_history:
                for msg in conversation_history[-20:]:
                    messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            messages.append({"role": "user", "content": prompt})
            
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": messages,
                        "max_tokens": 16000,
                        "temperature": 0.7,
                        "stream": True
                    }
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        yield delta["content"]
                            except json.JSONDecodeError:
                                continue
                                
        except Exception as e:
            logger.error(f"Code generation stream error: {e}")
            raise
    
    def _build_generation_prompt(
        self, 
        requirements: Dict,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False,
        test_cases: Optional[List[Dict]] = None,
        use_frontend_only: bool = True,
    ) -> str:
        """Build the prompt for code generation. use_frontend_only=True => modern UI with mock data, no backend."""
        
        logger.info(f"Building generation prompt (frontend_only={use_frontend_only}), requirements type: {type(requirements)}")
        
        # Handle case where requirements might be stored differently
        if isinstance(requirements, str):
            logger.error(f"Requirements is a string: {requirements[:200]}")
            requirements = {"features": [], "app_name": "App", "app_description": "", "pages": []}
        
        # Build features/requirements list (support both old and new formats)
        features_text = ""
        
        # New format: features array
        features = requirements.get("features", [])
        if features and isinstance(features, list):
            for f in features:
                if isinstance(f, dict):
                    features_text += f"- [{f.get('id', 'N/A')}] {f.get('name', '')}: {f.get('description', '')} [Priority: {f.get('priority', 'medium')}]\n"
        
        # Old format: requirements array (backwards compatibility)
        reqs_list = requirements.get("requirements", [])
        if reqs_list and isinstance(reqs_list, list):
            for r in reqs_list:
                if isinstance(r, dict):
                    features_text += f"- [{r.get('id', 'N/A')}] ({r.get('category', 'feature')}) {r.get('description', '')} [Priority: {r.get('priority', 'medium')}]\n"
        
        # Build schema info (support both old and new formats)
        schema_info = ""
        
        # New format: data_models array
        data_models = requirements.get("data_models", [])
        if data_models and isinstance(data_models, list):
            schema_info = "DATABASE SCHEMA TO CREATE:\n"
            for model in data_models:
                if isinstance(model, dict):
                    model_name = model.get("name", "Unknown")
                    table_name = model.get("table_name", model_name.lower() + "s")
                    fields = model.get("fields", [])
                    cols = ", ".join([f"{c.get('name', 'col')} {c.get('type', 'text')}" for c in fields if isinstance(c, dict)])
                    schema_info += f"- {table_name} ({model_name}): {cols}\n"
                    
                    # Add RLS info if present
                    if model.get("rls_enabled", True):
                        schema_info += f"  (RLS enabled)\n"
        
        # Old format: database_schema.tables (backwards compatibility)
        if not schema_info and requirements.get("database_schema", {}).get("tables"):
            tables = requirements["database_schema"]["tables"]
            schema_info = "DATABASE SCHEMA TO CREATE:\n"
            for table in tables:
                if isinstance(table, dict):
                    cols = ", ".join([f"{c['name']} {c['type']}" for c in table.get("columns", []) if isinstance(c, dict)])
                    schema_info += f"- {table.get('name', 'table')}: {cols}\n"
        
        # Build pages info (support both old and new formats)
        pages = requirements.get("pages", [])
        if isinstance(pages, list):
            if pages and isinstance(pages[0], dict):
                # New format: pages as dicts with name, route, etc.
                pages_info = ", ".join([f"{p.get('name', 'Page')} ({p.get('route', '/')})" for p in pages if isinstance(p, dict)])
            else:
                # Old format: pages as strings
                pages_info = ", ".join([str(p) for p in pages])
        else:
            pages_info = "Home"
        
        # Build permissions/RLS info
        permissions_info = ""
        permissions = requirements.get("permissions", [])
        if permissions and isinstance(permissions, list):
            permissions_info = "\nROW LEVEL SECURITY POLICIES:\n"
            for perm in permissions:
                if isinstance(perm, dict):
                    permissions_info += f"- {perm.get('model', 'model')}: {perm.get('role', 'user')} can {', '.join(perm.get('actions', []))} where {perm.get('condition', 'true')}\n"
        
        supabase_url = supabase_config.get("url", "") if supabase_config else ""

        # Build acceptance test cases section (TDD - build to pass these tests)
        test_cases_block = ""
        if test_cases and len(test_cases) > 0:
            test_cases_block = "\nACCEPTANCE TESTS (Your code MUST satisfy these):\n"
            for i, tc in enumerate(test_cases[:15], 1):
                desc = tc.get("description", "")
                steps = tc.get("steps", [])
                expected = tc.get("expected", "")
                cat = tc.get("category", "")
                steps_str = " → ".join(steps) if steps else "See description"
                test_cases_block += f"{i}. [{cat}] {desc}\n   Steps: {steps_str}\n   Expected: {expected}\n"
            test_cases_block += "\nEnsure your implementation allows these user flows to succeed.\n"
        
        if use_frontend_only:
            # Modern UI, mock data only - no backend
            prompt = f"""Generate a MODERN, BEAUTIFUL frontend-only React app with MOCK DATA.

APP NAME: {requirements.get('app_name', 'My App')}
DESCRIPTION: {requirements.get('app_description', '')}

FEATURES TO IMPLEMENT (use mock data in React state - no backend):
{features_text}

PAGES/SCREENS: {pages_info}
{test_cases_block}

REQUIREMENTS:
- Use ONLY React state (useState) for all data. Create realistic mock data (e.g. sample list items, sample user) so the app looks fully functional.
- Modern UI: Tailwind with gradients, shadows, rounded corners, clear typography. Mobile-first responsive.
- Single App.jsx or App.jsx + a few component files. NO lib/supabase.js, NO SQL, NO Edge Functions.
- CRUD = add/update/delete in state. No API calls.
- Use Lucide icons (Loader2 for loading). No import/export in frontend files.
"""
        else:
            prompt = f"""Generate a complete React + Supabase application.

APP NAME: {requirements.get('app_name', 'My App')}
DESCRIPTION: {requirements.get('app_description', '')}

FEATURES/REQUIREMENTS:
{features_text}

{schema_info}
{permissions_info}

PAGES TO CREATE: {pages_info}

SUPABASE PROJECT URL: {supabase_url or 'YOUR_SUPABASE_URL'}
{test_cases_block}
Generate ALL necessary files including:
1. React components with Supabase data fetching
2. SQL migrations for the database schema (with RLS policies)
3. Supabase client configuration with auth helpers
4. All UI components with Tailwind CSS styling

Remember:
- NO mock data - connect directly to Supabase
- Include proper loading and error states  
- Make responsive with Tailwind CSS
- Use Lucide React for icons
- Include proper error handling
- Implement RLS policies for security
"""

        if is_update and existing_files:
            # For updates, include existing file structure
            file_list = "\n".join([f"- {f['path']}" for f in existing_files[:20]])
            prompt += f"\n\nEXISTING FILES:\n{file_list}\n\nUpdate the existing codebase to add the new requirements. Only return files that need to be changed or added."
        
        return prompt
    
    def _parse_generation_response(self, content: str) -> Dict:
        """Parse the LLM response into structured output"""
        
        # Try to extract JSON from the response
        json_match = re.search(r'\{[\s\S]*"files"[\s\S]*\}', content)
        if json_match:
            try:
                result = json.loads(json_match.group(), strict=False)
                return self._validate_and_enhance(result)
            except json.JSONDecodeError:
                pass
        
        # Fallback: try to extract file blocks
        files = self._extract_file_blocks(content)
        return {
            "files": files,
            "summary": "Generated application code",
            "database_changes": [],
            "edge_functions": []
        }
    
    def _extract_file_blocks(self, content: str) -> List[Dict]:
        """Extract file content from markdown code blocks"""
        files = []
        
        # Pattern for ```filename or ```language filename
        pattern = r'```(?:jsx?|tsx?|sql|typescript|javascript)?\s*\n?(?://\s*)?([^\n]+?\.(?:jsx?|tsx?|sql|ts|js))\n([\s\S]*?)```'
        matches = re.findall(pattern, content, re.IGNORECASE)
        
        for filename, code in matches:
            filename = filename.strip()
            file_type = "frontend"
            if filename.endswith(".sql"):
                file_type = "sql"
            elif "functions/" in filename or filename.endswith(".ts"):
                file_type = "edge_function"
            
            files.append({
                "path": filename,
                "content": code.strip(),
                "file_type": file_type
            })
        
        return files
    
    def _validate_and_enhance(self, result: Dict) -> Dict:
        """Validate and enhance the generation result"""
        
        files = result.get("files", [])
        
        # Ensure each file has proper type
        for f in files:
            path = f.get("path", "")
            if not f.get("file_type"):
                if ".sql" in path:
                    f["file_type"] = "sql"
                elif "functions/" in path or (path.endswith(".ts") and "supabase" in path.lower()):
                    f["file_type"] = "edge_function"
                else:
                    f["file_type"] = "frontend"
        
        # Only add Supabase client if this is a full-stack build (has SQL or Edge Functions)
        has_backend = any(f.get("file_type") in ("sql", "edge_function") for f in files)
        has_supabase_client = any("supabase" in f.get("path", "").lower() for f in files)
        
        if has_backend and not has_supabase_client:
            # Add default Supabase client only when backend is used
            files.append({
                "path": "lib/supabase.js",
                "content": """import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || process.env.REACT_APP_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || process.env.REACT_APP_SUPABASE_ANON_KEY;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export default supabase;
""",
                "file_type": "frontend"
            })
        
        result["files"] = files
        return result
