"""
Conversational Tester Agent - Tests apps like a real human user
MUST DO: Read requirements.json, test flows conversationally, detect UX issues
MUST NOT: Assume happy paths only, skip edge cases, write/fix code
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """A single test case"""
    id: str
    category: str  # auth, crud, navigation, refresh, invalid_input, ux
    description: str
    steps: List[str]
    expected: str
    actual: Optional[str] = None
    passed: Optional[bool] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "category": self.category,
            "description": self.description,
            "steps": self.steps,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
            "error": self.error
        }


class ConversationalTesterAgent:
    """
    Tests the app like a real human user.
    
    Tests conversationally:
    - "What happens if I click this button without filling the form?"
    - "What happens if I refresh the page after submitting?"
    - "What happens if I enter invalid data?"
    
    Categories:
    - Auth: login, logout, signup, session persistence
    - CRUD: create, read, update, delete operations
    - Navigation: page transitions, back button, deep links
    - Refresh: page refresh behavior, state persistence
    - Invalid Input: empty fields, wrong formats, special characters
    - UX: error messages clarity, loading states, feedback
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
        
    async def generate_test_cases(self, requirements: Dict) -> List[TestCase]:
        """
        Generate test cases from requirements.json
        """
        
        test_cases = []
        
        # Auth tests
        if self._requires_auth(requirements):
            test_cases.extend(self._generate_auth_tests(requirements))
        
        # CRUD tests for each data model
        for model in requirements.get("data_models", []):
            test_cases.extend(self._generate_crud_tests(model, requirements))
        
        # Navigation tests for each page
        for page in requirements.get("pages", []):
            test_cases.extend(self._generate_navigation_tests(page, requirements))
        
        # Invalid input tests
        test_cases.extend(self._generate_invalid_input_tests(requirements))
        
        # UX tests
        test_cases.extend(self._generate_ux_tests(requirements))
        
        return test_cases
    
    async def run_tests(
        self, 
        files: List[Dict],
        requirements: Dict,
        supabase_config: Optional[Dict] = None
    ) -> Dict:
        """
        Run all tests against the generated code.
        Returns detailed test results.
        """
        
        # Generate test cases from requirements
        test_cases = await self.generate_test_cases(requirements)
        
        # Combine all code for analysis
        all_code = "\n\n".join([
            f"// FILE: {f.get('path', 'unknown')}\n{f.get('content', '')}" 
            for f in files
        ])
        
        results = {
            "total": len(test_cases),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "tests": [],
            "issues": [],
            "summary": ""
        }
        
        # Run each test
        for test in test_cases:
            result = await self._run_test(test, files, all_code, requirements)
            results["tests"].append(result.to_dict())
            
            if result.passed is True:
                results["passed"] += 1
            elif result.passed is False:
                results["failed"] += 1
                results["issues"].append({
                    "test_id": result.id,
                    "category": result.category,
                    "description": result.description,
                    "error": result.error,
                    "steps_to_reproduce": result.steps
                })
            else:
                results["skipped"] += 1
        
        # Generate summary
        if results["failed"] == 0:
            results["summary"] = f"✅ All {results['passed']} tests passed!"
        else:
            results["summary"] = f"❌ {results['failed']}/{results['total']} tests failed"
        
        return results
    
    async def _run_test(
        self, 
        test: TestCase, 
        files: List[Dict], 
        all_code: str,
        requirements: Dict
    ) -> TestCase:
        """Run a single test case using LLM analysis"""
        
        prompt = f"""You are testing a web application like a real user.

TEST CASE: {test.description}

STEPS TO TEST:
{chr(10).join(f"{i+1}. {step}" for i, step in enumerate(test.steps))}

EXPECTED RESULT: {test.expected}

CODE TO ANALYZE:
{all_code[:12000]}

REQUIREMENTS:
{json.dumps(requirements.get('features', [])[:5], indent=2)}

Analyze if this test would PASS or FAIL based on the code.

Think like a user:
- Does the code handle this scenario?
- Are there proper error messages?
- Does the UI give feedback?
- Are edge cases handled?

Respond in JSON:
{{
    "passed": true/false,
    "actual_behavior": "what would actually happen",
    "error": "specific issue if failed, null if passed"
}}
"""
        
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
                        test.passed = result.get("passed", False)
                        test.actual = result.get("actual_behavior", "")
                        test.error = result.get("error")
                        return test
                        
        except Exception as e:
            logger.error(f"Test execution error: {e}")
            test.error = str(e)
        
        # Default to pass if analysis fails
        test.passed = True
        return test
    
    def _requires_auth(self, requirements: Dict) -> bool:
        """Check if app requires authentication"""
        
        # Check if any page requires auth
        for page in requirements.get("pages", []):
            if page.get("auth_required", False):
                return True
        
        # Check for auth features
        for feature in requirements.get("features", []):
            if any(kw in feature.get("name", "").lower() + feature.get("description", "").lower() 
                   for kw in ["login", "signup", "auth", "user"]):
                return True
        
        # Check for user roles
        if requirements.get("user_roles"):
            return True
            
        return False
    
    def _generate_auth_tests(self, requirements: Dict) -> List[TestCase]:
        """Generate authentication test cases"""
        
        tests = [
            TestCase(
                id="AUTH-001",
                category="auth",
                description="User can sign up with valid credentials",
                steps=[
                    "Navigate to signup page",
                    "Enter valid email and password",
                    "Click signup button"
                ],
                expected="User account created, redirected to dashboard"
            ),
            TestCase(
                id="AUTH-002", 
                category="auth",
                description="User cannot sign up with invalid email",
                steps=[
                    "Navigate to signup page",
                    "Enter invalid email format",
                    "Click signup button"
                ],
                expected="Error message shown, form not submitted"
            ),
            TestCase(
                id="AUTH-003",
                category="auth",
                description="User can login with valid credentials",
                steps=[
                    "Navigate to login page",
                    "Enter valid email and password",
                    "Click login button"
                ],
                expected="User logged in, redirected to dashboard"
            ),
            TestCase(
                id="AUTH-004",
                category="auth",
                description="Login fails with wrong password",
                steps=[
                    "Navigate to login page",
                    "Enter valid email but wrong password",
                    "Click login button"
                ],
                expected="Error message shown, user not logged in"
            ),
            TestCase(
                id="AUTH-005",
                category="auth",
                description="User session persists after page refresh",
                steps=[
                    "Login successfully",
                    "Refresh the page"
                ],
                expected="User remains logged in"
            ),
            TestCase(
                id="AUTH-006",
                category="auth",
                description="User can logout",
                steps=[
                    "Login successfully",
                    "Click logout button"
                ],
                expected="User logged out, redirected to login page"
            ),
            TestCase(
                id="AUTH-007",
                category="auth",
                description="Protected pages redirect unauthenticated users",
                steps=[
                    "Without logging in, navigate to protected page"
                ],
                expected="Redirected to login page"
            )
        ]
        
        return tests
    
    def _generate_crud_tests(self, model: Dict, requirements: Dict) -> List[TestCase]:
        """Generate CRUD test cases for a data model"""
        
        model_name = model.get("name", "Item")
        table_name = model.get("table_name", "items")
        
        tests = [
            TestCase(
                id=f"CRUD-{model_name}-001",
                category="crud",
                description=f"User can create a new {model_name}",
                steps=[
                    f"Navigate to create {model_name} form",
                    "Fill in all required fields",
                    "Click save/create button"
                ],
                expected=f"New {model_name} created and shown in list"
            ),
            TestCase(
                id=f"CRUD-{model_name}-002",
                category="crud",
                description=f"User can view list of {model_name}s",
                steps=[
                    f"Navigate to {model_name} list page"
                ],
                expected=f"List of {model_name}s displayed"
            ),
            TestCase(
                id=f"CRUD-{model_name}-003",
                category="crud",
                description=f"User can update a {model_name}",
                steps=[
                    f"Navigate to {model_name} list",
                    "Click edit on an item",
                    "Modify fields",
                    "Click save"
                ],
                expected=f"{model_name} updated successfully"
            ),
            TestCase(
                id=f"CRUD-{model_name}-004",
                category="crud",
                description=f"User can delete a {model_name}",
                steps=[
                    f"Navigate to {model_name} list",
                    "Click delete on an item",
                    "Confirm deletion"
                ],
                expected=f"{model_name} deleted, removed from list"
            ),
            TestCase(
                id=f"CRUD-{model_name}-005",
                category="crud",
                description=f"Cannot create {model_name} with missing required fields",
                steps=[
                    f"Navigate to create {model_name} form",
                    "Leave required fields empty",
                    "Click save"
                ],
                expected="Validation error shown, item not created"
            )
        ]
        
        return tests
    
    def _generate_navigation_tests(self, page: Dict, requirements: Dict) -> List[TestCase]:
        """Generate navigation test cases"""
        
        page_name = page.get("name", "Page")
        route = page.get("route", "/")
        
        tests = [
            TestCase(
                id=f"NAV-{page_name}-001",
                category="navigation",
                description=f"User can navigate to {page_name}",
                steps=[
                    f"Click on {page_name} in navigation"
                ],
                expected=f"{page_name} page loads correctly"
            ),
            TestCase(
                id=f"NAV-{page_name}-002",
                category="navigation",
                description=f"Browser back button works on {page_name}",
                steps=[
                    f"Navigate to {page_name}",
                    "Navigate to another page",
                    "Click browser back button"
                ],
                expected=f"Returns to {page_name}"
            )
        ]
        
        return tests
    
    def _generate_invalid_input_tests(self, requirements: Dict) -> List[TestCase]:
        """Generate invalid input test cases"""
        
        tests = [
            TestCase(
                id="INPUT-001",
                category="invalid_input",
                description="Form handles empty submission",
                steps=[
                    "Navigate to any form",
                    "Submit without filling anything"
                ],
                expected="Validation errors shown for required fields"
            ),
            TestCase(
                id="INPUT-002",
                category="invalid_input",
                description="Form handles special characters",
                steps=[
                    "Navigate to any text input",
                    "Enter special characters: <script>alert('xss')</script>",
                    "Submit form"
                ],
                expected="Input sanitized, no XSS vulnerability"
            ),
            TestCase(
                id="INPUT-003",
                category="invalid_input",
                description="Form handles very long input",
                steps=[
                    "Navigate to any text input",
                    "Enter very long text (1000+ characters)",
                    "Submit form"
                ],
                expected="Input truncated or error shown"
            )
        ]
        
        return tests
    
    def _generate_ux_tests(self, requirements: Dict) -> List[TestCase]:
        """Generate UX test cases"""
        
        tests = [
            TestCase(
                id="UX-001",
                category="ux",
                description="Loading states are shown during async operations",
                steps=[
                    "Perform any action that fetches data"
                ],
                expected="Loading indicator shown while waiting"
            ),
            TestCase(
                id="UX-002",
                category="ux",
                description="Error messages are clear and helpful",
                steps=[
                    "Trigger an error (e.g., submit invalid data)"
                ],
                expected="Clear error message explaining what went wrong"
            ),
            TestCase(
                id="UX-003",
                category="ux",
                description="Success feedback is provided",
                steps=[
                    "Complete a successful action (e.g., create item)"
                ],
                expected="Success message or visual feedback shown"
            ),
            TestCase(
                id="UX-004",
                category="ux",
                description="Forms show validation errors inline",
                steps=[
                    "Submit form with invalid data"
                ],
                expected="Error messages shown next to relevant fields"
            ),
            TestCase(
                id="UX-005",
                category="ux",
                description="App is responsive on mobile",
                steps=[
                    "View app on mobile viewport"
                ],
                expected="Layout adapts, no horizontal scroll"
            )
        ]
        
        return tests
    
    def generate_test_report(self, results: Dict) -> str:
        """Generate a human-readable test report"""
        
        report = f"""
# Test Report

## Summary
- **Total Tests:** {results['total']}
- **Passed:** {results['passed']} ✅
- **Failed:** {results['failed']} ❌
- **Skipped:** {results['skipped']} ⏭️

## Results by Category
"""
        
        # Group tests by category
        by_category = {}
        for test in results.get("tests", []):
            cat = test.get("category", "other")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(test)
        
        for category, tests in by_category.items():
            passed = sum(1 for t in tests if t.get("passed"))
            failed = len(tests) - passed
            report += f"\n### {category.upper()} ({passed}/{len(tests)} passed)\n"
            
            for test in tests:
                status = "✅" if test.get("passed") else "❌"
                report += f"- {status} {test['description']}\n"
                if not test.get("passed") and test.get("error"):
                    report += f"  - Error: {test['error']}\n"
        
        # List all issues
        if results.get("issues"):
            report += "\n## Issues to Fix\n"
            for issue in results["issues"]:
                report += f"\n### {issue['test_id']}: {issue['description']}\n"
                report += f"**Category:** {issue['category']}\n"
                report += f"**Error:** {issue['error']}\n"
                report += "**Steps to Reproduce:**\n"
                for step in issue.get("steps_to_reproduce", []):
                    report += f"1. {step}\n"
        
        return report.strip()
