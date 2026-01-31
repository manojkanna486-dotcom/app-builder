# App Builder - Product Requirements Document

## Original Problem Statement
Create an App Builder (v0 clone) that allows users to build React applications using natural language prompts. 

**Latest Requirement (P0):** Upgrade to generate **full-stack applications** with:
- React frontend
- Supabase Edge Functions backend (TypeScript/Deno)
- PostgreSQL database schema with migrations
- Supabase Auth integration (via OAuth)

## Architecture

### Backend (FastAPI)
- **Framework**: FastAPI with async support
- **Database**: MongoDB for App Builder data (projects, versions, messages)
- **LLM Provider**: OpenRouter (Claude Sonnet 4)
- **Key Files**:
  - `/app/backend/server.py` - Main API server with Supabase OAuth and full-stack generation
  - `/app/backend/database.py` - Database abstraction layer

### Frontend (React)
- **Framework**: React 19 with React Router
- **Styling**: Tailwind CSS + shadcn/ui components
- **Key Files**:
  - `/app/frontend/src/pages/HomePage.jsx` - Project list page
  - `/app/frontend/src/pages/BuilderPage.jsx` - Builder with Supabase OAuth flow

## Supabase OAuth Integration (Completed)

### Flow:
1. User clicks "Connect Supabase Account" 
2. Redirects to Supabase OAuth authorization page
3. User authenticates and grants permissions (projects:read, organizations:read)
4. App receives authorization code
5. Backend exchanges code for access token (with PKCE)
6. User sees project selector modal with their Supabase projects
7. User selects a project (or creates new one)
8. App fetches project credentials automatically (URL, anon_key, service_key)
9. Connection saved - shows "Supabase Connected" with project name

### Security - Strict Project Isolation:
- All operations ONLY affect the connected Supabase project
- Project ownership verified before connection
- `supabase_project_ref` stored and used for all operations
- Helper function `get_connected_supabase_project()` enforces isolation
- UI shows "All operations will only affect this project"

### API Endpoints:
- `GET /api/auth/supabase/login?project_id={id}` - Start OAuth flow
- `GET /api/auth/supabase/callback` - OAuth callback handler
- `GET /api/auth/supabase/projects?token_state={state}` - List user's projects
- `GET /api/auth/supabase/organizations?token_state={state}` - List organizations
- `POST /api/auth/supabase/projects/create?token_state={state}` - Create new project
- `POST /api/auth/supabase/connect/{ref}?token_state={state}` - Connect project
- `GET /api/projects/{id}/supabase/info` - Get connected project info
- `POST /api/projects/{id}/supabase/run-migration` - Run SQL migrations (isolated)

## Deployment Features (Completed)

### Deploy to Vercel:
- One-click deployment with access token
- Automatic environment variable injection (Supabase URL/key)
- Modal with token input and deployment status

### CodeSandbox Integration:
- Opens project in CodeSandbox for editing/sharing
- No account required
- Fully interactive sandbox

### ZIP Export:
- Download complete source code
- Includes package.json, README, deployment instructions
- Ready for Vercel/Netlify deployment

## What's Been Implemented

### Jan 27, 2026 - Automatic Migration & Deployment Execution
- ✅ Updated `run_migrations_internal()` to actually execute SQL via pg-meta API
- ✅ Migrations auto-run after code generation (shows success/pending status)
- ✅ Frontend shows real-time migration results via toast notifications
- ✅ Link to SQL Editor provided for pending migrations
- ✅ Edge Functions prepared with deployment commands
- ✅ Added stream events for migration_result and deploy_result
- ✅ Better error messages for session expiration in project creation

### Jan 27, 2026 - Lucide Icons Support in Preview
- ✅ Added 40+ mock Lucide icons to preview HTML (Plus, Minus, Check, Trash, Edit, Search, Menu, Home, User, Settings, Heart, Star, Calendar, Clock, Mail, Phone, LogIn, LogOut, Sun, Moon, Chevrons, Arrows, Loader, Calculator, Code, Download, Upload, Eye, Lock, AlertCircle, CheckCircle, Info, RotateCcw)
- ✅ Icons render correctly in generated app previews
- ✅ Verified counter app works with Calculator icon

### Jan 27, 2026 - Requirement Clarification System & Responsive Design
- ✅ Created `clarification_agent.py` with ClarificationAgent class
- ✅ LLM-powered requirement extraction from user prompts
- ✅ Automatic clarifying questions generation (color theme, auth, data, layout)
- ✅ Shows project summary, requirements list, and assumptions
- ✅ User can answer questions or skip with defaults
- ✅ Updated LLM prompts to ALWAYS generate fully responsive code:
  - Mobile-first approach (320px+)
  - Responsive breakpoints (sm, md, lg, xl)
  - Touch-friendly UI (44px+ tap targets)
  - Responsive typography and spacing
  - Mobile navigation (hamburger menu)
- ✅ Enhanced frontend UI for clarification with requirements preview

### Jan 26, 2026 - Built-in Testing Agent
- ✅ Created `testing_agent.py` module with TestingAgent class
- ✅ Automatic requirement extraction from user prompts using LLM
- ✅ Test validation for UI, Auth, Data, API, and Logic requirements
- ✅ Auto-retry loop: max 3 attempts to fix failing tests
- ✅ Test results shown in real-time during generation
- ✅ Frontend toast notifications for test status
- ✅ Test results saved with version data
- ✅ Enable/disable testing per generation request

### Jan 26, 2026 - Auto-Migration & Function Deployment Preparation
- ✅ Added `run_migrations_internal()` function to prepare SQL migrations after code generation
- ✅ Added `deploy_edge_functions_internal()` function to prepare Edge Functions for deployment
- ✅ Integrated auto-migration preparation into code generation stream
- ✅ Frontend shows toast notifications with direct link to Supabase SQL Editor
- ⚠️ Note: Supabase doesn't allow arbitrary SQL execution via API for security - migrations are prepared but need manual execution in SQL Editor

### Jan 26, 2026 - Critical Bug Fix: Invalid API Key
- ✅ **FIXED** "Invalid API key" error in generated app preview
- ✅ Root cause: `supabaseClient.js` had hardcoded stale API key that conflicted with correct credentials
- ✅ Solution: Skip `supabaseClient.js` from preview, provide global `supabase` variable with correct credentials
- ✅ Added `is_supabase_client_file()` helper function to identify Supabase client files
- ✅ Modified `generate_preview_html_multifile()` to use project's actual API key
- ✅ Both Sign Up and Sign In now working correctly in preview

### Jan 26, 2026 - Supabase OAuth & Project Isolation
- ✅ Complete OAuth flow with PKCE security
- ✅ Project selector modal (list existing / create new)
- ✅ Automatic credential fetching
- ✅ Strict project isolation enforcement
- ✅ UI shows connected project name and ref
- ✅ "All operations will only affect this project" message

### Jan 25, 2026 - Phase 1: Full-Stack Generation
- ✅ "Connect Supabase" UI (now OAuth-based)
- ✅ Full-stack LLM prompts (Edge Functions + SQL)
- ✅ File type detection (frontend/edge_function/sql)
- ✅ Deploy to Vercel button
- ✅ CodeSandbox integration
- ✅ ZIP export feature

### Previous Sessions
- MVP App Builder with frontend-only generation
- Multi-file project support
- Code validation and auto-fix
- Real-time streaming generation
- Smart clarification system

## Prioritized Backlog

### P0 (Critical) - Completed
- [x] Supabase OAuth integration
- [x] Project selector modal
- [x] Strict project isolation
- [x] Full-stack code generation prompts
- [x] Deploy to Vercel
- [x] CodeSandbox integration
- [x] Fix "Invalid API key" bug in preview

### P1 (Important) - In Progress
- [x] Prepare SQL migrations after code generation (shows link to SQL Editor)
- [x] Prepare Edge Functions for deployment (shows deployment instructions)
- [ ] Supabase Auth in generated apps (email/password, OAuth)

### P2 (Nice to Have)
- [ ] Syntax highlighting in code view
- [ ] Cancel generation button
- [ ] Share projects publicly
- [ ] Project templates

## Environment Variables

### Backend (.env)
```
MONGO_URL="mongodb://localhost:27017"
DB_NAME="test_database"
OPENROUTER_API_KEY="sk-or-v1-..."
SUPABASE_OAUTH_CLIENT_ID="995b1173-e948-42c4-93dc-3a7632968fed"
SUPABASE_OAUTH_CLIENT_SECRET="sba_..."
SUPABASE_OAUTH_REDIRECT_URI="https://react-api-maker.preview.emergentagent.com/api/auth/supabase/callback"
```

## Data Model (Project)
```json
{
  "id": "uuid",
  "name": "string",
  "description": "string",
  "supabase_connected": true,
  "supabase_url": "https://xxx.supabase.co",
  "supabase_anon_key": "eyJ...",
  "supabase_service_key": "eyJ...",
  "supabase_project_ref": "xxx",
  "supabase_project_name": "AI hub",
  "supabase_region": "ap-south-1",
  "supabase_connected_at": "2026-01-26T08:52:24.483028+00:00"
}
```

## Testing Status
- OAuth Flow: ✅ Working
- Project Selector: ✅ Working
- Project Isolation: ✅ Enforced
- Full-stack Generation: ✅ Working
- Vercel Deploy: ✅ Working
- CodeSandbox: ✅ Working
- Live Preview: ✅ Working (Fixed Jan 27, 2026)

## Bug Fixes History

### Jan 27, 2026 - Blank Preview Bug (P0 - FIXED)
**Issue:** Live preview showed blank screen for generated projects containing `.env.example` or when App.jsx contained Supabase client initialization.

**Root Causes Identified:**
1. `.env.example` files (marked as `file_type: frontend`) were being included in preview HTML, causing JS syntax errors
2. `is_supabase_client_file()` was incorrectly filtering out `App.jsx` because it contained both `createClient` and `export const supabase` patterns

**Fixes Applied to `server.py` in `generate_preview_html_multifile()`:**
1. Added filter to skip files with `.env` in path
2. Added exception for App.jsx to NOT be skipped even if it matches supabase client patterns
3. Added fallback filter with same `.env` and extension checks
4. Added double-check filter in the code generation loop

### Jan 27, 2026 - Migration Approval Flow (P0 - IMPLEMENTED)
**Feature:** User approval required before running SQL migrations

**Changes:**
- Backend (`server.py`):
  - Modified streaming generation to send `migration_approval_needed` event instead of auto-running
  - Added `POST /api/projects/{project_id}/migrations/approve` endpoint
  - Added `POST /api/projects/{project_id}/migrations/skip` endpoint
  - Migrations stored in project as `pending_migrations` until approved/skipped

- Frontend (`BuilderPage.jsx`):
  - Added `pendingMigrations` state
  - Added migration approval UI card in chat with SQL preview
  - Added "Run Migrations" and "Skip for Now" buttons
  - Added `handleApproveMigrations()` and `handleSkipMigrations()` functions

### Jan 28, 2026 - Incremental/Diff-Based Code Generation (IMPLEMENTED)
**Optimization:** Reduced LLM context usage by only sending affected files for updates

**Changes:**
- Added `INTENT_DIFF_PROMPT` - Analyzes user request to identify affected files
- Added `DIFF_UPDATE_PROMPT` and `DIFF_UPDATE_FULLSTACK_PROMPT` - Only sends affected files
- Added `analyze_affected_files()` function for Pass 1 analysis
- Added `get_files_content()` helper to extract specific file contents
- Modified `generate_code_stream()` to use two-pass approach:
  - Pass 1: Analyze which files need changes (scope detection)
  - Pass 2: Send only affected files to LLM, get back only modified files
  - Merge: Combine modified files with unchanged existing files

**Benefits:**
- Significantly reduced token usage for updates
- Faster response times
- More focused changes (less risk of unintended modifications)

### Jan 28, 2026 - OAuth Token Persistence (P1 - FIXED)
**Issue:** Supabase OAuth tokens were stored in-memory, lost on server restart

**Changes:**
- Added `oauth_tokens` collection in MongoDB for persistent storage
- Added `store_oauth_token()`, `get_oauth_token()`, `delete_oauth_token()` to database.py
- Added `get_valid_oauth_token()` helper with automatic token refresh
- Added `refresh_oauth_token()` to refresh expired tokens using refresh_token
- Updated all OAuth endpoints to use database storage instead of in-memory
- Renamed `oauth_states` → `oauth_pkce_states` (short-lived PKCE state only)

**Benefits:**
- Tokens survive server restarts
- Automatic token refresh before expiration
- More reliable Supabase project creation flow

### Jan 28, 2026 - Auto Migration & Deployment (IMPLEMENTED)
**Feature:** Automatic migration execution and Edge Function deployment after code validation

**Changes:**
- Backend (`server.py`):
  - Removed migration approval flow - migrations now auto-run after validation
  - Auto-executes SQL migrations via Supabase pg-meta API
  - Auto-deploys Edge Functions after code generation
  - Sends real-time status updates: success/partial/pending/error

- Frontend (`BuilderPage.jsx`):
  - Removed `pendingMigrations` state and approval UI
  - Removed `handleApproveMigrations()` and `handleSkipMigrations()` functions
  - Updated toast notifications for auto-migration/deployment results

**Flow:**
1. Code generation completes
2. Code validation passes
3. SQL files detected → Auto-run migrations → Report status
4. Edge Functions detected → Auto-deploy → Report status
5. Show final result with migration/deployment status

### Jan 28, 2026 - Background Async Generation (IMPLEMENTED)
**Feature:** Code generation continues even if browser is closed

**Backend Changes (`server.py`):**
- Added `GenerationTask` model with status tracking (pending/analyzing/generating/validating/migrating/deploying/completed/failed)
- Added `generation_tasks` MongoDB collection for persistence
- Added `run_background_generation()` async function that runs independently
- Added endpoints:
  - `POST /api/projects/{id}/generate/background` - Start background generation
  - `GET /api/projects/{id}/generate/status` - Poll for status
  - `GET /api/projects/{id}/generate/task/{task_id}` - Get task details
- Added `active_generation_tasks` dict for tracking running tasks

**Frontend Changes (`BuilderPage.jsx`):**
- Added `generationTaskId` and `generationProgress` state
- Replaced streaming generation with background generation + polling
- Added `pollGenerationStatus()` function (2-second intervals)
- Added `loadGenerationResults()` to fetch results after completion
- Added `useEffect` to check for active generation on page load
- Added progress bar UI with percentage and "close browser safely" message

**Flow:**
1. User sends prompt → Backend starts background task
2. Frontend polls for status every 2 seconds
3. User can close browser - generation continues
4. On return, frontend detects active/completed task and shows result

### Jan 28, 2026 - Conversation Context Memory (IMPLEMENTED)
**Feature:** App remembers all previous messages with auto-summarization

**Backend Changes (`server.py`):**
- Added `build_conversation_context()` - loads chat history with summarization
- Added `summarize_conversation()` - uses LLM to summarize old messages when context limit reached
- Added `build_context_prompt()` - formats context for system prompt
- Constants: `MAX_CONTEXT_MESSAGES = 20`, `MAX_CONTEXT_CHARS = 8000`
- Integrated context into both background and streaming generation
- Context shows in status: "📚 Loaded conversation context..."

**How it works:**
1. Loads all chat messages for the project
2. If within limits (20 messages or 8000 chars) → use all messages
3. If over limit → summarize older messages, keep last 5 recent
4. Prepends context summary + recent messages to system prompt
5. LLM now knows full conversation history

**Benefits:**
- Multi-turn development: "now add dark mode" works because it knows what was built
- Consistent decisions: remembers user preferences from earlier messages
- Better error fixes: knows what was tried before

## Pending Issues

None - all major issues resolved.

## Bug Fixes Applied This Session

### Fix 1: `validate_generated_code` → `validate_react_code`
- Background generation was calling undefined function
- Changed to use existing `validate_react_code()`

### Fix 2: OpenRouter response parsing
- `call_openrouter()` was returning raw API response
- Fixed to extract `choices[0].message.content` properly

### Fix 3: Duplicate component detection in preview
- Diff-based generation could create files that duplicate components already in App.jsx
- Added `defined_components` set to track and skip duplicate definitions
- Now properly skips duplicate Header, MobileNav, etc.

## Upcoming Tasks
1. Verify Edge Function deployment end-to-end
2. Add "Cancel Generation" button
3. Implement syntax highlighting in code viewer
4. Track migration history and rollback feature

## Backlog
- Refactor `server.py` (~3000 lines) into smaller modules
- Refactor `BuilderPage.jsx` (~1600 lines) into components