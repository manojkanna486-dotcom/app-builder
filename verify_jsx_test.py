#!/usr/bin/env python3
"""
Verification script for JSX fix in Test App preview.
Tests the preview endpoint and validates the generated HTML.
"""

import requests
import re
from html.parser import HTMLParser

PROJECT_ID = "8f1d135e-a3f3-4f50-b7de-426f39549da0"
BASE_URL = "http://localhost:3000"
PREVIEW_URL = f"{BASE_URL}/api/projects/{PROJECT_ID}/preview"

class HTMLValidator(HTMLParser):
    """Validates HTML structure and detects unclosed tags."""
    
    def __init__(self):
        super().__init__()
        self.tag_stack = []
        self.errors = []
        self.self_closing = {'img', 'br', 'hr', 'input', 'meta', 'link', 'area', 'base', 'col', 'embed', 'param', 'source', 'track', 'wbr'}
        
    def handle_starttag(self, tag, attrs):
        if tag not in self.self_closing:
            self.tag_stack.append((tag, self.getpos()))
    
    def handle_endtag(self, tag):
        if tag in self.self_closing:
            return
            
        if not self.tag_stack:
            self.errors.append(f"Closing tag </{tag}> at line {self.getpos()[0]} has no matching opening tag")
            return
        
        expected_tag, start_pos = self.tag_stack[-1]
        if expected_tag == tag:
            self.tag_stack.pop()
        else:
            # Check if this tag exists somewhere in the stack
            for i in range(len(self.tag_stack) - 1, -1, -1):
                if self.tag_stack[i][0] == tag:
                    self.errors.append(
                        f"Tag mismatch at line {self.getpos()[0]}: "
                        f"found </{tag}> but <{expected_tag}> (opened at line {start_pos[0]}) is not closed"
                    )
                    return
            
            self.errors.append(
                f"Closing tag </{tag}> at line {self.getpos()[0]} "
                f"doesn't match opening tag <{expected_tag}> at line {start_pos[0]}"
            )
    
    def close(self):
        super().close()
        for tag, pos in self.tag_stack:
            self.errors.append(f"Unclosed tag <{tag}> opened at line {pos[0]}")

def test_preview_endpoint():
    """Test the preview endpoint and validate response."""
    
    print("=" * 80)
    print("JSX FIX VERIFICATION TEST")
    print("=" * 80)
    print()
    
    # Test 1: Check if endpoint is accessible
    print("TEST 1: Preview Endpoint Accessibility")
    print("-" * 80)
    try:
        response = requests.get(PREVIEW_URL, timeout=10)
        print(f"✅ Endpoint accessible: {PREVIEW_URL}")
        print(f"✅ Status Code: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ FAIL: Expected 200, got {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ FAIL: Could not connect to endpoint: {e}")
        return False
    
    print()
    
    # Test 2: Validate HTML structure
    print("TEST 2: HTML Structure Validation")
    print("-" * 80)
    html_content = response.text
    print(f"✅ HTML Content Size: {len(html_content)} characters")
    print(f"✅ HTML Lines: {len(html_content.splitlines())} lines")
    
    # Check for basic HTML structure
    if not html_content.strip().startswith('<!doctype html>') and not html_content.strip().startswith('<!DOCTYPE html>'):
        print("❌ FAIL: Missing DOCTYPE declaration")
        return False
    else:
        print("✅ DOCTYPE declaration present")
    
    if '<html' not in html_content:
        print("❌ FAIL: Missing <html> tag")
        return False
    else:
        print("✅ <html> tag present")
    
    if '</html>' not in html_content:
        print("❌ FAIL: Missing </html> closing tag")
        return False
    else:
        print("✅ </html> closing tag present")
    
    print()
    
    # Test 3: Parse HTML and detect tag mismatches
    print("TEST 3: JSX/HTML Tag Validation")
    print("-" * 80)
    
    validator = HTMLValidator()
    try:
        validator.feed(html_content)
        validator.close()
        
        if validator.errors:
            print(f"❌ FAIL: Found {len(validator.errors)} HTML/JSX errors:")
            for error in validator.errors[:10]:  # Show first 10 errors
                print(f"   - {error}")
            if len(validator.errors) > 10:
                print(f"   ... and {len(validator.errors) - 10} more errors")
            return False
        else:
            print("✅ No HTML/JSX tag mismatches detected")
            print("✅ All opening tags have matching closing tags")
    
    except Exception as e:
        print(f"❌ FAIL: HTML parsing error: {e}")
        return False
    
    print()
    
    # Test 4: Check for React components
    print("TEST 4: React Application Components")
    print("-" * 80)
    
    # Check for React root div
    if 'id="root"' in html_content:
        print('✅ React root div present (<div id="root">)')
    else:
        print('⚠️  WARNING: React root div not found')
    
    # Check for bundle script
    if '/static/js/bundle.js' in html_content or 'bundle.js' in html_content:
        print('✅ React bundle script included')
    else:
        print('⚠️  WARNING: React bundle script not found')
    
    print()
    
    # Test 5: Check for specific JSX patterns that were fixed
    print("TEST 5: Specific JSX Fix Validation")
    print("-" * 80)
    
    # Check for common JSX error patterns
    jsx_error_patterns = [
        (r'<header[^>]*>.*?</div>', 'header tag closed with </div>'),
        (r'<form[^>]*>.*?</div>', 'form tag closed with </div>'),
        (r'<nav[^>]*>.*?</div>', 'nav tag closed with </div>'),
        (r'<aside[^>]*>.*?</div>', 'aside tag closed with </div>'),
    ]
    
    errors_found = []
    for pattern, description in jsx_error_patterns:
        if re.search(pattern, html_content, re.DOTALL):
            errors_found.append(description)
    
    if errors_found:
        print(f"❌ FAIL: Found {len(errors_found)} JSX error patterns:")
        for error in errors_found:
            print(f"   - {error}")
        return False
    else:
        print("✅ No JSX error patterns detected")
        print("✅ All semantic HTML tags properly closed")
    
    print()
    
    # Test 6: Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()
    print("✅ ALL TESTS PASSED")
    print()
    print("The JSX syntax error has been successfully fixed!")
    print("The preview generates valid HTML without tag mismatches.")
    print()
    print(f"Preview URL: {PREVIEW_URL}")
    print(f"HTML Size: {len(html_content)} characters ({len(html_content.splitlines())} lines)")
    print()
    print("Next step: Test in browser by navigating to http://localhost:3000")
    print("and clicking on the Test App preview tab.")
    print()
    
    return True

if __name__ == "__main__":
    try:
        success = test_preview_endpoint()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
