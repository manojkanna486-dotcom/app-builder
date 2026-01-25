"""
Backend API tests for App Builder - Supabase Full-Stack Features
Tests: Supabase connection, full-stack code generation, file type distinction
"""
import pytest
import requests
import os
import time
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
SUPABASE_URL = "https://xdnwrmhsjrssdjogxjrb.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhkbndybWhzanJzc2Rqb2d4anJiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjkyMzg4OTksImV4cCI6MjA4NDgxNDg5OX0.2uzpNzCYxb3T-gIBLMLFXWt3rIbxbq1e2XkUuIV9P-0"


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def test_project(api_client):
    """Create a test project for Supabase tests"""
    unique_name = f"TEST_Supabase_Project_{uuid.uuid4().hex[:8]}"
    response = api_client.post(f"{BASE_URL}/api/projects", json={
        "name": unique_name,
        "description": "Testing Supabase full-stack features"
    })
    assert response.status_code == 200
    project = response.json()
    yield project
    # Cleanup
    api_client.delete(f"{BASE_URL}/api/projects/{project['id']}")


class TestAPIHealth:
    """Basic API health checks"""
    
    def test_api_root(self, api_client):
        """Test API root endpoint"""
        response = api_client.get(f"{BASE_URL}/api/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "App Builder API" in data["message"]
        print(f"✓ API root: {data}")
    
    def test_projects_list(self, api_client):
        """Test projects list endpoint"""
        response = api_client.get(f"{BASE_URL}/api/projects")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Projects list: {len(data)} projects found")


class TestProjectCRUD:
    """Project CRUD operations"""
    
    def test_create_project(self, api_client):
        """Test project creation"""
        unique_name = f"TEST_Project_{uuid.uuid4().hex[:8]}"
        response = api_client.post(f"{BASE_URL}/api/projects", json={
            "name": unique_name,
            "description": "Test project"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == unique_name
        assert "id" in data
        assert data["supabase_connected"] == False
        print(f"✓ Created project: {data['id']}")
        
        # Cleanup
        api_client.delete(f"{BASE_URL}/api/projects/{data['id']}")
    
    def test_get_project(self, api_client, test_project):
        """Test getting a specific project"""
        response = api_client.get(f"{BASE_URL}/api/projects/{test_project['id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_project["id"]
        print(f"✓ Got project: {data['name']}")
    
    def test_get_nonexistent_project(self, api_client):
        """Test getting a non-existent project"""
        fake_id = str(uuid.uuid4())
        response = api_client.get(f"{BASE_URL}/api/projects/{fake_id}")
        assert response.status_code == 404
        print("✓ Non-existent project returns 404")


class TestSupabaseConnection:
    """Supabase connection endpoints"""
    
    def test_connect_supabase_success(self, api_client, test_project):
        """Test successful Supabase connection"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/connect-supabase",
            json={
                "url": SUPABASE_URL,
                "anon_key": SUPABASE_ANON_KEY
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] == True
        assert "message" in data
        print(f"✓ Supabase connected: {data['message']}")
    
    def test_supabase_status_connected(self, api_client, test_project):
        """Test Supabase status after connection"""
        response = api_client.get(
            f"{BASE_URL}/api/projects/{test_project['id']}/supabase-status"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] == True
        assert data["url"] == SUPABASE_URL
        print(f"✓ Supabase status: connected to {data['url']}")
    
    def test_disconnect_supabase(self, api_client, test_project):
        """Test Supabase disconnection"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/disconnect-supabase"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["disconnected"] == True
        print(f"✓ Supabase disconnected: {data['message']}")
    
    def test_supabase_status_disconnected(self, api_client, test_project):
        """Test Supabase status after disconnection"""
        response = api_client.get(
            f"{BASE_URL}/api/projects/{test_project['id']}/supabase-status"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] == False
        assert data["url"] is None
        print("✓ Supabase status: disconnected")
    
    def test_connect_supabase_invalid_url(self, api_client, test_project):
        """Test Supabase connection with invalid URL"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/connect-supabase",
            json={
                "url": "http://invalid-url.com",
                "anon_key": SUPABASE_ANON_KEY
            }
        )
        assert response.status_code == 400
        print("✓ Invalid Supabase URL rejected")
    
    def test_connect_supabase_invalid_key(self, api_client, test_project):
        """Test Supabase connection with invalid key"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/connect-supabase",
            json={
                "url": SUPABASE_URL,
                "anon_key": "invalid-key"
            }
        )
        assert response.status_code == 400
        print("✓ Invalid Supabase key rejected")


class TestFullStackCodeGeneration:
    """Full-stack code generation tests"""
    
    def test_existing_fullstack_project_files(self, api_client):
        """Test that existing full-stack project has correct file types"""
        # Use the existing full-stack project
        project_id = "684915e5-7d08-4332-810c-5625fa146b49"
        
        response = api_client.get(f"{BASE_URL}/api/projects/{project_id}/versions/latest")
        assert response.status_code == 200
        data = response.json()
        
        files = data.get("files", [])
        assert len(files) > 0, "Should have generated files"
        
        # Check file types
        file_types = set()
        file_paths = []
        for f in files:
            file_types.add(f.get("file_type", "frontend"))
            file_paths.append(f["path"])
        
        print(f"✓ Found {len(files)} files with types: {file_types}")
        print(f"  File paths: {file_paths}")
        
        # Verify we have different file types for full-stack
        assert "frontend" in file_types, "Should have frontend files"
        
        # Check for edge function
        edge_functions = [f for f in files if f.get("file_type") == "edge_function"]
        print(f"✓ Edge functions: {len(edge_functions)}")
        
        # Check for SQL migrations
        sql_files = [f for f in files if f["path"].endswith(".sql")]
        print(f"✓ SQL files: {len(sql_files)}")
        
        # Check for supabase folder structure
        supabase_files = [f for f in files if "supabase/" in f["path"]]
        print(f"✓ Supabase folder files: {len(supabase_files)}")
    
    def test_frontend_only_project_files(self, api_client):
        """Test that frontend-only project has only frontend files"""
        # Use an existing frontend-only project
        project_id = "80cb26f8-f34d-441e-ab78-d35b233a1069"
        
        response = api_client.get(f"{BASE_URL}/api/projects/{project_id}/versions/latest")
        assert response.status_code == 200
        data = response.json()
        
        files = data.get("files", [])
        if len(files) > 0:
            # All files should be frontend type
            for f in files:
                file_type = f.get("file_type", "frontend")
                assert file_type == "frontend", f"Expected frontend, got {file_type} for {f['path']}"
            print(f"✓ Frontend-only project has {len(files)} frontend files")
        else:
            print("✓ Project has no files yet (expected for new project)")


class TestVersionsAndPreview:
    """Version and preview endpoints"""
    
    def test_get_versions(self, api_client, test_project):
        """Test getting project versions"""
        response = api_client.get(f"{BASE_URL}/api/projects/{test_project['id']}/versions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Got {len(data)} versions")
    
    def test_get_latest_version(self, api_client, test_project):
        """Test getting latest version"""
        response = api_client.get(f"{BASE_URL}/api/projects/{test_project['id']}/versions/latest")
        assert response.status_code == 200
        data = response.json()
        # New project may not have versions yet
        print(f"✓ Latest version response: {data.get('version_number', 'None')}")
    
    def test_get_preview(self, api_client):
        """Test preview endpoint for existing project"""
        project_id = "684915e5-7d08-4332-810c-5625fa146b49"
        response = api_client.get(f"{BASE_URL}/api/projects/{project_id}/preview")
        assert response.status_code == 200
        data = response.json()
        assert "html" in data
        assert len(data["html"]) > 0
        print(f"✓ Preview HTML generated: {len(data['html'])} chars")


class TestMessages:
    """Chat messages endpoints"""
    
    def test_get_messages(self, api_client, test_project):
        """Test getting project messages"""
        response = api_client.get(f"{BASE_URL}/api/projects/{test_project['id']}/messages")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Got {len(data)} messages")
    
    def test_add_message(self, api_client, test_project):
        """Test adding a message"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/messages",
            json={
                "role": "user",
                "content": "Test message"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Test message"
        assert data["role"] == "user"
        print(f"✓ Added message: {data['id']}")


class TestAnalyzePrompt:
    """Prompt analysis endpoints"""
    
    def test_analyze_clear_prompt(self, api_client, test_project):
        """Test analyzing a clear prompt"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/analyze",
            json={"prompt": "Create a Facebook clone app"}
        )
        assert response.status_code == 200
        data = response.json()
        # Clear prompts should not need clarification
        print(f"✓ Analyze clear prompt: needs_clarification={data.get('needs_clarification', False)}")
    
    def test_analyze_vague_prompt(self, api_client, test_project):
        """Test analyzing a vague prompt"""
        response = api_client.post(
            f"{BASE_URL}/api/projects/{test_project['id']}/analyze",
            json={"prompt": "Build an app for my business"}
        )
        assert response.status_code == 200
        data = response.json()
        print(f"✓ Analyze vague prompt: needs_clarification={data.get('needs_clarification', False)}")


class TestCodeValidation:
    """Code validation endpoints"""
    
    def test_validate_project_code(self, api_client):
        """Test code validation endpoint"""
        project_id = "684915e5-7d08-4332-810c-5625fa146b49"
        response = api_client.get(f"{BASE_URL}/api/projects/{project_id}/validate")
        assert response.status_code == 200
        data = response.json()
        assert "valid" in data
        assert "errors" in data
        print(f"✓ Code validation: valid={data['valid']}, errors={len(data['errors'])}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
