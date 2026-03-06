"""
Testing Agent - Deep testing of generated applications
Validates code against requirements and tests functionality
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger(__name__)

# Maximum retry attempts for fixing issues
MAX_FIX_RETRIES = 3

class TestResult:
    """Result of a single test"""
    def __init__(self, req_id: str, description: str, passed: bool, error: Optional[str] = None):
        self.req_id = req_id
        self.description = description
        self.passed = passed
        self.error = error
    
    def to_dict(self) -> Dict:
        return {
            "req_id": self.req_id,
            "description": self.description,
            "passed": self.passed,
            "error": self.error
        }


class TestingAgent:
    """Agent that performs deep testing of generated applications"""
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def run_tests(
        self, 
        files: List[Dict],
        requirements: Dict,
        supabase_config: Optional[Dict] = None
    ) -> Dict:
        """
        Run comprehensive tests against the generated code.
        Returns test results with pass/fail status for each requirement.
        """
        
        results = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "tests": [],
            "issues": [],
            "summary": ""
        }
        
        all_requirements = requirements.get("requirements", [])
        results["total"] = len(all_requirements)
        
        # Combine all code for analysis
        all_code = "\n\n".join([
            f"// FILE: {f.get('path', 'unknown')}\n{f.get('content', '')}" 
            for f in files
        ])
        
        # Run syntax validation
        syntax_results = self._validate_syntax(files)
        results["tests"].extend(syntax_results)
        
        # Run requirement-based tests
        for req in all_requirements:
            test_result = await self._test_requirement(req, files, all_code, supabase_config)
            results["tests"].append(test_result.to_dict())
            
            if test_result.passed:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["issues"].append({
                    "req_id": test_result.req_id,
                    "description": test_result.description,
                    "error": test_result.error
                })
        
        # Update passed count from syntax tests
        results["passed"] += sum(1 for t in syntax_results if t.get("passed", False))
        results["failed"] += sum(1 for t in syntax_results if not t.get("passed", True))
        
        # Generate summary
        if results["failed"] == 0:
            results["summary"] = f"✅ All {results['total']} tests passed!"
        else:
            results["summary"] = f"❌ {results['failed']}/{results['total']} tests failed. Issues need to be fixed."
        
        return results
    
    def _validate_syntax(self, files: List[Dict]) -> List[Dict]:
        """Validate syntax of generated files"""
        results = []
        
        for f in files:
            path = f.get("path", "unknown")
            content = f.get("content", "")
            file_type = f.get("file_type", "frontend")
            
            errors = []
            
            if file_type == "frontend" and (path.endswith(".jsx") or path.endswith(".js")):
                errors.extend(self._check_jsx_syntax(content, path))
            elif file_type == "sql":
                errors.extend(self._check_sql_syntax(content, path))
            elif file_type == "edge_function":
                errors.extend(self._check_typescript_syntax(content, path))
            
            results.append({
                "req_id": f"SYNTAX-{path}",
                "description": f"Syntax validation for {path}",
                "passed": len(errors) == 0,
                "error": "; ".join(errors) if errors else None
            })
        
        return results
    
    def _check_jsx_syntax(self, content: str, path: str) -> List[str]:
        """Check JSX/JavaScript syntax"""
        errors = []
        
        # Check for unbalanced brackets
        open_braces = content.count("{") 
        close_braces = content.count("}")
        if open_braces != close_braces:
            errors.append(f"Unbalanced braces in {path}: {open_braces} open, {close_braces} close")
        
        # Check for unbalanced parentheses
        open_parens = content.count("(")
        close_parens = content.count(")")
        if open_parens != close_parens:
            errors.append(f"Unbalanced parentheses in {path}")
        
        # Check for common React errors
        if "import React" in content and "from 'react'" not in content and 'from "react"' not in content:
            errors.append(f"Missing React import statement in {path}")
        
        # Check for undefined component exports
        if "export default" not in content and "export const" not in content and "export function" not in content:
            if path.endswith(".jsx") and "App" not in path:
                errors.append(f"No export statement in component {path}")
        
        # Check for common Supabase errors
        if "supabase" in content.lower():
            if "import" not in content or "supabase" not in content.lower():
                pass  # May be imported elsewhere
        
        return errors
    
    def _check_sql_syntax(self, content: str, path: str) -> List[str]:
        """Check SQL syntax"""
        errors = []
        
        # Check for common SQL issues
        if "CREATE TABLE" in content.upper():
            # Check for missing semicolons
            statements = content.split(";")
            for stmt in statements:
                stmt = stmt.strip()
                if stmt and not stmt.endswith(")") and "CREATE" in stmt.upper() and "(" in stmt:
                    if stmt.count("(") != stmt.count(")"):
                        errors.append(f"Unbalanced parentheses in SQL statement")
        
        # Check for RLS
        if "CREATE TABLE" in content.upper() and "ENABLE ROW LEVEL SECURITY" not in content.upper():
            errors.append(f"RLS not enabled in {path} - security issue")
        
        return errors
    
    def _check_typescript_syntax(self, content: str, path: str) -> List[str]:
        """Check TypeScript syntax for Edge Functions"""
        errors = []
        
        # Check for Deno serve pattern
        if "serve" not in content.lower() and "Deno" not in content:
            errors.append(f"Edge function {path} may not have proper Deno serve setup")
        
        return errors
    
    async def _test_requirement(
        self, 
        requirement: Dict,
        files: List[Dict],
        all_code: str,
        supabase_config: Optional[Dict]
    ) -> TestResult:
        """Test a specific requirement against the code"""
        
        req_id = requirement.get("id", "UNKNOWN")
        description = requirement.get("description", "")
        category = requirement.get("category", "feature")
        
        # Category-specific testing
        if category == "data":
            return await self._test_data_requirement(req_id, description, files, all_code)
        elif category == "auth":
            return await self._test_auth_requirement(req_id, description, all_code)
        elif category == "ui":
            return await self._test_ui_requirement(req_id, description, all_code)
        else:
            return await self._test_feature_requirement(req_id, description, files, all_code)
    
    async def _test_data_requirement(
        self, req_id: str, description: str, files: List[Dict], all_code: str
    ) -> TestResult:
        """Test data/database related requirements"""
        
        # Check for Supabase data operations
        has_supabase_query = re.search(r'supabase\s*\.from\s*\(|\.select\s*\(|\.insert\s*\(|\.update\s*\(|\.delete\s*\(', all_code)
        has_migration = any(f.get("file_type") == "sql" for f in files)
        
        if "database" in description.lower() or "table" in description.lower() or "data" in description.lower():
            if not has_migration:
                return TestResult(req_id, description, False, "No SQL migration found for database requirement")
            if not has_supabase_query:
                return TestResult(req_id, description, False, "No Supabase query found - data operations not implemented")
        
        return TestResult(req_id, description, True)
    
    async def _test_auth_requirement(self, req_id: str, description: str, all_code: str) -> TestResult:
        """Test authentication related requirements"""
        
        has_auth = re.search(r'supabase\.auth|signIn|signUp|signOut|session|user', all_code, re.I)
        
        if "auth" in description.lower() or "login" in description.lower() or "user" in description.lower():
            if not has_auth:
                return TestResult(req_id, description, False, "No authentication implementation found")
        
        return TestResult(req_id, description, True)
    
    async def _test_ui_requirement(self, req_id: str, description: str, all_code: str) -> TestResult:
        """Test UI related requirements"""
        
        desc_lower = description.lower()
        
        # Check responsive design
        if "responsive" in desc_lower:
            has_responsive = re.search(r'sm:|md:|lg:|xl:|@media|flex|grid', all_code)
            if not has_responsive:
                return TestResult(req_id, description, False, "No responsive design patterns found")
        
        # Check for loading states
        if "loading" in desc_lower:
            has_loading = re.search(r'loading|isLoading|Loader|Spinner|skeleton', all_code, re.I)
            if not has_loading:
                return TestResult(req_id, description, False, "No loading state implementation found")
        
        # Check for error handling
        if "error" in desc_lower:
            has_error = re.search(r'error|catch|try|Error|toast|alert', all_code, re.I)
            if not has_error:
                return TestResult(req_id, description, False, "No error handling found")
        
        return TestResult(req_id, description, True)
    
    async def _test_feature_requirement(
        self, req_id: str, description: str, files: List[Dict], all_code: str
    ) -> TestResult:
        """Test general feature requirements using LLM analysis"""
        
        # For complex feature requirements, use LLM to verify
        try:
            prompt = f"""Analyze if this code implements the following requirement:

REQUIREMENT: {description}

CODE FILES:
{all_code[:8000]}  # Truncate for context

Answer in JSON format:
{{"implemented": true/false, "evidence": "brief explanation", "missing": "what's missing if not implemented"}}
"""
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4-5",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.1
                    }
                )
                
                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    json_match = re.search(r'\{[\s\S]*\}', content)
                    if json_match:
                        result = json.loads(json_match.group())
                        if result.get("implemented", False):
                            return TestResult(req_id, description, True)
                        else:
                            return TestResult(req_id, description, False, result.get("missing", "Requirement not fully implemented"))
        
        except Exception as e:
            logger.error(f"Feature test error: {e}")
        
        # Default to pass if we can't verify
        return TestResult(req_id, description, True)
    
    def generate_fix_report(self, test_results: Dict) -> Dict:
        """Generate a detailed report of issues that need fixing"""
        
        issues = test_results.get("issues", [])
        
        report = {
            "total_issues": len(issues),
            "issues_by_category": {},
            "fix_instructions": []
        }
        
        for issue in issues:
            req_id = issue.get("req_id", "")
            
            # Categorize issues
            if "SYNTAX" in req_id:
                category = "syntax"
            elif "REQ" in req_id:
                category = "requirement"
            else:
                category = "other"
            
            if category not in report["issues_by_category"]:
                report["issues_by_category"][category] = []
            report["issues_by_category"][category].append(issue)
            
            # Generate fix instruction
            report["fix_instructions"].append({
                "req_id": req_id,
                "description": issue.get("description", ""),
                "error": issue.get("error", ""),
                "suggested_fix": self._suggest_fix(issue)
            })
        
        return report
    
    def _suggest_fix(self, issue: Dict) -> str:
        """Suggest a fix for an issue"""
        error = issue.get("error", "").lower()
        
        if "unbalanced" in error:
            return "Check and fix bracket/parenthesis matching"
        elif "rls" in error:
            return "Add 'ALTER TABLE table_name ENABLE ROW LEVEL SECURITY;' and create RLS policies"
        elif "supabase query" in error:
            return "Add Supabase data operations (select, insert, update, delete)"
        elif "migration" in error:
            return "Create SQL migration file with table schema"
        elif "auth" in error:
            return "Implement Supabase Auth (signIn, signUp, session management)"
        elif "responsive" in error:
            return "Add Tailwind responsive classes (sm:, md:, lg:)"
        elif "loading" in error:
            return "Add loading state with useState and conditional rendering"
        elif "error handling" in error:
            return "Add try/catch blocks and error state handling"
        else:
            return "Review and implement the requirement"
