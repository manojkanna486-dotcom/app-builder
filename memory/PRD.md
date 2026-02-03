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

### Async Job System
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
│   ├── job_manager.py         # Async job system
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

**Major Fixes:**
1. ✅ **Fixed Blank Preview** - Resolved duplicate icon declarations, added `auth` helper for Supabase
2. ✅ **Fixed Config File Processing** - Preview skips tailwind.config.js, vite.config.js, etc.
3. ✅ **Implemented Async Job System** - Jobs run independently, persist in MongoDB, resumable
4. ✅ **Fixed Version Merging** - Preview now merges files from ALL versions (not just latest)
5. ✅ **Fixed Version Status Filter** - Now includes both "success" and "partial" status versions

**End-to-End Test Completed:**
- Created "Social Feed App" with Supabase credentials
- Generated 21 files including Auth, Feed, Post, Profile components
- Added dark mode feature (version 2 with 7 additional files)
- Preview correctly shows merged files from both versions

## API Endpoints

### Job Management
- `POST /api/projects/{id}/jobs/start` - Start async build
- `GET /api/projects/{id}/jobs` - List all jobs
- `GET /api/projects/{id}/jobs/active` - Get active job
- `GET /api/projects/{id}/jobs/{job_id}` - Get job status
- `POST /api/projects/{id}/jobs/{job_id}/cancel` - Cancel job
- `POST /api/projects/{id}/jobs/{job_id}/resume` - Resume job

### Project Management
- `POST /api/projects` - Create project
- `POST /api/projects/{id}/connect-supabase` - Connect Supabase credentials
- `GET /api/projects/{id}/preview` - Get preview HTML (merged files)
- `GET /api/projects/{id}/preview/live` - Get live preview page
- `POST /api/projects/{id}/clarify` - Start clarification
- `GET /api/projects/{id}/versions` - Get all versions

## Database Schema

### projects
- id, name, description
- supabase_url, supabase_anon_key, supabase_service_key
- supabase_connected, current_version

### async_jobs
- id, project_id, prompt
- status, current_step, progress
- requirements, supabase_config
- files, step_results
- error, fix_attempts, max_fix_attempts
- created_at, started_at, completed_at

### versions
- id, project_id, version_number
- files, prompt, status (success/partial)
- delta_plan, created_at

## Supabase Setup

Add these redirect URLs to your Supabase project:
```
https://promptcraft-269.preview.emergentagent.com/api/auth/supabase/callback
https://promptcraft-269.preview.emergentagent.com
```

Location: Supabase Dashboard → Authentication → URL Configuration → Redirect URLs

## Test Results

### Social Feed App (E2E Test)
- **Version 1:** 21 files generated
  - Auth components (SignIn, SignUp)
  - Feed, Post, CreatePost components
  - Profile, Navbar, LoadingSpinner
  - 4 database migrations
  - Config files (package.json, vite, tailwind)

- **Version 2:** 7 files added/updated
  - ThemeToggle component
  - useTheme hook
  - Updated Navbar, App.jsx, index.css
  - User preferences migration

## Known Issues

### Resolved
- ✅ Blank preview (duplicate icons, missing auth helper)
- ✅ Config files breaking preview (now filtered)
- ✅ Incremental updates missing dependencies (now merged)
- ✅ Only "success" versions shown (now includes "partial")

### Outstanding
- ⚠️ OAuth redirect URL needs manual configuration for mobile
- ⚠️ "Skip & Use Defaults" button needs debugging

## Next Tasks

### P0 - Immediate
1. Debug "Skip & Use Defaults" button
2. Add real-time job progress in UI (WebSocket or frequent polling)

### P1 - Soon
1. Refine Deployment Agent for SQL migrations
2. Add cancel job button in UI
3. Show job history panel

### P2 - Backlog
- Syntax highlighting in code viewer
- Migration history/rollback
- Refactor monolithic BuilderPage.jsx

## 3rd Party Integrations
- **OpenRouter:** LLM-based code generation
- **Supabase:** Database, auth, and backend for generated apps
