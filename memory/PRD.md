# App Builder - Product Requirements Document

## Original Problem Statement
Create an App Builder App (v0 clone) that allows users to build React applications using natural language prompts. Features include:
- Project management with list and creation
- Split-view interface (25% chat, 75% preview)
- Real-time code generation via LLM
- Live preview in sandboxed iframe
- Version management and history
- Modern minimalist dark theme

## Architecture

### Backend (FastAPI)
- **Framework**: FastAPI with async support
- **Database**: MongoDB (default) or Supabase PostgreSQL (configurable via DB_TYPE)
- **LLM Provider**: OpenRouter (Claude Sonnet 4)
- **Key Files**:
  - `/app/backend/server.py` - Main API server
  - `/app/backend/database.py` - Database abstraction layer

### Frontend (React)
- **Framework**: React 19 with React Router
- **Styling**: Tailwind CSS + shadcn/ui components
- **Key Files**:
  - `/app/frontend/src/pages/HomePage.jsx` - Project list page
  - `/app/frontend/src/pages/BuilderPage.jsx` - Builder with chat + preview + file tree

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
- `GET /api/projects/{id}/preview` - Get preview HTML
- `GET /api/projects/{id}/validate` - Validate code for errors
- `POST /api/projects/{id}/fix` - Auto-fix code errors

## User Personas
1. **Non-technical Users**: Build apps via natural language
2. **Developers**: Rapid prototyping and iteration
3. **Designers**: Quick UI mockup generation

## Core Requirements (Static)
- [x] Project CRUD operations
- [x] Chat-based prompt interface
- [x] LLM code generation (OpenRouter)
- [x] Real-time iframe preview
- [x] Version tracking
- [x] Code view/export

## What's Been Implemented
- **Jan 24, 2026**: MVP Complete
  - Full project management UI
  - OpenRouter integration for code generation
  - Sandboxed iframe preview with React/Tailwind
  - Version history with success/failed states
  - Modern dark theme UI
  - Chat interface with message history

- **Jan 24, 2026**: Feature Updates
  - **Multi-file project support**: Generate apps with multiple component files
  - **File tree navigator**: Browse files in Code view sidebar
  - **Code validation**: Detect syntax errors, unmatched brackets, missing components
  - **Auto-fix**: LLM-powered automatic code repair
  - **Database abstraction**: Supports MongoDB (default) and Supabase PostgreSQL

## Prioritized Backlog

### P0 (Critical) - ✅ Complete
- [x] Project creation and management
- [x] Chat interface
- [x] Code generation
- [x] Preview rendering
- [x] Multi-file support
- [x] Code validation

### P1 (Important) - Next Phase
- [ ] Streaming code generation (show code as it generates)
- [ ] User authentication (Supabase Auth)
- [ ] Project templates

### P2 (Nice to Have)
- [ ] Export project as ZIP
- [ ] Share projects publicly
- [ ] Custom component library
- [ ] AI-assisted debugging

## Database Configuration
To switch to Supabase PostgreSQL:
1. Get Transaction Pooler URI from Supabase Dashboard -> Connect -> Transaction Pooler
2. Set in `/app/backend/.env`:
   ```
   DB_TYPE="supabase"
   SUPABASE_DB_URL="postgresql://postgres.[REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres"
   ```
3. Restart backend

## Next Tasks
1. Get Supabase Transaction Pooler URI to enable PostgreSQL
2. Add streaming support for real-time code generation feedback
3. Implement user authentication

