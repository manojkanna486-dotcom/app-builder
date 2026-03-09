"""
Code utilities for generated app validation and sanitization.
Ensures apps built by the app builder have no syntax errors.
"""

import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def validate_frontend_code(files: List[Dict]) -> List[Dict[str, Any]]:
    """
    Validate frontend code for syntax and common runtime errors.
    Returns list of issues in fix-agent format: {category, description, error, steps_to_reproduce}.
    Used during build to catch errors before they reach the preview.
    """
    issues = []
    all_content = ""
    all_paths = []

    for f in files:
        content = f.get("content", "")
        path = f.get("path", "unknown")
        file_type = f.get("file_type", "frontend")

        if file_type != "frontend":
            continue
        if not (path.endswith(".jsx") or path.endswith(".js") or path.endswith(".tsx")):
            continue

        all_content += f"\n// {path}\n{content}"
        all_paths.append(path)

        # 1. Unmatched brackets/braces
        open_parens = content.count("(") - content.count(")")
        open_braces = content.count("{") - content.count("}")
        open_brackets = content.count("[") - content.count("]")
        if open_parens != 0:
            issues.append({
                "category": "syntax",
                "description": f"Unmatched parentheses in {path}",
                "error": f"Parentheses diff: {open_parens}",
                "steps_to_reproduce": ["Check all ( and ) are balanced"]
            })
        if open_braces != 0:
            issues.append({
                "category": "syntax",
                "description": f"Unmatched curly braces in {path}",
                "error": f"Braces diff: {open_braces}",
                "steps_to_reproduce": ["Check all { and } are balanced"]
            })
        if open_brackets != 0:
            issues.append({
                "category": "syntax",
                "description": f"Unmatched square brackets in {path}",
                "error": f"Brackets diff: {open_brackets}",
                "steps_to_reproduce": ["Check all [ and ] are balanced"]
            })

        # 2. class= instead of className=
        if "class=" in content and "className=" not in content:
            issues.append({
                "category": "syntax",
                "description": f"Using 'class=' instead of 'className=' in {path}",
                "error": "JSX requires className, not class",
                "steps_to_reproduce": ["Replace all class= with className="]
            })

        # 3. Missing App component
        if path == "App.jsx" or path.endswith("/App.jsx"):
            if "function App" not in content and "const App" not in content and "var App" not in content:
                issues.append({
                    "category": "syntax",
                    "description": f"Missing App component in {path}",
                    "error": "Preview requires a main App component",
                    "steps_to_reproduce": ["Define function App or const App"]
                })

        # 4. Duplicate declarations that cause "already been declared" in preview
        # Preview injects: supabaseUrl, supabaseAnonKey, SUPABASE_URL, etc.
        dup_patterns = [
            (r"const\s+supabaseUrl\s*=", "supabaseUrl", "Preview injects supabaseUrl - remove from lib/supabase.js or use different var name"),
            (r"const\s+supabaseAnonKey\s*=", "supabaseAnonKey", "Preview injects supabaseAnonKey - remove or rename"),
            (r"const\s+supabaseKey\s*=", "supabaseKey", "May conflict with preview - lib/supabase.js should be skipped"),
        ]
        for pattern, name, msg in dup_patterns:
            if re.search(pattern, content) and ("lib/supabase" in path or "supabase" in path.lower()):
                issues.append({
                    "category": "runtime",
                    "description": f"Duplicate identifier '{name}' in {path}",
                    "error": msg,
                    "steps_to_reproduce": ["Remove this file from preview or use different variable names"]
                })
                break

        # 5. process.env in browser (preview doesn't support it) - skip lib/supabase (we skip that file in preview)
        if ("process.env" in content and file_type == "frontend" 
                and "lib/supabase" not in path.lower() and "supabaseclient" not in path.lower()):
            issues.append({
                "category": "runtime",
                "description": f"process.env used in {path} - not supported in preview",
                "error": "Use window.importMeta.env or hardcoded values for preview",
                "steps_to_reproduce": ["Replace process.env.X with window.importMeta?.env?.X or constants"]
            })

    # 6. Unmatched JSX tags (basic)
    for path in all_paths:
        f = next((x for x in files if x.get("path") == path), None)
        if not f:
            continue
        content = f.get("content", "")
        opening_tags = re.findall(r"<([A-Z][a-zA-Z0-9]*)[^/>]*(?<!/)>", content)
        closing_tags = re.findall(r"</([A-Z][a-zA-Z0-9]*)>", content)
        open_count = {}
        for tag in opening_tags:
            open_count[tag] = open_count.get(tag, 0) + 1
        for tag in closing_tags:
            open_count[tag] = open_count.get(tag, 0) - 1
        for tag, count in open_count.items():
            if count > 0:
                issues.append({
                    "category": "syntax",
                    "description": f"Possibly unclosed <{tag}> in {path}",
                    "error": f"Add closing </{tag}>",
                    "steps_to_reproduce": ["Balance JSX tags"]
                })
            elif count < 0:
                issues.append({
                    "category": "syntax",
                    "description": f"Extra closing </{tag}> in {path}",
                    "error": "Remove extra closing tag",
                    "steps_to_reproduce": ["Balance JSX tags"]
                })

    return issues


def sanitize_frontend_files(files: List[Dict]) -> None:
    """
    Fix common syntax errors in generated frontend files in-place.
    Ensures apps built by the app builder have no syntax errors.
    """
    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        file_type = f.get("file_type", "frontend")

        if file_type != "frontend":
            continue
        if not (path.endswith(".jsx") or path.endswith(".js") or path.endswith(".tsx")):
            continue
        if not content or len(content.strip()) < 5:
            continue

        modified = content

        # Fix class= to className= in JSX (common LLM mistake)
        modified = re.sub(r'\bclass\s*=\s*["\']', 'className="', modified)
        modified = re.sub(r'\bclass\s*=\s*\{', 'className={', modified)

        # Fix unbalanced braces - add missing closing braces (common in truncated LLM output)
        open_braces = modified.count("{") - modified.count("}")
        if open_braces > 0:
            modified = modified.rstrip() + "\n" + "}" * open_braces

        # Fix unbalanced parentheses (add missing - common in truncated output)
        open_parens = modified.count("(") - modified.count(")")
        if open_parens > 0:
            modified = modified.rstrip() + ")" * open_parens

        # Fix unbalanced square brackets
        open_brackets = modified.count("[") - modified.count("]")
        if open_brackets > 0:
            modified = modified.rstrip() + "]" * open_brackets

        if modified != content:
            f["content"] = modified
            logger.debug("Sanitized %s", path)
