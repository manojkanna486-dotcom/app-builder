"""
Code Generation Agent - Generates React + Supabase code
Creates frontend components, backend Edge Functions, and SQL migrations
"""

import json
import re
import logging
import sys
from typing import Dict, List, Optional, Any, AsyncGenerator
import httpx

from .model_config import get_model, get_model_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_SUPABASE = """You are an expert full-stack developer specializing in React + Supabase applications.

TECH STACK (FIXED):
- Frontend: React with Tailwind CSS, Lucide React icons
- Backend: Supabase (PostgreSQL + Edge Functions + Auth)
- No mock data - all data comes from Supabase

GENERATION RULES:
1. Create production-ready code that connects directly to Supabase
2. Include proper error handling and loading states
3. Use Supabase client for all data operations
4. Implement Row Level Security (RLS) in migrations
5. Make UI responsive (mobile-first)
6. Use modern React patterns (hooks, functional components)
7. Include proper TypeScript types in Edge Functions

FILE STRUCTURE:
- App.jsx: Main app component with routing
- components/: Reusable UI components
- hooks/: Custom React hooks for data fetching
- lib/supabase.js: Supabase client initialization
- supabase/migrations/: SQL migration files
- supabase/functions/: Edge Functions (Deno/TypeScript)

OUTPUT FORMAT - Return valid JSON:
{
    "files": [
        {
            "path": "filename.jsx or folder/filename.jsx",
            "content": "file content here",
            "file_type": "frontend|sql|edge_function"
        }
    ],
    "summary": "Brief description of what was built",
    "database_changes": ["List of tables/columns added or modified"],
    "edge_functions": ["List of edge functions created"]
}

IMPORTANT:
- ALWAYS create lib/supabase.js with client initialization
- ALWAYS create migration files for any database changes
- Use environment variables for Supabase URL and keys
- Include proper RLS policies in migrations
- Make all UI components responsive with Tailwind breakpoints
"""

SYSTEM_PROMPT_MOCK = """You are an elite frontend developer and UI/UX designer. Generate world-class React applications with stunning, modern interfaces.

IMPORTANT - MOCK DATA APPROACH:
Since no backend is connected, you MUST use realistic mock data:
1. Create a data/mockData.js file with realistic sample data
2. Use useState to manage the mock data
3. Implement full CRUD operations on the mock data (add, edit, delete work locally)
4. Design the data structure to easily connect to a real database later

MOCK DATA EXAMPLE:
```javascript
// In data/mockData.js
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

CRITICAL: Return ONLY raw JSON. No markdown code blocks. ALL layouts MUST be responsive. ALL CRUD operations must work with mock data."""

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
        max_retries: int = 3,
        agent_context: Optional[str] = None
    ) -> Dict:
        """
        Generate complete application code based on requirements.
        Returns files, summary, and metadata.
        
        Args:
            requirements: Requirements dict
            supabase_config: Supabase configuration
            existing_files: Existing files (full codebase)
            is_update: Whether this is an update
            max_retries: Max retry attempts
            agent_context: Pre-built context (full codebase + schema + message history)
        """
        import sys
        
        # Build the generation prompt
        prompt = self._build_generation_prompt(requirements, supabase_config, existing_files, is_update, agent_context)
        
        logger.info(f"Code generation: Starting, prompt length: {len(prompt)} chars")
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
                    
                    # Choose system prompt based on Supabase connection
                    supabase_connected = supabase_config.get("url") and supabase_config.get("url") != "YOUR_SUPABASE_URL"
                    system_prompt = SYSTEM_PROMPT_SUPABASE if supabase_connected else SYSTEM_PROMPT_MOCK
                    
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
                                {"role": "user", "content": prompt}
                            ],
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
        agent_context: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Stream code generation for real-time UI updates.
        Yields chunks of generated code.
        """
        
        prompt = self._build_generation_prompt(requirements, supabase_config, existing_files, is_update, agent_context)
        
        # Choose system prompt based on Supabase connection
        supabase_connected = supabase_config.get("url") and supabase_config.get("url") != "YOUR_SUPABASE_URL"
        system_prompt = SYSTEM_PROMPT_SUPABASE if supabase_connected else SYSTEM_PROMPT_MOCK
        
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4-5",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
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
        agent_context: Optional[str] = None
    ) -> str:
        """Build the prompt for code generation
        
        Args:
            requirements: Requirements dict
            supabase_config: Supabase configuration
            existing_files: Existing files
            is_update: Whether this is an update
            agent_context: Pre-built context (includes full codebase if provided)
        """
        
        logger.info(f"Building generation prompt with requirements type: {type(requirements)}")
        
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
        
        # Check if Supabase is connected
        supabase_connected = supabase_config.get("url") and supabase_config.get("url") != "YOUR_SUPABASE_URL"
        supabase_url = supabase_config.get("url", "") if supabase_connected else ""
        
        if supabase_connected:
            # Full-stack mode with Supabase
            prompt = f"""Generate a complete React + Supabase application.

APP NAME: {requirements.get('app_name', 'My App')}
DESCRIPTION: {requirements.get('app_description', '')}

FEATURES/REQUIREMENTS:
{features_text}

{schema_info}
{permissions_info}

PAGES TO CREATE: {pages_info}

SUPABASE PROJECT URL: {supabase_url}

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
            
            # Add agent context (includes full codebase if provided)
            if agent_context:
                prompt = f"{agent_context}\n\n{prompt}"
        else:
            # Mock data mode - no Supabase
            prompt = f"""Generate a complete React application with mock data.

APP NAME: {requirements.get('app_name', 'My App')}
DESCRIPTION: {requirements.get('app_description', '')}

FEATURES/REQUIREMENTS:
{features_text}

{schema_info}
{permissions_info}

PAGES TO CREATE: {pages_info}

IMPORTANT - MOCK DATA APPROACH:
Since no backend is connected, you MUST use realistic mock data:
1. Create a data/mockData.js file with realistic sample data
2. Use useState to manage the mock data
3. Implement full CRUD operations on the mock data (add, edit, delete work locally)
4. Design the data structure to easily connect to a real database later

MOCK DATA EXAMPLE:
```javascript
// In data/mockData.js
export const initialTweets = [
  {{ id: 1, user: '@johndoe', content: 'Hello world!', likes: 42, createdAt: '2h' }},
  {{ id: 2, user: '@janedoe', content: 'Building amazing apps!', likes: 128, createdAt: '4h' }},
];
```

Generate ALL necessary files including:
1. React components with mock data (useState)
2. data/mockData.js file with realistic sample data
3. All UI components with Tailwind CSS styling
4. Full CRUD operations on mock data

Remember:
- Use mock data stored in data/mockData.js
- Use useState to manage data state
- Implement full CRUD operations (add, edit, delete) on mock data
- Include proper loading and error states (simulated)
- Make responsive with Tailwind CSS
- Use Lucide React for icons
- Design data structure to easily migrate to a database later
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
        
        # Check for required files
        has_supabase_client = any("supabase" in f["path"].lower() for f in files)
        has_app = any(f["path"] in ["App.jsx", "App.tsx", "app.jsx", "app.tsx"] for f in files)
        
        if not has_supabase_client:
            # Add default Supabase client
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
