# React App Builder Script

`build_react_app.py` creates a **new** React (frontend-only) app, optionally adds features from a text prompt, and runs it locally.

## Requirements

- **Python 3.10+**
- **Node.js** and **npm** (for Vite and the generated app)

No Python packages required (uses stdlib only). For AI-generated code from your prompt, set `ANTHROPIC_API_KEY`.

## Usage

```bash
# From app-builder directory
python build_react_app.py my-app
```

This will:

1. Create a new Vite + React app under `app-builder/generated-apps/my-app`
2. Install dependencies
3. Start the dev server at http://localhost:5173

### With a prompt (scaffold only)

```bash
python build_react_app.py my-app --prompt "A todo list with add and delete"
```

Without `ANTHROPIC_API_KEY`, the app shows your prompt as a placeholder. With `ANTHROPIC_API_KEY` set, the script calls Claude to generate the initial `App.jsx` from your description.

### Options

| Option | Description |
|--------|-------------|
| `name` | App name (folder under `generated-apps/`) |
| `--prompt`, `-p` | Short description of the app/features (optional) |
| `--template`, `-t` | Vite template: `react`, `react-ts`, `react-swc`, `react-swc-ts` (default: `react`) |
| `--no-run` | Only create and install; do not start the dev server |
| `--port` | Dev server port (default: 5173) |

### Examples

```bash
# Create app and run
python build_react_app.py counter-app

# Create with prompt, then run
python build_react_app.py todo-app --prompt "Todo list with add, delete, and check done"

# Create with TypeScript template, do not run
python build_react_app.py my-ts-app -t react-ts --no-run

# Run on a different port
python build_react_app.py my-app --port 3000
```

## Output

- Apps are created in **`app-builder/generated-apps/<name>/`**.
- To run an existing app later: `cd generated-apps/<name> && npm run dev`.
