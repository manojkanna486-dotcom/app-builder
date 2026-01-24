#!/usr/bin/env python3

import requests
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

class AppBuilderAPITester:
    def __init__(self, base_url="https://appbuilder-sde.preview.emergentagent.com/api"):
        self.base_url = base_url
        self.tests_run = 0
        self.tests_passed = 0
        self.project_id = None
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})

    def run_test(self, name: str, method: str, endpoint: str, expected_status: int, 
                 data: Optional[Dict] = None, timeout: int = 30) -> tuple[bool, Dict]:
        """Run a single API test"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = self.session.get(url, timeout=timeout)
            elif method == 'POST':
                response = self.session.post(url, json=data, timeout=timeout)
            elif method == 'DELETE':
                response = self.session.delete(url, timeout=timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")

            success = response.status_code == expected_status
            
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    if isinstance(response_data, dict) and len(str(response_data)) < 200:
                        print(f"   Response: {response_data}")
                except:
                    pass
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")

            try:
                return success, response.json() if response.text else {}
            except:
                return success, {"raw_response": response.text}

        except requests.exceptions.Timeout:
            print(f"❌ Failed - Request timeout after {timeout}s")
            return False, {"error": "timeout"}
        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {"error": str(e)}

    def test_root_endpoint(self):
        """Test API root endpoint"""
        return self.run_test("API Root", "GET", "/", 200)

    def test_get_projects_empty(self):
        """Test getting projects when none exist"""
        return self.run_test("Get Projects (Empty)", "GET", "/projects", 200)

    def test_create_project(self):
        """Test creating a new project"""
        project_data = {
            "name": f"Test Project {datetime.now().strftime('%H%M%S')}",
            "description": "A test project for API testing"
        }
        
        success, response = self.run_test(
            "Create Project", 
            "POST", 
            "/projects", 
            200, 
            project_data
        )
        
        if success and 'id' in response:
            self.project_id = response['id']
            print(f"   Created project ID: {self.project_id}")
            return True, response
        return False, response

    def test_get_projects_with_data(self):
        """Test getting projects when data exists"""
        return self.run_test("Get Projects (With Data)", "GET", "/projects", 200)

    def test_get_project_by_id(self):
        """Test getting a specific project by ID"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Get Project by ID", 
            "GET", 
            f"/projects/{self.project_id}", 
            200
        )

    def test_get_project_messages(self):
        """Test getting project messages"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Get Project Messages", 
            "GET", 
            f"/projects/{self.project_id}/messages", 
            200
        )

    def test_get_project_versions(self):
        """Test getting project versions"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Get Project Versions", 
            "GET", 
            f"/projects/{self.project_id}/versions", 
            200
        )

    def test_get_project_preview(self):
        """Test getting project preview HTML"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Get Project Preview", 
            "GET", 
            f"/projects/{self.project_id}/preview", 
            200
        )

    def test_generate_code(self):
        """Test code generation with OpenRouter LLM"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        prompt_data = {
            "prompt": "Create a simple React counter app with increment and decrement buttons"
        }
        
        print("   ⚠️  This test may take 30-60 seconds due to LLM processing...")
        return self.run_test(
            "Generate Code", 
            "POST", 
            f"/projects/{self.project_id}/generate", 
            200, 
            prompt_data,
            timeout=90  # Extended timeout for LLM
        )

    def test_get_latest_version(self):
        """Test getting latest version after generation"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Get Latest Version", 
            "GET", 
            f"/projects/{self.project_id}/versions/latest", 
            200
        )

    def test_add_message(self):
        """Test adding a chat message"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        message_data = {
            "role": "user",
            "content": "This is a test message"
        }
        
        return self.run_test(
            "Add Message", 
            "POST", 
            f"/projects/{self.project_id}/messages", 
            200, 
            message_data
        )

    def test_analyze_vague_prompt(self):
        """Test prompt analysis for vague prompts (should need clarification)"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        vague_prompt_data = {
            "prompt": "Build a dashboard for my business"
        }
        
        success, response = self.run_test(
            "Analyze Vague Prompt", 
            "POST", 
            f"/projects/{self.project_id}/analyze", 
            200, 
            vague_prompt_data
        )
        
        if success and response.get("needs_clarification"):
            print(f"   ✅ Correctly identified need for clarification")
            if response.get("questions"):
                print(f"   ✅ Generated {len(response['questions'])} clarification questions")
            return True, response
        elif success and not response.get("needs_clarification"):
            print(f"   ⚠️  Expected clarification but got none")
            return False, response
        return success, response

    def test_analyze_clear_prompt(self):
        """Test prompt analysis for clear prompts (should skip clarification)"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        clear_prompt_data = {
            "prompt": "Create a Facebook clone app with posts, likes, and comments"
        }
        
        success, response = self.run_test(
            "Analyze Clear Prompt", 
            "POST", 
            f"/projects/{self.project_id}/analyze", 
            200, 
            clear_prompt_data
        )
        
        if success and not response.get("needs_clarification"):
            print(f"   ✅ Correctly skipped clarification for clear prompt")
            return True, response
        elif success and response.get("needs_clarification"):
            print(f"   ⚠️  Unexpected clarification request for clear prompt")
            return False, response
        return success, response

    def test_generate_with_context(self):
        """Test code generation with clarification context"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        context_data = {
            "original_prompt": "Build a dashboard",
            "answers": {
                "q1": "Sales and revenue metrics",
                "q2": "Professional corporate style",
                "q3": "Desktop-first design"
            }
        }
        
        print("   ⚠️  This test may take 30-60 seconds due to LLM processing...")
        return self.run_test(
            "Generate with Context", 
            "POST", 
            f"/projects/{self.project_id}/generate-with-context", 
            200, 
            context_data,
            timeout=90
        )

    def test_delete_project(self):
        """Test deleting a project"""
        if not self.project_id:
            print("❌ Skipped - No project ID available")
            return False, {}
        
        return self.run_test(
            "Delete Project", 
            "DELETE", 
            f"/projects/{self.project_id}", 
            200
        )

    def run_all_tests(self):
        """Run all API tests in sequence"""
        print("🚀 Starting App Builder API Tests")
        print(f"   Base URL: {self.base_url}")
        print("=" * 60)

        # Test sequence
        tests = [
            self.test_root_endpoint,
            self.test_get_projects_empty,
            self.test_create_project,
            self.test_get_projects_with_data,
            self.test_get_project_by_id,
            self.test_get_project_messages,
            self.test_get_project_versions,
            self.test_get_project_preview,
            self.test_generate_code,
            self.test_get_latest_version,
            self.test_add_message,
            self.test_get_project_messages,  # Check messages again after adding
            self.test_delete_project,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                print(f"❌ Test {test.__name__} crashed: {str(e)}")

        # Print results
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    tester = AppBuilderAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())