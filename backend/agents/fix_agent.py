"""
Fix Agent - Intelligent error fixing for generated applications
Uses context-aware prompts and multi-step reasoning to fix issues
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
import httpx

from .model_config import get_model, get_model_settings

logger = logging.getLogger(__name__)


class FixAgent:
    """
    Intelligent Fix Agent that can:
    1. Understand error messages and stack traces
    2. Analyze code to find root cause
    3. Apply targeted fixes without breaking existing functionality
    4. Handle user-reported errors with context
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def fix_user_error(
        self,
        files: List[Dict],
        error_message: str,
        user_context: Optional[str] = None,
        console_logs: Optional[str] = None,
        requirements: Optional[Dict] = None,
        agent_context: Optional[str] = None
    ) -> Dict:
        """
        Fix an error reported by the user.
        This is the main entry point for user-reported issues.
        
        Args:
            files: List of file dicts (full codebase)
            error_message: Error message to fix
            user_context: Additional user context
            console_logs: Console logs if available
            requirements: Requirements dict
            agent_context: Pre-built context (full codebase + schema + message history)
        """
        
        # Step 1: Analyze the error to understand what's wrong
        analysis = await self._analyze_error(error_message, console_logs, files, agent_context)
        
        # Step 2: Generate targeted fixes
        fixes = await self._generate_fixes(files, analysis, user_context, requirements, agent_context)
        
        return fixes
    
    async def _analyze_error(
        self,
        error_message: str,
        console_logs: Optional[str],
        files: List[Dict],
        agent_context: Optional[str] = None
    ) -> Dict:
        """Analyze error to understand root cause"""
        
        model = get_model("fix")
        settings = get_model_settings(model)
        
        # Use agent_context if provided (includes full codebase), otherwise build summary
        if agent_context:
            files_info = agent_context
        else:
            files_summary = "\n".join([
                f"- {f.get('path')}: {f.get('file_type', 'unknown')} ({len(f.get('content', ''))} chars)"
                for f in files
            ])
            files_info = f"FILES IN PROJECT:\n{files_summary}"
        
        prompt = f"""Analyze this error and identify the root cause.

ERROR MESSAGE:
{error_message}

{f"CONSOLE LOGS:{chr(10)}{console_logs}" if console_logs else ""}

{files_info}

Respond in JSON format:
{{
    "error_type": "syntax|runtime|logic|database|api|ui|other",
    "root_cause": "Brief explanation of what's causing the error",
    "likely_files": ["list", "of", "files", "to", "check"],
    "fix_strategy": "How to fix this issue",
    "severity": "critical|high|medium|low"
}}"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are an expert code debugger. Analyze errors precisely."},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 1000,
                        "temperature": 0.2
                    }
                )
                
                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        return json.loads(json_match.group())
                        
        except Exception as e:
            logger.error(f"Error analysis failed: {e}")
        
        # Default analysis if LLM fails
        return {
            "error_type": "unknown",
            "root_cause": error_message,
            "likely_files": [f.get("path") for f in files if f.get("file_type") == "frontend"][:3],
            "fix_strategy": "Review and fix the error",
            "severity": "high"
        }
    
    async def _generate_fixes(
        self,
        files: List[Dict],
        analysis: Dict,
        user_context: Optional[str],
        requirements: Optional[Dict],
        agent_context: Optional[str] = None
    ) -> Dict:
        """Generate code fixes based on analysis"""
        
        model = get_model("fix")
        settings = get_model_settings(model)
        
        # Get only relevant files for fixing
        likely_files = analysis.get("likely_files", [])
        relevant_files = [f for f in files if f.get("path") in likely_files]
        
        # If no specific files identified, include all frontend files
        if not relevant_files:
            relevant_files = [f for f in files if f.get("file_type") == "frontend"][:5]
        
        # Use agent_context if provided (includes full codebase), otherwise build from relevant files
        if agent_context:
            files_content = agent_context
        else:
            # Build the fix prompt with full context
            files_content = "\n\n".join([
                f"=== FILE: {f.get('path')} ===\n```\n{f.get('content', '')}\n```"
                for f in relevant_files
            ])
        
        system_prompt = """You are an expert React/JavaScript developer and debugger.
Your job is to fix bugs in generated code.

RULES:
1. Fix the SPECIFIC error mentioned - don't rewrite everything
2. Return COMPLETE file contents (not diffs or patches)
3. Preserve all existing functionality that works
4. Use the same coding style as the original
5. Add error handling where needed
6. Make sure imports are correct

OUTPUT FORMAT (JSON only, no markdown):
{
    "files": [
        {
            "path": "exact/file/path.jsx",
            "content": "COMPLETE fixed file content here",
            "file_type": "frontend"
        }
    ],
    "explanation": "What was fixed and why",
    "changes_made": ["List of specific changes"]
}"""

        user_prompt = f"""FIX THIS ERROR:

ERROR ANALYSIS:
- Type: {analysis.get('error_type', 'unknown')}
- Root Cause: {analysis.get('root_cause', 'Unknown')}
- Fix Strategy: {analysis.get('fix_strategy', 'Fix the error')}

{f"USER CONTEXT: {user_context}" if user_context else ""}

FILES TO FIX:
{files_content}

{f"APP REQUIREMENTS:{chr(10)}{json.dumps(requirements, indent=2)[:1000]}" if requirements else ""}

Generate the fixed code. Return complete file contents."""

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
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
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": settings["max_tokens"],
                        "temperature": 0.2
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Fix generation API error: {response.text}")
                    return {
                        "success": False,
                        "files": files,
                        "error": f"API error: {response.status_code}",
                        "analysis": analysis
                    }
                
                content = response.json()["choices"][0]["message"]["content"]
                return self._parse_and_merge_fixes(content, files, analysis)
                
        except Exception as e:
            logger.error(f"Fix generation error: {e}")
            return {
                "success": False,
                "files": files,
                "error": str(e),
                "analysis": analysis
            }
    
    def _parse_and_merge_fixes(
        self, 
        content: str, 
        original_files: List[Dict],
        analysis: Dict
    ) -> Dict:
        """Parse LLM response and merge fixed files"""
        
        # Try to extract JSON from response
        json_match = re.search(r'\{[\s\S]*"files"[\s\S]*\}', content)
        
        if json_match:
            try:
                result = json.loads(json_match.group(), strict=False)
                fixed_files = result.get("files", [])
                
                if not fixed_files:
                    return {
                        "success": False,
                        "files": original_files,
                        "error": "No fixed files in response",
                        "analysis": analysis
                    }
                
                # Validate fixed files have content
                valid_fixes = []
                for f in fixed_files:
                    if f.get("path") and f.get("content"):
                        valid_fixes.append(f)
                
                if not valid_fixes:
                    return {
                        "success": False,
                        "files": original_files,
                        "error": "Fixed files have no content",
                        "analysis": analysis
                    }
                
                # Merge: fixed files replace originals, keep unchanged files
                fixed_paths = {f["path"] for f in valid_fixes}
                merged_files = list(valid_fixes)
                
                for f in original_files:
                    if f["path"] not in fixed_paths:
                        merged_files.append(f)
                
                return {
                    "success": True,
                    "files": merged_files,
                    "files_modified": list(fixed_paths),
                    "explanation": result.get("explanation", ""),
                    "changes_made": result.get("changes_made", []),
                    "analysis": analysis
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error in fix response: {e}")
                logger.error(f"Content: {content[:500]}")
        
        return {
            "success": False,
            "files": original_files,
            "error": "Could not parse fix response",
            "raw_response": content[:1000],
            "analysis": analysis
        }
    
    async def fix_issues(
        self,
        files: List[Dict],
        test_results: Dict,
        requirements: Dict,
        attempt: int = 1,
        agent_context: Optional[str] = None
    ) -> Dict:
        """
        Fix issues from automated test results.
        (Legacy method for compatibility with job manager)
        
        Args:
            files: List of file dicts (full codebase)
            test_results: Test results dict
            requirements: Requirements dict
            attempt: Fix attempt number
            agent_context: Pre-built context (full codebase + schema + message history)
        """
        
        issues = test_results.get("issues", [])
        if not issues:
            return {
                "files": files,
                "fixes_applied": [],
                "files_modified": [],
                "summary": "No issues to fix"
            }
        
        # Convert test issues to error format
        error_message = "\n".join([
            f"- {issue.get('description', '')}: {issue.get('error', '')}"
            for issue in issues
        ])
        
        result = await self.fix_user_error(
            files=files,
            error_message=error_message,
            requirements=requirements,
            agent_context=agent_context
        )
        
        if result.get("success"):
            return {
                "files": result["files"],
                "fixes_applied": [{"description": c} for c in result.get("changes_made", [])],
                "files_modified": result.get("files_modified", []),
                "summary": result.get("explanation", f"Applied fixes on attempt {attempt}")
            }
        else:
            return {
                "files": files,
                "fixes_applied": [],
                "files_modified": [],
                "summary": f"Fix attempt {attempt} failed: {result.get('error', 'Unknown error')}"
            }
    
    def validate_fixes(self, original_files: List[Dict], fixed_files: List[Dict]) -> Dict:
        """Validate that fixes don't break existing functionality"""
        
        issues = []
        original_by_path = {f["path"]: f for f in original_files}
        fixed_by_path = {f["path"]: f for f in fixed_files}
        
        # Check for deleted files
        for path in original_by_path:
            if path not in fixed_by_path:
                issues.append({
                    "type": "deleted_file",
                    "file": path,
                    "message": f"File {path} was deleted"
                })
        
        # Check for empty files
        for path, f in fixed_by_path.items():
            if not f.get("content", "").strip():
                issues.append({
                    "type": "empty_file",
                    "file": path,
                    "message": f"File {path} is empty"
                })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues
        }
