#!/usr/bin/env python3
"""
Test script: Create a simple todo app and verify preview works.
Run: python test_todo_app.py
Requires: backend running (uvicorn server:app --port 8000)
"""

import requests
import time
import sys

API_BASE = "http://localhost:8000/api"

def main():
    print("=" * 60)
    print("TODO APP TEST")
    print("=" * 60)
    
    try:
        r = requests.get(f"{API_BASE}/projects", timeout=5)
    except Exception as e:
        print(f"Backend not running: {e}")
        sys.exit(1)
    
    r = requests.post(f"{API_BASE}/projects", json={"name": "Todo Test", "description": "Test"}, timeout=10)
    project_id = r.json().get("id")
    
    print("\nBuilding todo app...")
    r = requests.post(f"{API_BASE}/projects/{project_id}/build", json={
        "prompt": "Create a simple todo app with add, complete, and delete."
    }, timeout=90, stream=True)
    
    if r.status_code != 200:
        print(f"Build failed {r.status_code}, trying generate...")
        r = requests.post(f"{API_BASE}/projects/{project_id}/generate", json={
            "prompt": "Create a simple todo app"
        }, timeout=60)
    
    time.sleep(2)
    preview = requests.get(f"{API_BASE}/projects/{project_id}/preview", timeout=10)
    html = preview.json().get("html", "")
    
    print(f"Preview: {len(html):,} chars")
    print(f"Open: http://localhost:3000/projects/{project_id}")
    print("=" * 60)

if __name__ == "__main__":
    main()
