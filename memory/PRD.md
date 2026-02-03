# Multi-Agent App Builder - Product Requirements Document

## Original Problem Statement
Build a full-stack "App Builder" that generates FastAPI backends and React frontends based on user prompts. The application uses a multi-agent system to orchestrate the entire software creation process.

## Agent Architecture (Refactored Feb 3, 2026)

### 1. Orchestrator Agent (Brain)
**File:** `/app/backend/agents/orchestrator_v2.py`

**Responsibilities:**
- Owns the entire workflow
- Decides which agent runs and in what order
- Passes context between agents
- Enforces system rules and limits

**MUST DO:**
- Start build on user prompt
- Track build state (pending → generating → deploying → testing → fixing → completed)
- Stop build on cancel request
- Ensure max retry limits are respected (3 fix attempts max)

**MUST NOT:**
- Write application code
- Modify requirements directly

### 2. Requirements Agent
**File:** `/app/backend/agents/requirements_agent.py`

**Responsibilities:**
- Convert user prompt into structured `requirements.json`

**MUST DO:**
- Parse prompt into: Features, Pages, User roles, Data models, Permissions
- Generate and update requirements.json
- Validate completeness of requirements
- Flag ambiguities (never assume unclear requirements)

**MUST NOT:**
- Write frontend or backend code
- Assume unclear requirements

**Output Schema:**
```json
{
  "app_name": "string",
  "features": [{"id": "F001", "name": "...", "description": "...", "priority": "high|medium|low"}],
  "pages": [{"id": "P001", "name": "...", "route": "/...", "auth_required": true|false}],
  "user_roles": [{"id": "R001", "name": "...", "permissions": [...]}],
  "data_models": [{"id": "D001", "name": "...", "table_name": "...", "fields": [...], "rls_enabled": true}],
  "permissions": [{"model": "...", "role": "...", "actions": [...], "condition": "..."}],
  "ambiguities": [{"id": "A001", "question": "?", "options": [...]}],
  "is_complete": true|false
}
```

### 3. Dev Agent (Frontend + Supabase)
**File:** `/app/backend/agents/code_generation_agent.py`

**Responsibilities:**
- Generate and update application code

**MUST DO:**
- Generate frontend UI (React + Tailwind)
- Integrate Supabase client
- Generate database schema & migrations
- Generate RLS policies
- Create Edge Functions (only if required)
- Follow requirements exactly

**MUST NOT:**
- Change requirements
- Rewrite entire app unless instructed
- Disable security (RLS, auth)

### 4. Deployment Agent
**File:** `/app/backend/agents/deployment_agent.py`

**Responsibilities:**
- Deploy preview builds safely

**MUST DO:**
- Run database migrations via Supabase
- Deploy preview
- Ensure deployed version matches tested code

**MUST NOT:**
- Deploy untested builds
- Deploy failed builds (previous must be working)

### 5. Conversational Tester Agent
**File:** `/app/backend/agents/tester_agent.py`

**Responsibilities:**
- Test the app like a real human user

**MUST DO:**
- Read requirements.json
- Test flows conversationally ("What happens if I...")
- Test categories:
  - Auth (login, logout, signup, session persistence)
  - CRUD (create, read, update, delete)
  - Navigation (page transitions, back button)
  - Refresh behavior (state persistence)
  - Invalid inputs (empty, special chars, long text)
  - UX (error messages, loading states, feedback)
- Validate error message clarity
- Detect UX confusion

**MUST NOT:**
- Assume happy paths only
- Skip edge cases
- Write or fix code

### 6. Fix Agent
**File:** `/app/backend/agents/fix_agent.py`

**Responsibilities:**
- Fix issues reported by Tester Agent

**MUST DO:**
- Fix ONLY reported issues
- Modify minimal required code
- Preserve existing working features
- Re-run tests after fix

**MUST NOT:**
- Add new features
- Change requirements
- Over-refactor

## Workflow

```
User Prompt
    ↓
[Requirements Agent] → requirements.json
    ↓
(Ambiguities?) → Ask User → Update requirements
    ↓
[Dev Agent] → Generated Files
    ↓
[Deployment Agent] → Deploy to Supabase
    ↓
[Tester Agent] → Test Results
    ↓
(Tests Failed?) → [Fix Agent] → Loop back to Deploy (max 3 times)
    ↓
✅ Complete
```

## API Endpoints

### Job Management (Async)
- `POST /api/projects/{id}/jobs/start` - Start async build
- `GET /api/projects/{id}/jobs/{job_id}` - Get job status
- `POST /api/projects/{id}/jobs/{job_id}/cancel` - Cancel job
- `POST /api/projects/{id}/jobs/{job_id}/resume` - Resume failed job

### Requirements
- `POST /api/projects/{id}/requirements/parse` - Parse prompt to requirements
- `POST /api/projects/{id}/requirements/resolve` - Resolve ambiguities

## Database Collections

### async_jobs
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "prompt": "string",
  "status": "pending|generating|deploying|testing|fixing|completed|failed|cancelled",
  "current_step": "init|clarify|generate|deploy|test|fix|done",
  "progress": 0-100,
  "requirements": {...},
  "files": [...],
  "test_results": {...},
  "fix_attempts": 0,
  "max_fix_attempts": 3,
  "error": "string|null",
  "created_at": "ISO timestamp",
  "completed_at": "ISO timestamp"
}
```

## Testing Status

### Verified Working (Feb 3, 2026):
- ✅ User signup creates accounts in Supabase
- ✅ User login authenticates successfully  
- ✅ Session persistence across page loads
- ✅ Sign out functionality
- ✅ Preview rendering with auth forms
- ✅ Async job creation and status polling

### Known Issues:
- ⚠️ OAuth redirect URL needs manual config for mobile
- ⚠️ Code generation sometimes creates incompatible file structures between versions

## File Structure
```
/app/backend/
├── agents/
│   ├── __init__.py
│   ├── orchestrator_v2.py      # Brain - workflow control
│   ├── requirements_agent.py   # Parse prompts to requirements
│   ├── code_generation_agent.py # Generate React + Supabase code
│   ├── deployment_agent.py     # Deploy to Supabase
│   ├── tester_agent.py         # Conversational testing
│   └── fix_agent.py            # Fix only reported issues
├── job_manager.py              # Async job management
├── database.py
└── server.py
```

## 3rd Party Integrations
- **OpenRouter:** LLM-based code generation (Claude Sonnet 4)
- **Supabase:** Database, auth, and backend for generated apps
