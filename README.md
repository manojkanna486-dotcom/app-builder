# 🚀 Astra AI

**AI-Powered Full-Stack Application Builder**

Build production-ready full-stack applications using natural language. Astra AI generates React frontends with Supabase backends, complete with database schemas, API endpoints, and beautiful UI components.

---

## ✨ Features

- 🤖 **AI-Powered Generation** - Describe your app, get production code
- 🎨 **Visual Editing** - Click-and-edit interface for instant updates
- 🗄️ **Full-Stack** - React frontend + Supabase PostgreSQL backend
- 🔄 **Version Control** - Track every change with built-in versioning
- 🧪 **Auto-Testing** - Automated testing for generated code
- 📦 **One-Click Deploy** - Deploy to Vercel instantly

---

## 🏃 Quick Start

### Prerequisites

- Python 3.8+
- Node.js 16+ and Yarn
- MongoDB or Supabase account

### Installation

```bash
# Clone the repository
git clone https://github.com/manojkanna486-dotcom/app-builder.git
cd app-builder

# Backend setup
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Frontend setup
cd ../frontend
yarn install
```

### Configuration

**Backend (.env):**
```env
# Database (choose one)
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
# OR
MONGO_URL=mongodb://localhost:27017
DB_NAME=astra_ai

# AI
OPENROUTER_API_KEY=your_openrouter_api_key

# CORS
CORS_ORIGINS=http://localhost:3000
```

**Frontend (.env):**
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

### Run Locally

**Terminal 1 - Backend:**
```bash
cd backend
source venv/bin/activate
python server.py
```

**Terminal 2 - Frontend:**
```bash
cd frontend
yarn start
```

Access at: **http://localhost:3000**

---

## 📚 Documentation

- [Running Locally](./RUN_LOCALLY.md) - Complete setup guide
- [Code Update Logic](./CODE_UPDATE_LOGIC_EXPLAINED.md) - How updates work
- [LLM Context Analysis](./LLM_CONTEXT_ANALYSIS.md) - Token usage details

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Astra AI Platform                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  React Frontend  ←→  FastAPI Backend  ←→  Supabase/MongoDB  │
│       ↓                    ↓                      ↓          │
│  Visual Editor      AI Engine (Claude)      Database        │
│       ↓                    ↓                      ↓          │
│  Hot Reload         Code Generation        Version Store    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Usage

### 1. Create a New Project

```
"Build a todo app with user authentication"
```

### 2. AI Generates Full Stack

- React components with Tailwind CSS
- Supabase database schema
- API endpoints
- Edge functions

### 3. Visual Editing (Optional)

- Click any element to edit
- Change colors, text, styles instantly
- No AI needed for simple tweaks

### 4. Deploy

- One-click deploy to Vercel
- Automatic Supabase integration

---

## 🛠️ Tech Stack

**Frontend:**
- React 19
- Tailwind CSS + Shadcn UI
- React Router v7
- Axios

**Backend:**
- FastAPI (Python)
- OpenRouter (Claude Sonnet 4)
- Supabase / MongoDB
- Auto-testing agent

**Deployment:**
- Vercel (Frontend)
- Supabase (Backend)

---

## 📦 Project Structure

```
astra-ai/
├── backend/
│   ├── server.py              # FastAPI server
│   ├── database.py            # Database abstraction
│   ├── testing_agent.py       # Auto-testing
│   ├── clarification_agent.py # Requirement extraction
│   └── requirements.txt       # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HomePage.jsx   # Landing page
│   │   │   └── BuilderPage.jsx # Main builder
│   │   └── components/        # UI components
│   ├── plugins/
│   │   └── visual-edits/      # Visual editing system
│   └── package.json
└── README.md
```

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

MIT License - feel free to use this project for any purpose.

---

## 🙏 Acknowledgments

- Built with [Emergent.sh](https://emergent.sh)
- Powered by [Anthropic Claude](https://anthropic.com)
- UI components from [Shadcn UI](https://ui.shadcn.com)

---

## 🔗 Links

- **GitHub:** https://github.com/manojkanna486-dotcom/app-builder
- **Issues:** https://github.com/manojkanna486-dotcom/app-builder/issues

---

**Made with ❤️ by the Astra AI team**
