#!/usr/bin/env python3
"""
Test script to diagnose the Test App preview issue
"""

import requests
import json

API_BASE = "http://localhost:8000/api"

def main():
    print("=" * 80)
    print("TEST APP PREVIEW DIAGNOSTICS")
    print("=" * 80)
    
    # 1. Check if backend is running
    print("\n1. Checking if backend is running...")
    try:
        response = requests.get(f"{API_BASE}/projects", timeout=5)
        print(f"   ✓ Backend is running (Status: {response.status_code})")
    except Exception as e:
        print(f"   ✗ Backend not accessible: {e}")
        return
    
    # 2. Get all projects
    print("\n2. Fetching projects...")
    try:
        projects = response.json()
        print(f"   ✓ Found {len(projects)} projects")
    except Exception as e:
        print(f"   ✗ Failed to parse projects: {e}")
        return
    
    # 3. Find "Test App"
    print("\n3. Looking for 'Test App'...")
    test_app = None
    for project in projects:
        if project.get("name") == "Test App":
            test_app = project
            break
    
    if not test_app:
        print("   ✗ 'Test App' not found in projects")
        print("\n   Available projects:")
        for p in projects:
            print(f"      - {p.get('name')} (ID: {p.get('id')})")
        return
    
    print(f"   ✓ Found 'Test App'")
    print(f"      ID: {test_app.get('id')}")
    print(f"      Description: {test_app.get('description')}")
    
    project_id = test_app.get('id')
    
    # 4. Get preview HTML
    print("\n4. Fetching preview HTML...")
    try:
        preview_response = requests.get(f"{API_BASE}/projects/{project_id}/preview", timeout=10)
        print(f"   ✓ Preview endpoint responded (Status: {preview_response.status_code})")
        
        preview_data = preview_response.json()
        html = preview_data.get("html", "")
        
        print(f"\n   Preview HTML stats:")
        print(f"      - Length: {len(html):,} characters ({len(html) / 1024:.1f} KB)")
        print(f"      - Has <html> tag: {'<html' in html}")
        print(f"      - Has <body> tag: {'<body' in html}")
        print(f"      - Has React: {'React' in html}")
        print(f"      - Has Babel: {'babel' in html.lower()}")
        
        # Check first 500 chars
        print(f"\n   First 500 characters:")
        print(f"      {html[:500]}")
        
        # Check if it's just placeholder
        if "No preview available" in html or len(html) < 1000:
            print("\n   ⚠️  Preview appears to be placeholder or too short")
        else:
            print("\n   ✓ Preview HTML looks substantial")
        
        # Save to file for inspection
        output_file = "/tmp/test_app_preview.html"
        with open(output_file, "w") as f:
            f.write(html)
        print(f"\n   ✓ Full HTML saved to: {output_file}")
        print(f"      You can open this file in a browser to test")
        
    except Exception as e:
        print(f"   ✗ Failed to fetch preview: {e}")
        return
    
    # 5. Get files for the project
    print("\n5. Checking project files...")
    try:
        files_response = requests.get(f"{API_BASE}/projects/{project_id}/files", timeout=10)
        if files_response.status_code == 200:
            files = files_response.json()
            print(f"   ✓ Project has {len(files)} files")
            
            # Group by type
            by_type = {}
            for f in files:
                file_type = f.get("file_type", "unknown")
                by_type[file_type] = by_type.get(file_type, 0) + 1
            
            print("\n   Files by type:")
            for ftype, count in by_type.items():
                print(f"      - {ftype}: {count}")
            
            print("\n   All files:")
            for f in files:
                path = f.get("path", "unknown")
                content_len = len(f.get("content", ""))
                print(f"      - {path} ({content_len} chars)")
        else:
            print(f"   ⚠️  Could not fetch files (Status: {files_response.status_code})")
    except Exception as e:
        print(f"   ⚠️  Error checking files: {e}")
    
    print("\n" + "=" * 80)
    print("DIAGNOSTICS COMPLETE")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Open /tmp/test_app_preview.html in your browser to see if HTML works")
    print("2. Check browser console in the app at http://localhost:3000")
    print("3. Look for JavaScript errors that might prevent preview from showing")
    print("\n")

if __name__ == "__main__":
    main()
