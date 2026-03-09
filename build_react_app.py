#!/usr/bin/env python3
"""
Build a new React (frontend-only) app from a prompt and run it locally.

Usage:
  python build_react_app.py my-app
  python build_react_app.py my-app --prompt "A todo list with add and delete"
  python build_react_app.py my-app --prompt "Counter with + and - buttons" --no-run
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Directory where new apps are created (inside app-builder)
APPS_DIR = Path(__file__).resolve().parent / "generated-apps"
DEFAULT_APP_TEMPLATE = '''export default function App() {
  return (
    <div style={{ padding: "2rem", fontFamily: "system-ui" }}>
      <h1>React App</h1>
      <p>Edit <code>src/App.jsx</code> and save to reload.</p>
    </div>
  );
}
'''


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a command; raise on failure."""
    merged = {**os.environ} if env is None else {**os.environ, **env}
    return subprocess.run(
        cmd,
        cwd=cwd or Path.cwd(),
        env=merged,
        check=True,
        text=True,
    )


def create_react_app(name: str, template: str = "react") -> Path:
    """Scaffold a new Vite React app. Returns path to the app."""
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    app_path = APPS_DIR / name
    if app_path.exists():
        raise SystemExit(f"App already exists: {app_path}. Choose another name or remove it.")

    # npm create vite@latest <name> -- --template react
    run(
        ["npm", "create", "vite@latest", name, "--", "--template", template],
        cwd=APPS_DIR,
    )
    return app_path


def install_deps(app_path: Path) -> None:
    """Install npm dependencies."""
    run(["npm", "install"], cwd=app_path)


def apply_prompt_to_app(app_path: Path, prompt: str) -> None:
    """
    Update the app based on the prompt.
    If ANTHROPIC_API_KEY is set, use Claude to generate App.jsx. Otherwise use a placeholder.
    """
    app_jsx = app_path / "src" / "App.jsx"
    if not app_jsx.exists():
        app_jsx = app_path / "src" / "App.tsx"
    if not app_jsx.exists():
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key and prompt:
        code = generate_react_with_anthropic(prompt, api_key)
        if code:
            write_app_component(app_jsx, code)
            return

    # No API or no code: write a prompt-based placeholder
    if prompt:
        # Use {{ and }} so the f-string emits single braces in the JSX style={{ }}
        placeholder = (
            "export default function App() {\n"
            "  return (\n"
            '    <div style={{ padding: "2rem", fontFamily: "system-ui", maxWidth: "40rem" }}>\n'
            "      <h1>React App</h1>\n"
            f"      <p><strong>Requested:</strong> {prompt!r}</p>\n"
            "      <p>Set <code>ANTHROPIC_API_KEY</code> and pass <code>--prompt</code> to generate code from your description.</p>\n"
            "    </div>\n"
            "  );\n"
            "}\n"
        )
        write_app_component(app_jsx, placeholder)
    else:
        write_app_component(app_jsx, DEFAULT_APP_TEMPLATE)


def write_app_component(app_jsx: Path, body: str) -> None:
    """Write App.jsx/App.tsx with a single default export component."""
    is_ts = app_jsx.suffix == ".tsx"
    react_import = "import React from 'react';\n\n" if not is_ts else ""
    # Ensure we have a proper component (default export)
    if "export default" not in body:
        body = f"export default function App() {{\n  return (\n    <div>{body.strip()}</div>\n  );\n}}\n"
    content = react_import + body.strip() + "\n"
    app_jsx.write_text(content, encoding="utf-8")


def generate_react_with_anthropic(prompt: str, api_key: str) -> str | None:
    """Call Anthropic Messages API to generate a simple React App component. Returns JSX body or None."""
    try:
        import urllib.request
        import json

        url = "https://api.anthropic.com/v1/messages"
        body = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": f"""Generate a single React component for the main App. Requirements: {prompt}

Rules:
- Return ONLY the code for one default-exported function component (no file path, no markdown fences).
- Use only React and standard HTML/CSS (inline styles or a single <style> tag). No extra dependencies.
- Use .jsx style (function App() {{ ... return (...) }}).
- No imports at the top (we will add them if needed).""",
                }
            ],
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.load(resp)
        for block in out.get("content", []):
            if block.get("type") == "text":
                text = block.get("text", "").strip()
                # Strip markdown code block if present
                if text.startswith("```"):
                    lines = text.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    text = "\n".join(lines)
                return text
        return None
    except Exception as e:
        print(f"Warning: Could not generate code from prompt ({e}). Using placeholder.", file=sys.stderr)
        return None


def run_dev_server(app_path: Path, port: int = 5173) -> subprocess.Popen | None:
    """Start Vite dev server in the background. Returns the process handle."""
    env = {**os.environ, "BROWSER": "none"}  # avoid auto-open if running from script
    try:
        proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=app_path,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return proc
    except Exception as e:
        print(f"Failed to start dev server: {e}", file=sys.stderr)
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a new React (frontend) app, optionally add features from a prompt, and run it locally."
    )
    parser.add_argument("name", help="App name (e.g. my-app)")
    parser.add_argument(
        "--prompt",
        "-p",
        default="",
        help="Describe the app or features; used to generate initial UI (requires ANTHROPIC_API_KEY for AI generation).",
    )
    parser.add_argument(
        "--template",
        "-t",
        default="react",
        choices=["react", "react-ts", "react-swc", "react-swc-ts"],
        help="Vite template (default: react).",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Do not start the dev server after building.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5173,
        help="Port for dev server (default: 5173).",
    )
    args = parser.parse_args()

    app_path = create_react_app(args.name, template=args.template)
    print(f"Created app at {app_path}")
    install_deps(app_path)
    print("Dependencies installed.")
    apply_prompt_to_app(app_path, args.prompt.strip())
    if args.prompt:
        print("Applied prompt to app.")

    if args.no_run:
        print(f"Done. To run: cd {app_path} && npm run dev")
        return

    proc = run_dev_server(app_path, port=args.port)
    if proc:
        print(f"Dev server starting at http://localhost:{args.port}")
        print("Press Ctrl+C to stop.")
        try:
            for line in proc.stdout:
                print(line, end="")
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    main()
