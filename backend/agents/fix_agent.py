"""
Fix Agent - Fixes only issues reported by Tester Agent
MUST DO: Fix only reported issues, modify minimal code, preserve working features
MUST NOT: Add new features, change requirements, over-refactor
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger(__name__)


class FixAgent:
    """
    Fixes code issues identified by the Tester Agent.
    
    RULES:
    1. Fix ONLY reported issues - nothing else
    2. Modify minimal required code
    3. Preserve ALL existing working features
    4. Maintain existing code style
    5. Never add new features
    6. Never change requirements
    """
    
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
        Fix issues from test results.
        Returns ONLY modified files.
        """
        
        issues = test_results.get("issues", [])
        if not issues:
            return {
                "files": files,
                "fixes_applied": [],
                "files_modified": [],
                "summary": "No issues to fix"
            }
        
        # Build minimal fix prompt
        prompt = self._build_fix_prompt(files, issues, requirements, attempt)
        
        system_prompt = """You are the Fix Agent. Your ONLY job is to fix reported issues.

STRICT RULES:
1. Fix ONLY the issues listed - NOTHING ELSE
2. Make MINIMAL changes - only what's needed to fix the issue
3. PRESERVE all existing working functionality
4. Do NOT add new features
5. Do NOT refactor working code
6. Do NOT change code style
7. Do NOT modify files that don't need changes

OUTPUT FORMAT - Return ONLY files that were MODIFIED:
{
    "files": [
        {
            "path": "path/to/file.jsx",
            "content": "complete fixed content",
            "file_type": "frontend|sql|edge_function"
        }
    ],
    "fixes_applied": [
        {
            "issue_id": "TEST-001",
            "description": "What was fixed",
            "file": "path/to/file.jsx",
            "change_type": "bug_fix|missing_feature|error_handling"
        }
    ],
    "files_modified": ["path/to/file.jsx"]
}

IMPORTANT:
- Return COMPLETE file content, not diffs
- Only include files that were ACTUALLY modified
- If you can't fix an issue, don't include fake fixes
"""
        
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
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 16000,
                        "temperature": 0.2
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"Fix Agent API error: {response.text}")
                    return {
                        "files": files,
                        "fixes_applied": [],
                        "files_modified": [],
                        "summary": f"Fix attempt {attempt} failed: API error"
                    }
                
                content = response.json()["choices"][0]["message"]["content"]
                return self._parse_and_merge_fixes(content, files)
                
        except Exception as e:
            logger.error(f"Fix Agent error: {e}")
            return {
                "files": files,
                "fixes_applied": [],
                "files_modified": [],
                "summary": f"Fix attempt {attempt} failed: {str(e)}"
            }
    
    def _build_fix_prompt(
        self,
        files: List[Dict],
        issues: List[Dict],
        requirements: Dict,
        attempt: int
    ) -> str:
        """Build minimal fix prompt"""
        
        # Format issues clearly
        issues_text = "\n".join([
            f"""
ISSUE {i+1}: {issue.get('test_id', 'UNKNOWN')}
Category: {issue.get('category', 'unknown')}
Description: {issue.get('description', '')}
Error: {issue.get('error', 'Unknown')}
Steps to Reproduce: {', '.join(issue.get('steps_to_reproduce', []))}
"""
            for i, issue in enumerate(issues)
        ])
        
        # Format files
        files_text = "\n\n".join([
            f"=== {f.get('path', 'unknown')} ===\n{f.get('content', '')}"
            for f in files
        ])
        
        return f"""FIX ATTEMPT {attempt}/3

ISSUES TO FIX (Fix these ONLY):
{issues_text}

CURRENT FILES:
{files_text}

Fix ONLY the issues listed above. Do NOT change anything else."""
    
    def _parse_and_merge_fixes(self, content: str, original_files: List[Dict]) -> Dict:
        """Parse fix response and merge with original files"""
        
        # Try to extract JSON
        json_match = re.search(r'\{[\s\S]*"files"[\s\S]*\}', content)
        if json_match:
            try:
                result = json.loads(json_match.group(), strict=False)
                
                fixed_files = result.get("files", [])
                fixed_paths = {f["path"] for f in fixed_files}
                
                # Merge: fixed files + unchanged original files
                merged_files = list(fixed_files)
                for f in original_files:
                    if f["path"] not in fixed_paths:
                        merged_files.append(f)
                
                return {
                    "files": merged_files,
                    "fixes_applied": result.get("fixes_applied", []),
                    "files_modified": list(fixed_paths),
                    "summary": f"Applied {len(result.get('fixes_applied', []))} fixes to {len(fixed_paths)} files"
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
        
        return {
            "files": original_files,
            "fixes_applied": [],
            "files_modified": [],
            "summary": "Could not parse fix response"
        }
    
    def validate_fixes(self, original_files: List[Dict], fixed_files: List[Dict]) -> Dict:
        """Validate that fixes don't break existing functionality"""
        
        issues = []
        
        # Create lookup for original files
        original_by_path = {f["path"]: f for f in original_files}
        fixed_by_path = {f["path"]: f for f in fixed_files}
        
        # Check for deleted files
        for path in original_by_path:
            if path not in fixed_by_path:
                issues.append({
                    "type": "deleted_file",
                    "file": path,
                    "message": f"File {path} was deleted - this may break the app"
                })
        
        # Check for significantly changed files
        for path, fixed in fixed_by_path.items():
            if path in original_by_path:
                original = original_by_path[path]
                original_lines = len(original.get("content", "").split("\n"))
                fixed_lines = len(fixed.get("content", "").split("\n"))
                
                # Warn if file changed by more than 50%
                change_ratio = abs(fixed_lines - original_lines) / max(original_lines, 1)
                if change_ratio > 0.5:
                    issues.append({
                        "type": "major_change",
                        "file": path,
                        "message": f"File {path} changed significantly ({int(change_ratio*100)}%) - verify functionality"
                    })
        
        return {
            "valid": len(issues) == 0,
            "issues": issues
        }
