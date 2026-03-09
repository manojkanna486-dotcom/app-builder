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
        agent_context: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Fix an error reported by the user.
        Receives entire codebase, errors, and chat history for full context.
        
        Args:
            files: List of file dicts (full codebase)
            error_message: Error message to fix
            user_context: Additional user context
            console_logs: Console logs if available
            requirements: Requirements dict
            agent_context: Pre-built context (full codebase + schema + message history)
            chat_history: Conversation history [{"role": "user"|"assistant", "content": "..."}]
        """
        
        # Step 1: Analyze the error to understand what's wrong
        analysis = await self._analyze_error(error_message, console_logs, files, agent_context)
        
        # Step 2: Generate targeted fixes (sends entire codebase + errors + chat history)
        fixes = await self._generate_fixes(files, analysis, user_context, requirements, agent_context, chat_history)
        
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
        
        # Build analysis prompt
        files_summary = "\n".join([
            f"- {f.get('path')}: {f.get('file_type', 'unknown')} ({len(f.get('content', ''))} chars)"
            for f in files
        ])
        
        prompt = f"""Analyze this error and identify the root cause.

ERROR MESSAGE:
{error_message}

{f"CONSOLE LOGS:{chr(10)}{console_logs}" if console_logs else ""}

FILES IN PROJECT:
{files_summary}

Respond in JSON format:
{{
    "error_type": "syntax|runtime|logic|database|api|ui|other",
    "root_cause": "Brief explanation of what's causing the error",
    "likely_files": ["list", "of", "files", "to", "check"],
    "fix_strategy": "How to fix this issue",
    "severity": "critical|high|medium|low"
}}"""

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
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
        agent_context: Optional[str] = None,
        chat_history: Optional[List[Dict]] = None
    ) -> Dict:
        """Generate code fixes - sends ENTIRE codebase, errors, and chat history"""
        
        model = get_model("fix")
        settings = get_model_settings(model)
        
        # Include ENTIRE codebase (all frontend files) for full context
        frontend_files = [f for f in files if f.get("file_type") == "frontend"]
        if not frontend_files:
            frontend_files = [f for f in files if f.get("path", "").endswith((".jsx", ".js", ".tsx"))]
        
        files_content = "\n\n".join([
            f"=== FILE: {f.get('path')} ===\n```\n{f.get('content', '')}\n```"
            for f in frontend_files
        ])
        
        system_prompt = """You are an expert React/JavaScript developer and debugger.
Your job is to fix bugs in generated code. When multiple test failures are reported, you MUST fix ALL of them in a single pass - do not fix only one and leave others broken.

PREVIEW RENDERING ENVIRONMENT:
The frontend code runs in a browser iframe using Babel Standalone (NOT a bundler).
- All import/export statements are STRIPPED before rendering - do NOT include them.
- React hooks (useState, useEffect, etc.) and 160+ Lucide icons are available as globals.
- React Router is mocked (BrowserRouter, Routes, Route, Link, useNavigate, etc. are globals).
- The main component MUST be named App.
- Do NOT name components the same as Lucide icons (Calculator, Calendar, Home, Settings, User, etc.) - prefix them instead (MyCalculator, AppSettings, etc.).
- import.meta.env is NOT supported.
- All components share a single global scope (no module isolation).

COMMON PREVIEW ERRORS:
- "Identifier 'X' has already been declared" → Component named same as a Lucide icon. Rename it.
- White screen with no error → Check for import/export statements that shouldn't be there.
- "X is not defined" → Missing global or typo. All React hooks and Lucide icons are globals.

RULES:
1. Fix the SPECIFIC error mentioned - don't rewrite everything
2. Return COMPLETE file contents (not diffs or patches)
3. Preserve all existing functionality that works
4. Use the same coding style as the original
5. Add error handling where needed
6. Do NOT include import/export statements in frontend files
7. Do NOT name components the same as Lucide icon names

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

        # Build chat history section
        chat_section = ""
        if chat_history and len(chat_history) > 0:
            recent = chat_history[-10:]  # Last 10 messages
            chat_section = "\n\nCONVERSATION HISTORY (user requests and prior context):\n"
            for m in recent:
                role = m.get("role", "user")
                content = (m.get("content", "") or "")[:800]  # Truncate long messages
                if content and not content.startswith("✅"):
                    chat_section += f"\n{role.upper()}: {content}\n"

        user_prompt = f"""FIX THIS ERROR:

ERROR ANALYSIS:
- Type: {analysis.get('error_type', 'unknown')}
- Root Cause: {analysis.get('root_cause', 'Unknown')}
- Fix Strategy: {analysis.get('fix_strategy', 'Fix the error')}

{f"USER CONTEXT: {user_context}" if user_context else ""}
{chat_section}

ENTIRE CODEBASE (fix the relevant files, return ALL modified files):
{files_content}

{f"APP REQUIREMENTS:{chr(10)}{json.dumps(requirements, indent=2)[:1500]}" if requirements else ""}

Generate the fixed code. Return complete file contents for ALL files you modify."""

        # Build messages with chat history for context
        messages = [{"role": "system", "content": system_prompt}]
        if chat_history and len(chat_history) > 0:
            for m in chat_history[-6:]:  # Last 6 for context (3 exchanges)
                role = m.get("role", "user")
                content = m.get("content", "")
                if content and role in ("user", "assistant"):
                    messages.append({"role": role, "content": content[:1500]})
        messages.append({"role": "user", "content": user_prompt})

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
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
        chat_history: Optional[List[Dict]] = None
    ) -> Dict:
        """
        Fix ALL issues from automated test results.
        Receives entire codebase, errors, and chat history for full context.
        Skips the separate analysis LLM call - we already have structured errors (faster).
        """
        
        issues = test_results.get("issues", [])
        if not issues:
            return {
                "files": files,
                "fixes_applied": [],
                "files_modified": [],
                "summary": "No issues to fix"
            }
        
        # Build error text for the fix prompt
        error_message = (
            f"FIX ALL {len(issues)} FAILING TESTS (attempt {attempt}/3). Address every issue below:\n\n"
            + "\n".join([
                f"{i+1}. [{issue.get('category', '')}] {issue.get('description', '')}: {issue.get('error', '')}"
                + (f"\n   Steps: {' → '.join(issue.get('steps_to_reproduce', []))}" if issue.get('steps_to_reproduce') else "")
                for i, issue in enumerate(issues)
            ])
        )
        
        # Skip _analyze_error LLM call - use synthetic analysis from structured issues (saves ~30-60s per fix)
        categories = [i.get("category", "unknown") for i in issues]
        analysis = {
            "error_type": "syntax" if "syntax" in categories else ("runtime" if "runtime" in categories else "logic"),
            "root_cause": error_message[:1500],
            "likely_files": list({f.get("path") for f in files if f.get("file_type") == "frontend"})[:5],
            "fix_strategy": "Fix each reported issue in the code; return complete file contents for all modified files.",
            "severity": "high"
        }
        
        result = await self._generate_fixes(
            files=files,
            analysis=analysis,
            user_context=None,
            requirements=requirements,
            agent_context=None,
            chat_history=chat_history
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
