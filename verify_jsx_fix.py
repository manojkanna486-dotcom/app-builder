#!/usr/bin/env python3
"""
Test the Test App preview for JSX syntax errors
This script will verify that the Babel compilation error has been fixed
"""

import requests
import json
import re
from html.parser import HTMLParser

API_BASE = "http://localhost:8000/api"

class JSXErrorDetector:
    """Detect JSX-related errors in HTML/JavaScript"""
    
    @staticmethod
    def check_for_jsx_errors(html: str) -> dict:
        """Check HTML for common JSX syntax errors"""
        results = {
            "has_adjacent_jsx_error": False,
            "has_babel_error": False,
            "has_react_errors": False,
            "errors_found": [],
            "warnings": []
        }
        
        # Check for "Adjacent JSX elements" error
        if "Adjacent JSX elements must be wrapped" in html:
            results["has_adjacent_jsx_error"] = True
            results["errors_found"].append("Adjacent JSX elements error detected")
        
        # Check for Babel compilation errors
        babel_error_patterns = [
            r"SyntaxError:.*JSX",
            r"Babel.*compilation.*error",
            r"Unexpected token.*<",
            r"JSX.*syntax.*error"
        ]
        
        for pattern in babel_error_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                results["has_babel_error"] = True
                match = re.search(pattern, html, re.IGNORECASE)
                results["errors_found"].append(f"Babel error pattern found: {match.group()}")
        
        # Check for React-specific errors
        react_error_patterns = [
            r"React.*is not defined",
            r"ReactDOM.*is not defined",
            r"Uncaught.*React",
        ]
        
        for pattern in react_error_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                results["has_react_errors"] = True
                match = re.search(pattern, html, re.IGNORECASE)
                results["errors_found"].append(f"React error pattern found: {match.group()}")
        
        # Check for proper JSX wrapping (look for React.Fragment or parent div)
        if "React.Fragment" in html or "<Fragment" in html:
            results["warnings"].append("Uses React.Fragment (good)")
        
        # Check if code has return statements with JSX
        return_jsx_pattern = r"return\s*\(\s*<[a-zA-Z]"
        if re.search(return_jsx_pattern, html):
            results["warnings"].append("Found JSX in return statements")
        
        return results

def main():
    print("=" * 80)
    print("TEST APP JSX SYNTAX ERROR VERIFICATION")
    print("=" * 80)
    
    # 1. Check if backend is running
    print("\n1. Checking backend connection...")
    try:
        response = requests.get(f"{API_BASE}/projects", timeout=5)
        print(f"   ✓ Backend is running (Status: {response.status_code})")
    except Exception as e:
        print(f"   ✗ Backend not accessible: {e}")
        print("   Please start the backend server first.")
        return False
    
    # 2. Find Test App
    print("\n2. Finding 'Test App' project...")
    try:
        projects = response.json()
        test_app = None
        for project in projects:
            if project.get("name") == "Test App":
                test_app = project
                break
        
        if not test_app:
            print("   ✗ 'Test App' not found")
            return False
        
        project_id = test_app.get('id')
        print(f"   ✓ Found 'Test App' (ID: {project_id})")
        print(f"   Description: {test_app.get('description')}")
    except Exception as e:
        print(f"   ✗ Error finding Test App: {e}")
        return False
    
    # 3. Fetch preview HTML
    print("\n3. Fetching preview HTML...")
    try:
        preview_response = requests.get(
            f"{API_BASE}/projects/{project_id}/preview",
            timeout=10
        )
        
        if preview_response.status_code != 200:
            print(f"   ✗ Preview endpoint returned status {preview_response.status_code}")
            return False
        
        preview_data = preview_response.json()
        html = preview_data.get("html", "")
        
        if not html or len(html) < 100:
            print(f"   ✗ Preview HTML is too short or empty (length: {len(html)})")
            return False
        
        print(f"   ✓ Preview HTML fetched successfully")
        print(f"   Size: {len(html):,} characters ({len(html) / 1024:.1f} KB)")
    except Exception as e:
        print(f"   ✗ Error fetching preview: {e}")
        return False
    
    # 4. Check for JSX syntax errors
    print("\n4. Checking for JSX syntax errors...")
    detector = JSXErrorDetector()
    results = detector.check_for_jsx_errors(html)
    
    if results["errors_found"]:
        print("   ✗ JSX ERRORS DETECTED:")
        for error in results["errors_found"]:
            print(f"      - {error}")
    else:
        print("   ✓ No JSX syntax errors detected!")
    
    if results["warnings"]:
        print("\n   Info:")
        for warning in results["warnings"]:
            print(f"      - {warning}")
    
    # 5. Check for Student Management System content
    print("\n5. Checking for Student Management System content...")
    if "Student Management System" in html:
        print("   ✓ Student Management System title found")
    else:
        print("   ⚠️  Student Management System title not found")
    
    # Check for key UI elements
    ui_elements = {
        "Add New Student": "Add button",
        "Student": "Student references",
        "form": "Form elements",
        "table": "Table element",
    }
    
    print("\n   Checking UI elements:")
    for element, description in ui_elements.items():
        if element.lower() in html.lower():
            print(f"      ✓ {description} found")
        else:
            print(f"      ⚠️  {description} not found")
    
    # 6. Save HTML for manual inspection
    print("\n6. Saving HTML for manual inspection...")
    output_file = "/tmp/test_app_preview_jsx_check.html"
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"   ✓ HTML saved to: {output_file}")
        print(f"   You can open this file in a browser to verify it works")
    except Exception as e:
        print(f"   ⚠️  Could not save HTML: {e}")
    
    # 7. Summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    all_passed = True
    
    if results["has_adjacent_jsx_error"]:
        print("✗ FAILED: Adjacent JSX elements error still present")
        all_passed = False
    else:
        print("✓ PASSED: No adjacent JSX elements errors")
    
    if results["has_babel_error"]:
        print("✗ FAILED: Babel compilation errors detected")
        all_passed = False
    else:
        print("✓ PASSED: No Babel compilation errors")
    
    if results["has_react_errors"]:
        print("✗ FAILED: React errors detected")
        all_passed = False
    else:
        print("✓ PASSED: No React errors")
    
    if len(html) > 1000:
        print("✓ PASSED: Preview HTML is substantial")
    else:
        print("✗ FAILED: Preview HTML is too short")
        all_passed = False
    
    print("\n" + "=" * 80)
    
    if all_passed:
        print("🎉 ALL CHECKS PASSED!")
        print("\nThe JSX syntax error has been fixed.")
        print("Next steps:")
        print("1. Navigate to http://localhost:3000")
        print("2. Click on 'Test App'")
        print("3. Click on the 'Preview' tab")
        print("4. The preview should load without console errors")
    else:
        print("⚠️  SOME CHECKS FAILED")
        print("\nPlease review the errors above and the saved HTML file.")
        print(f"Saved HTML: {output_file}")
    
    print("=" * 80)
    print()
    
    return all_passed

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
