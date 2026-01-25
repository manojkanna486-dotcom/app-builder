# App Builder - Product Requirements Document

## Original Problem Statement
Create an App Builder (v0 clone) that allows users to build React applications using natural language prompts. 

**Latest Requirement (P0):** Upgrade to generate **full-stack applications** with:
- React frontend
- Supabase Edge Functions backend (TypeScript/Deno)
- PostgreSQL database schema with migrations
- Supabase Auth integration

## Architecture

### Backend (FastAPI)
- **Framework**: FastAPI with async support
- **Database**: MongoDB for App Builder data (projects, versions, messages)
- **LLM Provider**: OpenRouter (Claude Sonnet 4)
- **Key Files**:
  - `/app/backend/server.py` - Main API server with full-stack generation logic
  - `/app/backend/database.py` - Database abstraction layer

### Frontend (React)
- **Framework**: React 19 with React Router
- **Styling**: Tailwind CSS + shadcn/ui components
- **Key Files**:
  - `/app/frontend/src/pages/HomePage.jsx` - Project list page
  - `/app/frontend/src/pages/BuilderPage.jsx` - Builder with Supabase connection UI

### API Endpoints
- `GET /api/projects` - List projects
- `POST /api/projects` - Create project
- `GET /api/projects/{id}` - Get project
- `DELETE /api/projects/{id}` - Delete project
- `GET /api/projects/{id}/versions` - Get version history
- `GET /api/projects/{id}/versions/latest` - Get latest version
- `GET /api/projects/{id}/messages` - Get chat messages
- `POST /api/projects/{id}/messages` - Add message
- `POST /api/projects/{id}/generate` - Generate code via LLM
- `POST /api/projects/{id}/generate/stream` - Generate code with streaming
- `GET /api/projects/{id}/preview` - Get preview HTML
- `GET /api/projects/{id}/validate` - Validate code for errors
- `POST /api/projects/{id}/fix` - Auto-fix code errors
- `POST /api/projects/{id}/analyze` - Analyze prompt for clarification
- **NEW** `POST /api/projects/{id}/connect-supabase` - Connect Supabase project
- **NEW** `POST /api/projects/{id}/disconnect-supabase` - Disconnect Supabase
- **NEW** `GET /api/projects/{id}/supabase-status` - Get Supabase connection status

## What's Been Implemented

### Jan 25, 2026 - Phase 1: Full-Stack Supabase Integration
- **Connect Supabase UI**: Button and modal to capture Supabase URL and keys
- **Supabase Connection Endpoints**: Store credentials per project
- **Full-Stack LLM Prompts**: Generate Edge Functions + SQL migrations
- **File Type Detection**: Auto-detect `frontend`, `edge_function`, `sql` types
- **Status Banner**: Shows "Supabase Connected" with disconnect option

### Previous Sessions
- MVP App Builder with frontend-only generation
- Multi-file project support with file tree navigator
- Code validation and auto-fix
- Real-time streaming generation
- Smart clarification system for vague prompts

## Prioritized Backlog

### P0 (Critical) - In Progress
- [x] Connect Supabase UI and backend
- [x] Full-stack code generation prompts
- [x] File type distinction (frontend/edge_function/sql)
- [ ] Backend deployment to Supabase Edge Functions (research needed)
- [ ] Supabase Auth integration in generated apps

### P1 (Important)
- [ ] Execute SQL migrations on connected Supabase
- [ ] Deploy Edge Functions programmatically
- [ ] User authentication for App Builder itself

### P2 (Nice to Have)
- [ ] Export project as ZIP
- [ ] Syntax highlighting in code view
- [ ] Cancel generation button
- [ ] Share projects publicly

## Database Configuration
The App Builder uses MongoDB. Generated apps use Supabase PostgreSQL.

### Supabase Connection (for generated apps)
Users must provide:
1. **Project URL**: `https://[project-ref].supabase.co`
2. **Anon/Public Key**: Safe for frontend
3. **Service Role Key** (optional): For admin operations

## File Types in Generated Projects
- `frontend` - React/JSX components
- `edge_function` - Supabase Edge Functions (TypeScript/Deno)
- `sql` - Database migrations

## Testing Status
- Backend: 100% (21/21 tests passed)
- Frontend: 100%
- Test Report: `/app/test_reports/iteration_4.json`

## Known Limitations
- Preview iframe is blank for full-stack apps (Supabase client can't load in sandbox)
- Edge Functions must be deployed manually to Supabase (not automated yet)
- SQL migrations must be run manually via Supabase Dashboard
