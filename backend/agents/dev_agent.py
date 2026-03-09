"""
Dev Agent - Fixes code issues identified by Testing Agent
Automatically fixes bugs up to MAX_RETRIES times
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
import httpx

logger = logging.getLogger(__name__)

FIX_SYSTEM_PROMPT = """You are an expert code fixer for React + Supabase applications.

Your job is to fix issues in generated code based on test failures.

PREVIEW RENDERING ENVIRONMENT:
The frontend code runs in a browser iframe using Babel Standalone (NOT a bundler).
- All import/export statements are STRIPPED before rendering - do NOT include them in frontend files.
- React hooks (useState, useEffect, etc.) and 160+ Lucide icons are available as globals.
- React Router is mocked (BrowserRouter, Routes, Route, Link, useNavigate, etc. are globals).
- The main component MUST be named App.
- Do NOT name components the same as Lucide icons (Calculator, Calendar, Home, Settings, User, etc.).
- import.meta.env is NOT supported.

RULES:
1. Only fix the issues reported - don't change working code
2. Maintain the existing code style and patterns
3. Ensure all Supabase connections work properly
4. Keep UI responsive and accessible
5. Fix syntax errors precisely
6. Do NOT include import/export statements in frontend files
7. Do NOT name components the same as Lucide icon names

OUTPUT FORMAT - Return ONLY the fixed files in JSON:
{
    "files": [
        {
            "path": "path/to/file.jsx",
            "content": "complete fixed file content",
            "file_type": "frontend|sql|edge_function"
        }
    ],
    "fixes_applied": ["description of fix 1", "description of fix 2"],
    "summary": "Brief summary of all fixes"
}

IMPORTANT:
- Return complete file content, not just diffs
- Only include files that were actually modified
- Preserve all existing functionality
- Do NOT use import/export in frontend component files
"""


class DevAgent:
    """Agent that fixes code issues based on test results"""
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def fix_issues(
        self,
        files: List[Dict],
        test_results: Dict,
        requirements: Dict,
        attempt: int = 1
    ) -> Dict:
        """
        Fix issues identified in test results.
        Returns updated files and fix summary.
        """
        
        issues = test_results.get("issues", [])
        if not issues:
            return {
                "files": files,
                "fixes_applied": [],
                "summary": "No issues to fix"
            }
        
        # Build fix prompt
        prompt = self._build_fix_prompt(files, issues, requirements, attempt)
        
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": FIX_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 16000,
                        "temperature": 0.3
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Dev Agent API error: {response.text}")
                    return {
                        "files": files,
                        "fixes_applied": [],
                        "summary": f"Fix attempt {attempt} failed: API error"
                    }
                
                content = response.json()["choices"][0]["message"]["content"]
                return self._parse_fix_response(content, files)
                
        except Exception as e:
            logger.error(f"Dev Agent error: {e}")
            return {
                "files": files,
                "fixes_applied": [],
                "summary": f"Fix attempt {attempt} failed: {str(e)}"
            }
    
    async def fix_issues_stream(
        self,
        files: List[Dict],
        test_results: Dict,
        requirements: Dict,
        attempt: int = 1
    ) -> AsyncGenerator[str, None]:
        """
        Stream fix generation for real-time UI updates.
        """
        
        issues = test_results.get("issues", [])
        if not issues:
            yield json.dumps({"type": "complete", "message": "No issues to fix"})
            return
        
        prompt = self._build_fix_prompt(files, issues, requirements, attempt)
        
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
                        "model": "openai/gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": FIX_SYSTEM_PROMPT},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 16000,
                        "temperature": 0.3,
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
            logger.error(f"Dev Agent stream error: {e}")
            yield json.dumps({"type": "error", "message": str(e)})
    
    def _build_fix_prompt(
        self,
        files: List[Dict],
        issues: List[Dict],
        requirements: Dict,
        attempt: int
    ) -> str:
        """Build the prompt for fixing issues"""
        
        # Format issues
        issues_text = "\n".join([
            f"- [{issue.get('req_id', 'UNKNOWN')}] {issue.get('description', '')}: {issue.get('error', 'Unknown error')}"
            for issue in issues
        ])
        
        # Format current files
        files_text = "\n\n".join([
            f"=== FILE: {f.get('path', 'unknown')} ===\n{f.get('content', '')}"
            for f in files
        ])
        
        # Format requirements for context
        req_text = "\n".join([
            f"- [{r.get('id', '')}] {r.get('description', '')}"
            for r in requirements.get("requirements", [])
        ])
        
        return f"""Fix the following issues in the code (Attempt {attempt}/3):

ISSUES TO FIX:
{issues_text}

REQUIREMENTS FOR CONTEXT:
{req_text}

CURRENT CODE FILES:
{files_text}

Fix ALL the issues listed above. Return the complete fixed files."""
    
    def _parse_fix_response(self, content: str, original_files: List[Dict]) -> Dict:
        """Parse the fix response from LLM"""
        
        # Try to extract JSON
        json_match = re.search(r'\{[\s\S]*"files"[\s\S]*\}', content)
        if json_match:
            try:
                result = json.loads(json_match.group(), strict=False)
                
                # Merge fixed files with original files
                fixed_paths = {f["path"] for f in result.get("files", [])}
                merged_files = result.get("files", [])
                
                # Keep original files that weren't modified
                for f in original_files:
                    if f["path"] not in fixed_paths:
                        merged_files.append(f)
                
                return {
                    "files": merged_files,
                    "fixes_applied": result.get("fixes_applied", []),
                    "summary": result.get("summary", "Fixes applied")
                }
            except json.JSONDecodeError:
                pass
        
        # Fallback: try to extract file blocks
        return {
            "files": original_files,
            "fixes_applied": [],
            "summary": "Could not parse fix response"
        }
    
    async def quick_fix_syntax(self, file_content: str, file_path: str, error: str) -> Optional[str]:
        """Quick fix for common syntax errors without full regeneration"""
        
        # Fix unbalanced braces
        open_braces = file_content.count("{")
        close_braces = file_content.count("}")
        
        if open_braces > close_braces:
            # Add missing closing braces
            diff = open_braces - close_braces
            file_content = file_content.rstrip() + "\n" + "}" * diff
            return file_content
        elif close_braces > open_braces:
            # Remove extra closing braces (more complex, skip for now)
            pass
        
        # Fix unbalanced parentheses
        open_parens = file_content.count("(")
        close_parens = file_content.count(")")
        
        if open_parens > close_parens:
            diff = open_parens - close_parens
            file_content = file_content.rstrip() + ")" * diff
            return file_content
        
        return None
