"""
Built-in Testing Agent for Generated Apps
Automatically tests generated code based on user requirements.
Max 3 retry attempts per prompt.
"""

import json
import logging
import re
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Maximum retry attempts
MAX_RETRY_ATTEMPTS = 3


class TestResult:
    """Represents a single test result"""
    def __init__(self, requirement_id: str, description: str, passed: bool, 
                 error: str = None, severity: str = "MAJOR"):
        self.requirement_id = requirement_id
        self.description = description
        self.passed = passed
        self.error = error
        self.severity = severity  # BLOCKER, MAJOR, MINOR
    
    def to_dict(self):
        return {
            "requirement_id": self.requirement_id,
            "description": self.description,
            "passed": self.passed,
            "error": self.error,
            "severity": self.severity
        }


class TestingAgent:
    """
    Testing Agent that validates generated apps based on user requirements.
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
    
    async def extract_requirements(self, user_prompt: str) -> List[Dict[str, str]]:
        """
        Use LLM to extract testable requirements from user prompt.
        """
        extraction_prompt = f"""Analyze this user request and extract testable requirements.

User Request: "{user_prompt}"

Return a JSON array of requirements. Each requirement should be:
- id: REQ-001, REQ-002, etc.
- description: What the feature should do
- test_type: "ui" (visual), "auth" (authentication), "data" (database), "api" (API calls), "logic" (business logic)
- validation: How to verify it works

Return ONLY valid JSON array, no markdown:
[{{"id": "REQ-001", "description": "...", "test_type": "...", "validation": "..."}}]"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4",
                        "messages": [{"role": "user", "content": extraction_prompt}],
                        "max_tokens": 1000
                    }
                )
                
                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    # Extract JSON from response
                    try:
                        # Try direct parse
                        requirements = json.loads(content)
                    except:
                        # Try to find JSON array in response
                        match = re.search(r'\[[\s\S]*\]', content)
                        if match:
                            requirements = json.loads(match.group())
                        else:
                            requirements = [{"id": "REQ-001", "description": user_prompt, "test_type": "ui", "validation": "App renders without errors"}]
                    return requirements
        except Exception as e:
            logger.error(f"Error extracting requirements: {e}")
        
        # Default requirement if extraction fails
        return [{"id": "REQ-001", "description": user_prompt, "test_type": "ui", "validation": "App renders without errors"}]
    
    async def run_tests(self, files: List[Dict], requirements: List[Dict], 
                        supabase_config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Run tests against generated code based on requirements.
        """
        results = []
        
        for req in requirements:
            result = await self._test_requirement(req, files, supabase_config)
            results.append(result)
        
        passed = all(r.passed for r in results)
        failed_results = [r for r in results if not r.passed]
        
        return {
            "status": "PASS" if passed else "FAIL",
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [r.to_dict() for r in results],
            "failed_requirements": [r.to_dict() for r in failed_results],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    async def _test_requirement(self, requirement: Dict, files: List[Dict], 
                                supabase_config: Optional[Dict]) -> TestResult:
        """
        Test a single requirement against the generated code.
        """
        req_id = requirement.get("id", "REQ-???")
        description = requirement.get("description", "")
        test_type = requirement.get("test_type", "ui")
        
        try:
            # Get all code content
            all_code = "\n".join([f.get("content", "") for f in files])
            
            # Basic validations based on test type
            if test_type == "ui":
                return await self._test_ui_requirement(req_id, description, files, all_code)
            elif test_type == "auth":
                return await self._test_auth_requirement(req_id, description, files, all_code, supabase_config)
            elif test_type == "data":
                return await self._test_data_requirement(req_id, description, files, all_code)
            elif test_type == "api":
                return await self._test_api_requirement(req_id, description, files, all_code)
            else:
                return await self._test_logic_requirement(req_id, description, files, all_code)
                
        except Exception as e:
            return TestResult(req_id, description, False, str(e), "BLOCKER")
    
    async def _test_ui_requirement(self, req_id: str, description: str, 
                                   files: List[Dict], all_code: str) -> TestResult:
        """Test UI-related requirements"""
        errors = []
        
        # Check for React component structure
        has_component = bool(re.search(r'(function|const)\s+\w+\s*[=]?\s*\([^)]*\)\s*[=>{]', all_code))
        if not has_component:
            errors.append("No React component found")
        
        # Check for render/return statement
        has_render = 'return' in all_code and ('<' in all_code or 'jsx' in all_code.lower())
        if not has_render:
            errors.append("No JSX return statement found")
        
        # Check for basic UI elements mentioned in description
        desc_lower = description.lower()
        if 'button' in desc_lower and not re.search(r'<button|<Button|onClick', all_code, re.I):
            errors.append("Button element not found but required")
        if 'form' in desc_lower and not re.search(r'<form|onSubmit|handleSubmit', all_code, re.I):
            errors.append("Form element not found but required")
        if 'input' in desc_lower and not re.search(r'<input|<Input|onChange', all_code, re.I):
            errors.append("Input element not found but required")
        if 'list' in desc_lower and not re.search(r'\.map\(|<ul|<ol|<li', all_code, re.I):
            errors.append("List rendering not found but required")
        
        # Check for syntax errors
        syntax_errors = self._check_jsx_syntax(all_code)
        if syntax_errors:
            errors.extend(syntax_errors)
        
        if errors:
            return TestResult(req_id, description, False, "; ".join(errors), "MAJOR")
        return TestResult(req_id, description, True)
    
    async def _test_auth_requirement(self, req_id: str, description: str, 
                                     files: List[Dict], all_code: str,
                                     supabase_config: Optional[Dict]) -> TestResult:
        """Test authentication-related requirements"""
        errors = []
        
        # Check for Supabase auth imports/usage
        has_supabase = 'supabase' in all_code.lower()
        has_auth = re.search(r'supabase\.auth\.|signIn|signUp|signOut|auth\.', all_code, re.I)
        
        if 'login' in description.lower() or 'signin' in description.lower() or 'auth' in description.lower():
            if not has_supabase:
                errors.append("Supabase client not found for authentication")
            if not has_auth:
                errors.append("Auth methods (signIn/signUp) not implemented")
            
            # Check for auth state handling
            if not re.search(r'useState.*user|session|onAuthStateChange', all_code, re.I):
                errors.append("Auth state management not found")
        
        # Check for password input if signup/login
        if 'password' in description.lower() or 'signup' in description.lower():
            if not re.search(r'type=["\']password["\']|password', all_code, re.I):
                errors.append("Password field not found")
        
        if errors:
            return TestResult(req_id, description, False, "; ".join(errors), "BLOCKER")
        return TestResult(req_id, description, True)
    
    async def _test_data_requirement(self, req_id: str, description: str,
                                     files: List[Dict], all_code: str) -> TestResult:
        """Test data/database-related requirements"""
        errors = []
        
        # Check for data fetching
        has_fetch = re.search(r'fetch\(|axios|supabase\.from|\.select\(|\.insert\(', all_code, re.I)
        has_state = re.search(r'useState|useReducer|state', all_code, re.I)
        
        if 'data' in description.lower() or 'fetch' in description.lower() or 'load' in description.lower():
            if not has_fetch:
                errors.append("No data fetching mechanism found")
            if not has_state:
                errors.append("No state management for data")
        
        # Check for CRUD operations if mentioned
        if 'create' in description.lower() or 'add' in description.lower():
            if not re.search(r'\.insert\(|\.create|POST|add', all_code, re.I):
                errors.append("Create/insert operation not found")
        if 'delete' in description.lower() or 'remove' in description.lower():
            if not re.search(r'\.delete\(|DELETE|remove', all_code, re.I):
                errors.append("Delete operation not found")
        if 'update' in description.lower() or 'edit' in description.lower():
            if not re.search(r'\.update\(|PUT|PATCH|edit', all_code, re.I):
                errors.append("Update operation not found")
        
        if errors:
            return TestResult(req_id, description, False, "; ".join(errors), "MAJOR")
        return TestResult(req_id, description, True)
    
    async def _test_api_requirement(self, req_id: str, description: str,
                                    files: List[Dict], all_code: str) -> TestResult:
        """Test API-related requirements"""
        errors = []
        
        # Check for API calls
        has_api = re.search(r'fetch\(|axios|httpx|supabase\.|\.rpc\(', all_code, re.I)
        has_async = re.search(r'async|await|\.then\(|Promise', all_code, re.I)
        
        if 'api' in description.lower() or 'endpoint' in description.lower():
            if not has_api:
                errors.append("No API call mechanism found")
            if not has_async:
                errors.append("No async handling for API calls")
        
        # Check for error handling
        if not re.search(r'try\s*{|\.catch\(|catch\s*\(|error', all_code, re.I):
            errors.append("No error handling for API calls")
        
        if errors:
            return TestResult(req_id, description, False, "; ".join(errors), "MAJOR")
        return TestResult(req_id, description, True)
    
    async def _test_logic_requirement(self, req_id: str, description: str,
                                      files: List[Dict], all_code: str) -> TestResult:
        """Test business logic requirements"""
        errors = []
        
        # Check for basic logic patterns
        desc_lower = description.lower()
        
        if 'calculate' in desc_lower or 'compute' in desc_lower:
            if not re.search(r'[\+\-\*\/]|Math\.|calculate|compute', all_code, re.I):
                errors.append("Calculation logic not found")
        
        if 'sort' in desc_lower:
            if not re.search(r'\.sort\(|sorted|orderBy', all_code, re.I):
                errors.append("Sorting logic not found")
        
        if 'filter' in desc_lower or 'search' in desc_lower:
            if not re.search(r'\.filter\(|\.find\(|search|query', all_code, re.I):
                errors.append("Filter/search logic not found")
        
        if 'validate' in desc_lower or 'validation' in desc_lower:
            if not re.search(r'validate|isValid|error|required', all_code, re.I):
                errors.append("Validation logic not found")
        
        if errors:
            return TestResult(req_id, description, False, "; ".join(errors), "MINOR")
        return TestResult(req_id, description, True)
    
    def _check_jsx_syntax(self, code: str) -> List[str]:
        """Check for common JSX syntax errors"""
        errors = []
        
        # Check for unclosed tags (basic check)
        open_tags = re.findall(r'<(\w+)[^/>]*(?<!/)>', code)
        close_tags = re.findall(r'</(\w+)>', code)
        
        # Check for common React errors
        if 'class=' in code and 'className=' not in code:
            errors.append("Using 'class' instead of 'className' in JSX")
        
        if re.search(r'for=["\']\w', code) and 'htmlFor=' not in code:
            errors.append("Using 'for' instead of 'htmlFor' in JSX")
        
        # Check for missing key prop in map
        if '.map(' in code and not re.search(r'key=|key:', code):
            errors.append("Missing 'key' prop in list rendering")
        
        return errors
    
    async def generate_fix_prompt(self, original_prompt: str, files: List[Dict],
                                  test_results: Dict) -> str:
        """
        Generate a prompt for the dev agent to fix failed tests.
        """
        failed = test_results.get("failed_requirements", [])
        
        if not failed:
            return None
        
        # Build error summary
        error_summary = []
        for f in failed:
            error_summary.append(f"- {f['requirement_id']}: {f['description']}")
            error_summary.append(f"  Error: {f['error']}")
            error_summary.append(f"  Severity: {f['severity']}")
        
        fix_prompt = f"""The generated code has test failures. Please fix these issues:

ORIGINAL REQUEST: {original_prompt}

TEST FAILURES:
{chr(10).join(error_summary)}

INSTRUCTIONS:
1. Fix ONLY the issues mentioned above
2. Keep all working functionality intact
3. Ensure the code still fulfills the original request
4. Return the complete fixed code

Fix these issues and regenerate the code."""
        
        return fix_prompt


async def run_testing_loop(
    testing_agent: TestingAgent,
    generate_func,  # Function to call for code generation
    project_id: str,
    original_prompt: str,
    supabase_config: Optional[Dict] = None,
    max_attempts: int = MAX_RETRY_ATTEMPTS
) -> Dict[str, Any]:
    """
    Run the testing loop with automatic retries.
    
    Args:
        testing_agent: The TestingAgent instance
        generate_func: Async function that generates code and returns files
        project_id: The project ID
        original_prompt: Original user prompt
        supabase_config: Supabase configuration if connected
        max_attempts: Maximum retry attempts (default 3)
    
    Returns:
        Final test results with retry history
    """
    attempt = 0
    current_prompt = original_prompt
    history = []
    final_files = None
    
    while attempt < max_attempts:
        attempt += 1
        logger.info(f"Testing attempt {attempt}/{max_attempts} for project {project_id}")
        
        # Generate code
        files = await generate_func(project_id, current_prompt)
        final_files = files
        
        # Extract requirements from original prompt (only on first attempt)
        if attempt == 1:
            requirements = await testing_agent.extract_requirements(original_prompt)
        
        # Run tests
        test_results = await testing_agent.run_tests(files, requirements, supabase_config)
        
        history.append({
            "attempt": attempt,
            "prompt": current_prompt[:200] + "..." if len(current_prompt) > 200 else current_prompt,
            "test_results": test_results
        })
        
        if test_results["status"] == "PASS":
            logger.info(f"All tests passed on attempt {attempt}")
            return {
                "status": "PASS",
                "attempts": attempt,
                "final_results": test_results,
                "history": history,
                "files": files
            }
        
        # Tests failed - generate fix prompt if we have retries left
        if attempt < max_attempts:
            fix_prompt = await testing_agent.generate_fix_prompt(
                original_prompt, files, test_results
            )
            current_prompt = fix_prompt
            logger.info(f"Tests failed, generating fix prompt for attempt {attempt + 1}")
        else:
            logger.warning(f"Max attempts ({max_attempts}) reached with failures")
    
    # Return final results after max attempts
    return {
        "status": "FAIL",
        "attempts": attempt,
        "final_results": test_results,
        "history": history,
        "files": final_files,
        "message": f"Tests still failing after {max_attempts} attempts"
    }
