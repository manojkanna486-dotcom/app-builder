# 🔄 Code Update Logic - Complete Explanation

## Overview

This app has **TWO different ways** to update generated code:

1. **AI-Powered Updates** (Conversational) - User describes changes in natural language
2. **Visual Edits** (Direct Manipulation) - User clicks and edits UI elements directly in browser

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INPUT                                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Option 1: Text Prompt           Option 2: Visual Click     │
│  "Make button blue"              [Click button → Edit]      │
│         │                                 │                 │
│         ▼                                 ▼                 │
├─────────────────────────────────────────────────────────────┤
│   AI Code Generation              Visual Edit System        │
│   (/generate endpoint)            (/edit-file endpoint)     │
│         │                                 │                 │
│         ▼                                 ▼                 │
├─────────────────────────────────────────────────────────────┤
│         LLM analyzes code                AST manipulation   │
│         Generates new version            Direct file update │
│         Creates Version object           Git commit         │
│         Stores in database               Immediate effect   │
│         │                                 │                 │
│         ▼                                 ▼                 │
├─────────────────────────────────────────────────────────────┤
│              UPDATED CODE IN PROJECT                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 🤖 Method 1: AI-Powered Updates (Conversational)

### Endpoint: `/api/projects/{project_id}/generate`

### Flow

```
1. User sends prompt: "Make the button blue"
   ↓
2. Backend fetches latest version from database
   ↓
3. Backend determines if this is UPDATE or NEW generation
   ↓
4. If UPDATE: Builds context with current code
   ↓
5. Sends to LLM (Claude Sonnet 4) with special prompts
   ↓
6. LLM returns JSON with modified files
   ↓
7. Backend validates & auto-fixes code
   ↓
8. Creates new Version object (v2, v3, etc.)
   ↓
9. Saves to database
   ↓
10. Returns updated code to frontend
```

### Key Code Sections

#### Step 1: Detect if Update or New Generation

```python
# Get latest successful version
latest_version = await database.get_latest_version(project_id)

if latest_version and latest_version.get("files"):
    # UPDATE existing code
    current_code = ""
    for f in latest_version["files"]:
        current_code += f"// File: {f['path']}\n{f['content']}\n\n"
    
    # Use UPDATE prompt with context
    system_content = UPDATE_SYSTEM_PROMPT.replace(
        "{current_code}", current_code
    ).replace("{user_request}", request.prompt)
else:
    # NEW generation
    system_content = SYSTEM_PROMPT
```

#### Step 2: LLM Call with Context

```python
messages = [
    {"role": "system", "content": system_content},
    {"role": "user", "content": f"Update: {request.prompt}"}
]

# Call OpenRouter API (Claude Sonnet 4)
response = await call_openrouter(messages)
```

#### Step 3: Parse Response

The LLM returns JSON in this format:

```json
{
  "files": [
    {
      "path": "src/App.js",
      "content": "// updated code here",
      "file_type": "frontend"
    },
    {
      "path": "src/Button.js", 
      "content": "// updated button code",
      "file_type": "frontend"
    }
  ],
  "summary": "Changed button color to blue",
  "changes": ["Modified Button component styling"]
}
```

#### Step 4: Validate & Auto-Fix

```python
# Validate React code
validation_errors = validate_react_code(files)

if validation_errors:
    # Attempt auto-fix
    fixed_files, fix_summary = await auto_fix_code(
        files, validation_errors
    )
    if fixed_files:
        files = fixed_files
```

#### Step 5: Create New Version

```python
# Increment version number
new_version_number = latest_version["version_number"] + 1

# Create version object
version = Version(
    project_id=project_id,
    version_number=new_version_number,  # v2, v3, etc.
    prompt=request.prompt,
    files=[VersionFile(**f) for f in files],
    status="success",
    delta_plan={
        "summary": summary,
        "changes": result.get("changes", [])
    }
)

# Save to database
await database.create_version(version.model_dump())

# Update project's current_version pointer
await database.update_project(project_id, {
    "current_version": new_version_number
})
```

### Version History

Every update creates a **new version**:

```
Project: "My Todo App"
  ├─ Version 1: Initial generation
  ├─ Version 2: "Add delete button"
  ├─ Version 3: "Make it blue"
  └─ Version 4: "Add user authentication"
```

---

## 🎨 Method 2: Visual Edits (Direct Manipulation)

### Endpoint: `/edit-file` (Dev server middleware)

### Flow

```
1. User clicks element in browser
   ↓
2. Frontend detects click, shows edit UI
   ↓
3. User changes className/text/content
   ↓
4. Frontend sends POST /edit-file with changes
   ↓
5. Backend parses file into AST (Abstract Syntax Tree)
   ↓
6. Backend finds exact element by line number
   ↓
7. Backend modifies AST node
   ↓
8. Backend generates updated code from AST
   ↓
9. Backend writes file to disk
   ↓
10. Backend commits to Git
   ↓
11. Hot reload updates browser immediately
```

### Key Code Sections

#### Step 1: Frontend Sends Edit Request

```javascript
// Frontend sends this format
{
  changes: [
    {
      fileName: "Button",
      component: "button", 
      lineNumber: 15,
      type: "className",
      className: "bg-blue-500 text-white px-4 py-2"
    }
  ]
}
```

#### Step 2: Backend Parses File to AST

```javascript
// Parse JSX/TSX file
const ast = parser.parse(currentContent, {
  sourceType: "module",
  plugins: ["jsx", "typescript"]
});
```

#### Step 3: Find Element by Line Number

```javascript
traverse(ast, {
  JSXOpeningElement: (path) => {
    const lineNumber = path.node.loc?.start.line;
    const elementName = path.node.name.name;
    
    // Check if this is the target element
    if (lineNumber === change.lineNumber && 
        elementName === change.component) {
      // Apply the change
    }
  }
});
```

#### Step 4: Apply Change Based on Type

**Type 1: className (Tailwind CSS)**

```javascript
if (change.type === "className") {
  let classAttr = path.node.attributes.find(
    attr => attr.name.name === "className"
  );
  
  if (classAttr) {
    // Update existing
    classAttr.value = t.stringLiteral(change.className);
  } else {
    // Add new className attribute
    path.node.attributes.push(
      t.jsxAttribute(
        t.jsxIdentifier("className"),
        t.stringLiteral(change.className)
      )
    );
  }
}
```

**Type 2: textContent**

```javascript
if (change.type === "textContent") {
  const jsxElement = parentPath.node;
  let textNode = jsxElement.children.find(
    child => t.isJSXText(child)
  );
  
  if (textNode) {
    textNode.value = change.textContent;
  }
}
```

**Type 3: content (Replace entire children)**

```javascript
if (change.type === "content") {
  // Parse new JSX content
  const newChildren = parseJsxChildren(change.content);
  parentPath.node.children = newChildren;
}
```

#### Step 5: Generate Code from Modified AST

```javascript
const { code } = generate(ast, {
  retainLines: true,          // Keep line numbers
  retainFunctionParens: true, // Keep formatting
  comments: true              // Keep comments
});
```

#### Step 6: Write File & Commit

```javascript
// Write updated code
fs.writeFileSync(targetFile, code, "utf8");

// Commit to Git
const timestamp = Date.now();
execSync(`git add "${targetFile}"`);
execSync(`git commit -m "visual_edit_${timestamp}"`);
```

---

## 🔑 Key Differences

| Feature | AI Updates | Visual Edits |
|---------|-----------|--------------|
| **Input** | Natural language prompt | Direct UI click |
| **Speed** | 5-30 seconds (LLM call) | Instant (<100ms) |
| **Scope** | Can change entire app | Changes single element |
| **Precision** | May misinterpret | Exact, predictable |
| **Versioning** | Creates new version | Git commit only |
| **Database** | Stored in DB | Not stored in DB |
| **Undo** | Revert to previous version | Git revert |
| **Cost** | Uses API credits | Free |

---

## 🎯 When to Use Each Method

### Use AI Updates When:
- ✅ Making complex changes (new features)
- ✅ Refactoring multiple files
- ✅ Adding new components
- ✅ Changing business logic
- ✅ You want version history

### Use Visual Edits When:
- ✅ Changing button colors/styles
- ✅ Updating text content
- ✅ Tweaking layouts
- ✅ Quick CSS adjustments
- ✅ You want immediate feedback

---

## 📝 Update Workflow Example

### Scenario: "Make the submit button blue"

**Option 1: AI Update**

```bash
User: "Make the submit button blue"
  ↓
Backend: Fetches current Button.js code
  ↓
LLM: Analyzes code, changes className
  ↓
Backend: Validates, creates Version 2
  ↓
Database: Stores new version
  ↓
Frontend: Loads Version 2, button is blue
```

**Option 2: Visual Edit**

```bash
User: Clicks submit button → Edit panel opens
  ↓
User: Changes color to blue in UI
  ↓
Frontend: Sends /edit-file request
  ↓
Backend: Parses Button.js AST
  ↓
Backend: Updates className attribute
  ↓
Backend: Writes file, commits to Git
  ↓
Hot reload: Button turns blue immediately
```

---

## 🏗️ Technical Implementation Details

### AST (Abstract Syntax Tree) Approach

Visual edits use **Babel parser** to:

1. Parse JSX into tree structure
2. Navigate to specific node
3. Modify node properties
4. Regenerate code from tree

**Example:**

```jsx
// Original code
<button className="bg-red-500">Click</button>

// Parsed to AST
{
  type: "JSXElement",
  openingElement: {
    name: "button",
    attributes: [
      {
        name: "className",
        value: "bg-red-500"
      }
    ]
  },
  children: [
    { type: "JSXText", value: "Click" }
  ]
}

// After modification
attributes[0].value = "bg-blue-500"

// Regenerated code
<button className="bg-blue-500">Click</button>
```

### Security Features

1. **Path Traversal Protection**
   - Only allows editing files in `frontend/src`
   - Blocks `node_modules`, `public`, `.git`

2. **Authentication**
   - Requires `x-api-key` header
   - Validates against supervisor password

3. **Git Tracking**
   - Every edit is a Git commit
   - Easy to review/revert changes

---

## 🔄 State Management

### AI Updates (Database-Backed)

```
Database Tables:
  ├─ projects (project metadata)
  ├─ versions (v1, v2, v3...)
  └─ messages (chat history)

Current State = Latest Version in DB
```

### Visual Edits (File-Based)

```
File System:
  ├─ src/App.js (current state on disk)
  ├─ src/Button.js
  └─ .git/commits (history)

Current State = Files on disk
```

---

## 💡 Best Practices

1. **Use AI for major changes** → Creates clean versions
2. **Use Visual for tweaks** → Fast iteration
3. **Commit often** → Easy to revert
4. **Test after updates** → Auto-testing validates changes
5. **Review version history** → Understand evolution

---

## 🐛 Error Handling

### AI Updates

```python
try:
    # Generate code
    response = await call_openrouter(messages)
except Exception as e:
    # Save failed version
    version = Version(
        project_id=project_id,
        status="failed",
        delta_plan={"error": str(e)}
    )
    await database.create_version(version.model_dump())
```

### Visual Edits

```javascript
try {
  // Parse and modify AST
  const ast = parser.parse(content);
  // ... modifications ...
  fs.writeFileSync(targetFile, code);
} catch (err) {
  // Restore from backup
  if (fs.existsSync(backupFile)) {
    fs.copyFileSync(backupFile, targetFile);
  }
  res.status(500).json({ error: err.message });
}
```

---

## 📊 Performance

| Metric | AI Updates | Visual Edits |
|--------|-----------|--------------|
| Latency | 5-30 seconds | < 100ms |
| Throughput | 1-2 updates/min | Unlimited |
| Resource Usage | High (LLM API) | Low (local) |
| Accuracy | 85-95% | 100% |

---

## 🎓 Summary

This app uses a **hybrid approach**:

- **AI for intelligence** → Complex changes, new features
- **Visual for precision** → Exact, immediate tweaks

Both methods complement each other:
- AI handles what humans describe
- Visual handles what humans see

Together, they provide a complete code editing experience! 🚀

