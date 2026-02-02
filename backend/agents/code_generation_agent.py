"""
Code Generation Agent - Generates React + Supabase code
Creates frontend components, backend Edge Functions, and SQL migrations
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
import httpx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert full-stack developer specializing in React + Supabase applications.

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
        is_update: bool = False
    ) -> Dict:
        """
        Generate complete application code based on requirements.
        Returns files, summary, and metadata.
        """
        
        # Build the generation prompt
        prompt = self._build_generation_prompt(requirements, supabase_config, existing_files, is_update)
        
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 16000,
                        "temperature": 0.7
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Code generation API error: {response.text}")
                    raise Exception(f"Code generation failed: {response.status_code}")
                
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                
                # Parse the response
                return self._parse_generation_response(content)
                    
        except Exception as e:
            logger.error(f"Code generation error: {e}")
            raise
    
    async def generate_code_stream(
        self, 
        requirements: Dict,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False
    ) -> AsyncGenerator[str, None]:
        """
        Stream code generation for real-time UI updates.
        Yields chunks of generated code.
        """
        
        prompt = self._build_generation_prompt(requirements, supabase_config, existing_files, is_update)
        
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
                        "model": "anthropic/claude-sonnet-4",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
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
        is_update: bool = False
    ) -> str:
        """Build the prompt for code generation"""
        
        req_list = "\n".join([
            f"- [{r['id']}] ({r['category']}) {r['description']} [Priority: {r['priority']}]"
            for r in requirements.get("requirements", [])
        ])
        
        schema_info = ""
        if requirements.get("database_schema", {}).get("tables"):
            tables = requirements["database_schema"]["tables"]
            schema_info = "DATABASE SCHEMA TO CREATE:\n"
            for table in tables:
                cols = ", ".join([f"{c['name']} {c['type']}" for c in table.get("columns", [])])
                schema_info += f"- {table['name']}: {cols}\n"
        
        pages_info = ", ".join(requirements.get("pages", ["Home"]))
        
        supabase_url = supabase_config.get("url", "YOUR_SUPABASE_URL")
        
        prompt = f"""Generate a complete React + Supabase application.

APP NAME: {requirements.get('app_name', 'My App')}
DESCRIPTION: {requirements.get('app_description', '')}

REQUIREMENTS:
{req_list}

{schema_info}

PAGES TO CREATE: {pages_info}

SUPABASE PROJECT URL: {supabase_url}

Generate ALL necessary files including:
1. React components with Supabase data fetching
2. SQL migrations for the database schema (with RLS policies)
3. Edge Functions if complex backend logic is needed
4. Supabase client configuration

Remember:
- NO mock data - connect directly to Supabase
- Include proper loading and error states
- Make responsive with Tailwind CSS
- Use Lucide React for icons
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
