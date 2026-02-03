# Multi-Agent App Builder - Product Requirements Document

## Original Problem Statement
Build a full-stack "App Builder" that generates FastAPI backends and React frontends based on user prompts. The application uses a multi-agent system to orchestrate the entire software creation process.

## Core Requirements

### Mandatory Integration: Supabase
- All generated apps use Supabase (PostgreSQL) for database and auth
- A project cannot be started until a user connects their Supabase account
- System handles automated database migrations via Service Role Key

### Multi-Agent Generation Pipeline
1. **Clarification Agent:** Analyzes prompts, extracts requirements, asks clarifying questions
2. **Code Generation Agent:** Writes React and FastAPI code based on finalized requirements
3. **Deployment Agent:** Deploys the application, runs database migrations
4. **Testing Agent:** Runs automated tests to validate requirements
5. **Dev Agent:** Fixes code if tests fail (max 3 retries)

### Async Job System (NEW - Feb 2026)
Jobs run independently of browser sessions:
1. Run independently of any browser/UI session
2. Continue execution until completed or canceled
3. Persist progress after every step
4. Resumable after failure or restart

## Architecture

```
/app/
├── backend/
│   ├── .env
│   ├── agents/
│   │   ├── clarification_agent.py
│   │   ├── code_generation_agent.py
│   │   ├── deployment_agent.py
│   │   ├── dev_agent.py
│   │   ├── orchestrator.py
│   │   └── testing_agent.py
│   ├── job_manager.py         # NEW: Async job system
│   ├── database.py
│   ├── server.py
│   └── requirements.txt
└── frontend/
    └── src/
        ├── pages/
        │   └── BuilderPage.jsx
        └── ...
```

## What's Been Implemented

### Session: Feb 3, 2026
- **Fixed Blank Preview (P1):** Resolved duplicate icon declarations and missing `auth` helper in preview HTML
- **Fixed Config File Processing:** Preview now skips tailwind.config.js, vite.config.js, etc.
- **Implemented Async Job System:**
  - `/api/projects/{id}/jobs/start` - Start a background build job
  - `/api/projects/{id}/jobs/{job_id}` - Get job status
  - `/api/projects/{id}/jobs/active` - Check for active jobs
  - `/api/projects/{id}/jobs/{job_id}/cancel` - Cancel a job
  - `/api/projects/{id}/jobs/{job_id}/resume` - Resume a failed job
- **Job persistence:** Jobs stored in MongoDB, resumable on server restart
- **Frontend polling:** UI polls for job status updates

### Previous Sessions
- Multi-agent orchestrator architecture
- Supabase OAuth connection flow
- Clarification UI for user questions
- SSE streaming for real-time updates

## Known Issues

### P0 - Critical
- OAuth redirect URL not configured for mobile devices (user config issue)

### P1 - High  
- FIXED: Preview was blank (duplicate icons + missing auth helper)

### P2 - Medium
- "Skip & Use Defaults" button needs debugging
- Incremental updates may miss component dependencies (e.g., AuthForm)

## API Endpoints

### Job Management
- `POST /api/projects/{id}/jobs/start` - Start async build
- `GET /api/projects/{id}/jobs` - List all jobs
- `GET /api/projects/{id}/jobs/active` - Get active job
- `GET /api/projects/{id}/jobs/{job_id}` - Get job status
- `POST /api/projects/{id}/jobs/{job_id}/cancel` - Cancel job
- `POST /api/projects/{id}/jobs/{job_id}/resume` - Resume job

### Existing
- `POST /api/projects` - Create project
- `GET /api/projects/{id}/preview` - Get preview HTML
- `POST /api/projects/{id}/clarify` - Start clarification
- `POST /api/projects/{id}/build` - Legacy build (SSE streaming)

## Database Schema

### projects
- id, name, description
- supabase_url, supabase_anon_key, supabase_service_key
- supabase_connected, current_version
- requirements (from clarification agent)

### async_jobs (NEW)
- id, project_id, prompt
- status, current_step, progress
- requirements, supabase_config
- files, step_results
- error, fix_attempts, max_fix_attempts
- created_at, started_at, completed_at

## Next Tasks

### P0 - Immediate
1. Ensure incremental updates include all dependencies
2. Test complete E2E flow: prompt → clarification → generation → preview

### P1 - Soon
1. Refine Deployment Agent for SQL migrations
2. Debug "Skip & Use Defaults" button
3. Verify Dev Agent fix loop

### P2 - Backlog
- Cancel generation button
- Syntax highlighting in code viewer
- Migration history/rollback
- Refactor monolithic BuilderPage.jsx

## 3rd Party Integrations
- **OpenRouter:** LLM-based code generation
- **Supabase:** Database, auth, and backend for generated apps
