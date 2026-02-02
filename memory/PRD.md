# App Builder - Product Requirements Document

## Original Problem Statement
Build a multi-agent web app builder similar to Emergent. The system should:
- Generate full-stack React + Supabase applications from user prompts
- Require Supabase connection before allowing app creation
- Create and run SQL migrations automatically
- Deploy Edge Functions to Supabase
- Test generated apps against requirements
- Fix issues automatically (max 3 retries)
- Store requirements and validate against them

## Tech Stack (Fixed)
- **Frontend**: React with Tailwind CSS, Lucide React icons
- **Backend**: Supabase (PostgreSQL + Edge Functions + Auth)
- **No mock data** - All data comes from Supabase

## Multi-Agent Architecture

### Agent 1: Clarification Agent (`/app/backend/agents/clarification_agent.py`)
- Analyzes user prompts
- Extracts structured requirements
- Identifies database schema needs
- Asks minimal clarifying questions (1-2 only)
- Stores requirements in project for validation

### Agent 2: Code Generation Agent (`/app/backend/agents/code_generation_agent.py`)
- Generates React frontend components
- Creates SQL migrations with RLS policies
- Generates Edge Functions (TypeScript/Deno)
- Creates Supabase client configuration
- Supports streaming for real-time UI updates

### Agent 3: Deployment Agent (`/app/backend/agents/deployment_agent.py`)
- Executes SQL migrations via Supabase Management API
- Deploys Edge Functions to Supabase
- Verifies deployment success
- Handles partial deployments

### Agent 4: Testing Agent (`/app/backend/agents/testing_agent.py`)
- Deep testing against stored requirements
- Syntax validation (JSX, SQL, TypeScript)
- Category-specific testing (data, auth, UI)
- LLM-powered feature verification
- Generates fix reports

### Agent 5: Dev Agent (`/app/backend/agents/dev_agent.py`)
- Fixes issues identified by Testing Agent
- Max 3 retry attempts
- Returns fixed files
- Supports streaming for real-time updates

### Agent Orchestrator (`/app/backend/agents/orchestrator.py`)
- Coordinates the pipeline: Clarify → Generate → Deploy → Test → Fix
- Manages retry loops
- Yields status updates for UI
- Handles errors gracefully

## Pipeline Flow
```
User Prompt
    ↓
[Supabase Check] → If not connected, show error
    ↓
[Clarification Agent] → Extract requirements, ask questions if needed
    ↓
[Code Generation Agent] → Generate React + Supabase code (streaming)
    ↓
[Deployment Agent] → Run migrations, deploy Edge Functions
    ↓
[Testing Agent] → Deep test against requirements
    ↓
If tests fail:
    [Dev Agent] → Fix issues (max 3 retries)
    → Loop back to Deploy
    ↓
[Complete] → Save version, update preview
```

## API Endpoints

### Clarification
- `POST /api/projects/{id}/clarify` - Analyze prompt, extract requirements
- `POST /api/projects/{id}/confirm-requirements` - Confirm with user answers

### Build Pipeline
- `POST /api/projects/{id}/build` - Run complete multi-agent pipeline (streaming)

### Legacy (still available)
- `POST /api/projects/{id}/generate/stream` - Legacy generation endpoint

## Database Schema Updates

### Project Model
- Added `requirements: Dict` - Stores extracted requirements
- Added `requirements_confirmed: bool` - Whether requirements are confirmed

## Implementation Status

### ✅ Completed (Feb 2, 2026)
1. Created multi-agent system architecture
2. Implemented all 5 agents + orchestrator
3. Added Supabase connection requirement
4. Updated frontend to enforce Supabase connection
5. Created /build endpoint with streaming pipeline
6. Requirements storage and validation

### 🔧 To Test
1. Full pipeline with Supabase OAuth connection
2. Migration execution on real Supabase project
3. Edge Function deployment
4. Fix loop (3 retries)

## File References
- `/app/backend/agents/` - All agent implementations
- `/app/backend/server.py` - Main API server
- `/app/frontend/src/pages/BuilderPage.jsx` - Main UI component

## User Flow
1. User creates new project
2. System prompts to connect Supabase (REQUIRED)
3. User connects via OAuth or manual credentials
4. User enters prompt describing what to build
5. Clarification Agent analyzes and asks questions (if needed)
6. User confirms requirements
7. Code Generation creates files (streaming to UI)
8. Deployment runs migrations and deploys functions
9. Testing validates against requirements
10. If issues: Dev Agent fixes (up to 3x)
11. Version saved, preview updated
