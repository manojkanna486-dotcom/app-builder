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
- **Database**: MongoDB (Motor async driver)
- **LLM Provider**: OpenRouter (Claude Sonnet 4)
- **Key Files**:
  - `/app/backend/server.py` - Main API server with all endpoints

### Frontend (React)
- **Framework**: React 19 with React Router
- **Styling**: Tailwind CSS + shadcn/ui components
- **Key Files**:
  - `/app/frontend/src/pages/HomePage.jsx` - Project list page
  - `/app/frontend/src/pages/BuilderPage.jsx` - Builder with chat + preview

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

## Prioritized Backlog

### P0 (Critical) - ✅ Complete
- [x] Project creation and management
- [x] Chat interface
- [x] Code generation
- [x] Preview rendering

### P1 (Important) - Next Phase
- [ ] Streaming code generation (show code as it generates)
- [ ] Code validation/linting before preview
- [ ] Auto-fix broken code
- [ ] Multi-file project support

### P2 (Nice to Have)
- [ ] User authentication (Supabase Auth)
- [ ] Export project as ZIP
- [ ] Share projects publicly
- [ ] Custom component library
- [ ] AI-assisted debugging

## Next Tasks
1. Add streaming support for real-time code generation feedback
2. Implement code validation with TypeScript/ESLint
3. Add multi-file support with file tree navigator
4. Migrate to Supabase PostgreSQL (user provided Transaction Pooler URI)
5. Add user authentication

## Technical Notes
- Preview uses Babel standalone for JSX transformation
- Import statements are stripped from generated code (React provided globally)
- Uses sandbox with allow-scripts and allow-same-origin for iframe security
