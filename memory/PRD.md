# Multi-Agent App Builder - Product Requirements Document

## Original Problem Statement
Build a full-stack "App Builder" that generates FastAPI backends and React frontends based on user prompts. The application uses a multi-agent system to orchestrate the entire software creation process using Supabase for database and authentication.

## Current Status (Feb 10, 2026)
**✅ E2E Pipeline Working** - Successfully generating and previewing applications
**✅ Model Configuration Updated** - Cost-optimized model selection per agent
**✅ Intelligent Fix Agent** - Can analyze and fix user-reported errors

## Model Configuration (Updated Feb 10, 2026)
```
Agent Architecture:
User Prompt
    ↓
Orchestrator (Router Pattern)
    ↓
├── Requirements Agent: Claude 3.5 Sonnet
├── Dev Agent (UI): GPT-4o mini  
├── Dev Agent (Backend): Gemini 1.5 Pro
├── Tester: o1-mini
├── Fix Agent: DeepSeek Chat
└── Deployment Agent: Claude Haiku
```

## Agent Architecture (Refactored Feb 3, 2026)

### 1. Orchestrator Agent (Brain)
**File:** `/app/backend/agents/orchestrator_v2.py`

**Responsibilities:**
- Owns the entire workflow
- Decides which agent runs and in what order
- Passes context between agents
- Enforces system rules and limits

### 2. Requirements Agent
**File:** `/app/backend/agents/requirements_agent.py`

**Responsibilities:**
- Convert user prompt into structured requirements JSON
- Parse prompt into: Features, Pages, User roles, Data models

### 3. Code Generation Agent
**File:** `/app/backend/agents/code_generation_agent.py`

**Responsibilities:**
- Generate complete application code based on requirements
- Creates: App.jsx, Components, SQL migrations, Hooks

### 4. Tester Agent (Stub)
**File:** `/app/backend/agents/tester_agent.py`

### 5. Fix Agent (Stub)
**File:** `/app/backend/agents/fix_agent.py`

## Job System
**File:** `/app/backend/job_manager.py`

- Async job processing runs in background
- Jobs persist to MongoDB `jobs` collection
- States: pending → parsing → generating → deploying → testing → completed/failed
- Frontend polls for status updates

## Key Technical Details

### Preview Renderer
**File:** `/app/backend/server.py` - `get_preview_html()` function

- Dynamically constructs sandboxed HTML to render React apps
- Mocks 100+ Lucide icons for generated code
- Injects Supabase client configuration
- Handles React Router for SPA navigation

### Database Schema
- `projects`: Project metadata, Supabase config
- `project_versions`: Generated code for each version
- `jobs`: Async job state and progress

## What's Implemented

### ✅ Completed (Feb 7, 2026)
1. **Async Job System** - Background builds with progress tracking
2. **Requirements Parsing** - LLM-powered prompt analysis
3. **Code Generation** - Full React app with Supabase integration
4. **Live Preview** - Working preview with 100+ mocked Lucide icons
5. **SQL Migrations** - Auto-generated database schema
6. **Simple Apps (No Auth)** - E2E pipeline verified working

### 🔧 Partially Working
1. **Tester Agent** - Stub implemented, needs full logic
2. **Fix Agent** - Stub implemented, needs full logic
3. **Real-time UI Updates** - Polling works but not dynamic

### ❌ Not Yet Implemented
1. **Supabase Edge Functions** - Not being generated
2. **Authentication in Generated Apps** - Temporarily disabled
3. **Cancel Generation** - Button exists but not functional
4. **Code Syntax Highlighting** - Not implemented

## API Endpoints

### Projects
- `GET /api/projects` - List all projects
- `POST /api/projects` - Create new project
- `GET /api/projects/{id}` - Get project details
- `DELETE /api/projects/{id}` - Delete project

### Jobs
- `POST /api/projects/{id}/jobs/start` - Start build job
- `GET /api/projects/{id}/jobs/{job_id}` - Get job status
- `GET /api/projects/{id}/jobs/active` - Get active job

### Preview
- `GET /api/projects/{id}/preview/live` - Live HTML preview

## Environment Configuration

### Backend (.env)
- `OPENROUTER_API_KEY` - For LLM API calls
- `SUPABASE_URL` - Default Supabase project URL
- `SUPABASE_ANON_KEY` - Public API key
- `SUPABASE_SERVICE_KEY` - Service role key
- `MONGO_URL` - MongoDB connection string

### Frontend (.env)
- `REACT_APP_BACKEND_URL` - API base URL

## Recent Fixes (Feb 7, 2026)
1. Added retry logic to code generation (3 retries for 500 errors)
2. Added 12+ new Lucide icons (BookOpen, Book, Notebook, etc.)
3. Removed duplicate icon definitions causing Babel errors
4. Increased code generation timeout to 300 seconds
5. Added detailed logging for debugging

## Known Issues
1. **Navigation in Preview** - React Router navigation may not work in iframe
2. **Database Tables** - Must be created manually in Supabase
3. **Multiple Concurrent Jobs** - Can cause race conditions

## Backlog

### P1 - High Priority
- Fix real-time UI updates (add proper polling)
- Implement Supabase function generation
- Add database table auto-creation

### P2 - Medium Priority
- Implement full Tester Agent
- Implement full Fix Agent
- Add authentication support to generated apps

### P3 - Low Priority
- Add code syntax highlighting
- Implement cancel generation
- Add project export/download
