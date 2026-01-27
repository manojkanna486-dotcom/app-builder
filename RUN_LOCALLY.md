# 🚀 Run App Locally - Quick Start Guide

## Prerequisites

- ✅ Python 3.8+
- ✅ Node.js 16+ and Yarn
- ✅ MongoDB or Supabase (for database)

---

## 🔧 Setup & Run

### **Step 1: Backend Setup**

```bash
# Navigate to backend
cd backend

# Create virtual environment (if not exists)
python -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Create .env file
cat > .env << 'EOF'
# Database - Choose one:
# Option 1: MongoDB
MONGO_URL=mongodb://localhost:27017
DB_NAME=ai_app_builder

# Option 2: Supabase (if using Supabase instead)
# SUPABASE_URL=your_supabase_url
# SUPABASE_KEY=your_supabase_key

# CORS
CORS_ORIGINS=http://localhost:3000

# API Keys
OPENROUTER_API_KEY=your-openai-key-here
EOF

# Edit .env and add your actual API keys
nano .env  # or use any text editor
```

### **Step 2: Start Backend**

```bash
# Make sure you're in backend directory with venv activated
cd backend
source venv/bin/activate

# Run the FastAPI server
python server.py
```

Backend will start on: **http://localhost:8001**

---

### **Step 3: Frontend Setup** (New Terminal)

```bash
# Navigate to frontend
cd frontend

# Install dependencies
yarn install

# Create .env file
cat > .env << 'EOF'
REACT_APP_BACKEND_URL=http://localhost:8001
EOF
```

### **Step 4: Start Frontend**

```bash
# Make sure you're in frontend directory
cd frontend

# Start React app
yarn start
```

Frontend will open automatically at: **http://localhost:3000**

---

## 📊 Quick Start Commands

### Start Everything (Two Terminals)

**Terminal 1 - Backend:**
```bash
cd backend && source venv/bin/activate && python server.py
```

**Terminal 2 - Frontend:**
```bash
cd frontend && yarn start
```

---

## 🧪 Verify It's Working

1. **Backend Health Check:**
   ```bash
   curl http://localhost:8001/health
   ```

2. **Frontend:** Open http://localhost:3000 in your browser

---

## 🗄️ Database Options

### Option 1: MongoDB (Local)
```bash
# Install MongoDB (macOS)
brew install mongodb-community

# Start MongoDB
brew services start mongodb-community

# Verify it's running
mongosh
```

### Option 2: Supabase (Cloud)
1. Create account at https://supabase.com
2. Create a new project
3. Get your URL and key from Settings > API
4. Add to `backend/.env`:
   ```
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_key
   ```

---

## 🔑 Environment Variables

### Backend (.env)
```bash
# Database
MONGO_URL=mongodb://localhost:27017
DB_NAME=ai_app_builder
# OR
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# CORS
CORS_ORIGINS=http://localhost:3000

# API Keys
OPENROUTER_API_KEY=your-openai-or-openrouter-key
```

### Frontend (.env)
```bash
REACT_APP_BACKEND_URL=http://localhost:8001
```

---

## 🐛 Troubleshooting

### Backend won't start
- ✓ Check if port 8001 is free: `lsof -i :8001`
- ✓ Verify Python version: `python --version` (need 3.8+)
- ✓ Check if venv is activated: `which python`
- ✓ Install dependencies: `pip install -r requirements.txt`

### Frontend won't start
- ✓ Check if port 3000 is free: `lsof -i :3000`
- ✓ Verify Node version: `node --version` (need 16+)
- ✓ Clear cache: `rm -rf node_modules yarn.lock && yarn install`
- ✓ Check .env file exists

### Database connection failed
- ✓ MongoDB: Check if running with `brew services list`
- ✓ Supabase: Verify URL and key in .env
- ✓ Check .env file is in backend directory

### CORS errors
- ✓ Verify CORS_ORIGINS in backend/.env matches frontend URL
- ✓ Clear browser cache
- ✓ Restart both backend and frontend

---

## 📝 Notes

- Backend uses **FastAPI** (async Python framework)
- Frontend uses **React 19** with **Tailwind CSS**
- Database can be **MongoDB** or **Supabase PostgreSQL**
- Backend runs on port **8001**
- Frontend runs on port **3000**

---

## 🎯 What's Next?

Once both are running:
1. Open http://localhost:3000
2. Start building your app!
3. Check backend API docs: http://localhost:8001/docs

---

## 🆘 Need Help?

- Backend API docs: http://localhost:8001/docs
- Backend health: http://localhost:8001/health
- Frontend: http://localhost:3000

Happy coding! 🚀

