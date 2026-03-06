"""
Memory System for AI App Builder

Provides persistent memory so the builder learns from:
- Past builds (what was asked, what was generated, what worked)
- Error patterns and their fixes
- Component / architecture patterns that produced good results

Architecture:
  MemoryStore  <-> MongoDB (via database layer)
  MemoryContext    composed and injected into agent prompts
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# Core data classes
# ──────────────────────────────────────────────────────────

class BuildMemory:
    """A record of one completed (or failed) build."""

    def __init__(
        self,
        project_id: str,
        prompt: str,
        app_type: str,
        features: List[str],
        files_generated: List[str],
        test_score: float,       # 0.0 – 1.0  (passed / total)
        fix_attempts: int,
        outcome: str,            # "success" | "partial" | "failed"
        patterns_used: Optional[List[str]] = None,
        lessons: Optional[str] = None,
        timestamp: Optional[str] = None,
    ):
        self.project_id = project_id
        self.prompt = prompt
        self.app_type = app_type
        self.features = features or []
        self.files_generated = files_generated or []
        self.test_score = test_score
        self.fix_attempts = fix_attempts
        self.outcome = outcome
        self.patterns_used = patterns_used or []
        self.lessons = lessons or ""
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "project_id": self.project_id,
            "prompt": self.prompt,
            "app_type": self.app_type,
            "features": self.features,
            "files_generated": self.files_generated,
            "test_score": self.test_score,
            "fix_attempts": self.fix_attempts,
            "outcome": self.outcome,
            "patterns_used": self.patterns_used,
            "lessons": self.lessons,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "BuildMemory":
        return cls(
            project_id=d.get("project_id", ""),
            prompt=d.get("prompt", ""),
            app_type=d.get("app_type", "unknown"),
            features=d.get("features", []),
            files_generated=d.get("files_generated", []),
            test_score=d.get("test_score", 0.0),
            fix_attempts=d.get("fix_attempts", 0),
            outcome=d.get("outcome", "unknown"),
            patterns_used=d.get("patterns_used", []),
            lessons=d.get("lessons", ""),
            timestamp=d.get("timestamp"),
        )


class LearnedPattern:
    """A reusable insight learned from builds."""

    def __init__(
        self,
        pattern_type: str,           # "architecture" | "error_fix" | "ui" | "preference"
        title: str,
        description: str,
        context_keywords: List[str],  # when to apply this pattern
        solution: str,
        confidence: float = 0.5,      # 0.0–1.0, grows with usage
        usage_count: int = 0,
        timestamp: Optional[str] = None,
    ):
        self.pattern_type = pattern_type
        self.title = title
        self.description = description
        self.context_keywords = context_keywords or []
        self.solution = solution
        self.confidence = confidence
        self.usage_count = usage_count
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "pattern_type": self.pattern_type,
            "title": self.title,
            "description": self.description,
            "context_keywords": self.context_keywords,
            "solution": self.solution,
            "confidence": self.confidence,
            "usage_count": self.usage_count,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "LearnedPattern":
        return cls(
            pattern_type=d.get("pattern_type", "general"),
            title=d.get("title", ""),
            description=d.get("description", ""),
            context_keywords=d.get("context_keywords", []),
            solution=d.get("solution", ""),
            confidence=d.get("confidence", 0.5),
            usage_count=d.get("usage_count", 0),
            timestamp=d.get("timestamp"),
        )


class MemoryContext:
    """
    Assembled context injected into agent prompts.
    Call format_for_prompt() to get a ready-to-use string.
    """

    def __init__(
        self,
        similar_builds: Optional[List[BuildMemory]] = None,
        relevant_patterns: Optional[List[LearnedPattern]] = None,
        project_history: Optional[List[Dict]] = None,
    ):
        self.similar_builds = similar_builds or []
        self.relevant_patterns = relevant_patterns or []
        self.project_history = project_history or []

    def format_for_prompt(self) -> str:
        parts: List[str] = []

        if self.similar_builds:
            parts.append("=" * 60)
            parts.append("MEMORY: RELEVANT PAST BUILDS")
            parts.append("=" * 60)
            for b in self.similar_builds[:3]:
                score_pct = int(b.test_score * 100)
                prompt_preview = b.prompt[:80] + ("..." if len(b.prompt) > 80 else "")
                parts.append(f'\n  Build: "{prompt_preview}"')
                parts.append(
                    f"  Outcome: {b.outcome}  |  Test score: {score_pct}%"
                    f"  |  Fix attempts: {b.fix_attempts}"
                )
                if b.features:
                    parts.append(f"  Features: {', '.join(b.features[:6])}")
                if b.lessons:
                    parts.append(f"  Lesson: {b.lessons}")
            parts.append("")

        if self.relevant_patterns:
            parts.append("=" * 60)
            parts.append("MEMORY: LEARNED PATTERNS & BEST PRACTICES")
            parts.append("=" * 60)
            for p in self.relevant_patterns[:5]:
                conf_pct = int(p.confidence * 100)
                parts.append(
                    f"\n  [{p.pattern_type.upper()}] {p.title}  (confidence: {conf_pct}%)"
                )
                parts.append(f"  {p.description}")
                parts.append(f"  -> Apply: {p.solution}")
            parts.append("")

        if self.project_history:
            parts.append("=" * 60)
            parts.append("MEMORY: THIS PROJECT'S HISTORY")
            parts.append("=" * 60)
            for entry in self.project_history[-5:]:
                ts = entry.get("timestamp", "")[:19].replace("T", " ")
                parts.append(
                    f"  [{ts}] {entry.get('event', '')} — {entry.get('detail', '')}"
                )
            parts.append("")

        return "\n".join(parts)

    def is_empty(self) -> bool:
        return (
            not self.similar_builds
            and not self.relevant_patterns
            and not self.project_history
        )


# ──────────────────────────────────────────────────────────
# Main MemoryStore
# ──────────────────────────────────────────────────────────

class MemoryStore:
    """
    Persistent memory backed by MongoDB (or in-memory fallback).

    Usage:
        store = MemoryStore(database)
        await store.save_build(...)
        ctx = await store.get_context_for_prompt("todo app with auth")
    """

    def __init__(self, database=None):
        self.database = database
        # In-memory fallback when DB is not available
        self._builds: List[Dict] = []
        self._patterns: List[Dict] = []
        self._project_events: Dict[str, List[Dict]] = {}
        self._use_db = database is not None

    # ── Builds ──────────────────────────────────────────────

    async def save_build(self, build: BuildMemory) -> bool:
        """Persist a build record."""
        data = build.to_dict()
        data["type"] = "build"
        try:
            if self._use_db and hasattr(self.database, "save_memory_entry"):
                await self.database.save_memory_entry(data)
            else:
                self._builds.append(data)
            logger.info(
                f"Memory: saved build for project {build.project_id}"
                f" (outcome={build.outcome})"
            )
            return True
        except Exception as e:
            logger.warning(f"Memory: could not save build: {e}")
            self._builds.append(data)
            return False

    async def get_similar_builds(
        self, prompt: str, limit: int = 5
    ) -> List[BuildMemory]:
        """Find past builds that are semantically similar to the given prompt."""
        try:
            if self._use_db and hasattr(self.database, "get_memory_entries"):
                all_builds = await self.database.get_memory_entries("build", limit=50)
            else:
                all_builds = self._builds
        except Exception as e:
            logger.warning(f"Memory: could not load builds: {e}")
            all_builds = self._builds

        if not all_builds:
            return []

        prompt_words = set(_tokenize(prompt))
        scored: List[tuple] = []
        for b in all_builds:
            build_words = set(_tokenize(b.get("prompt", "")))
            if not build_words:
                continue
            overlap = len(prompt_words & build_words)
            total = len(prompt_words | build_words)
            score = overlap / total if total else 0
            if b.get("outcome") == "success":
                score *= 1.2
            if score > 0.15:
                scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [BuildMemory.from_dict(b) for _, b in scored[:limit]]

    # ── Patterns ────────────────────────────────────────────

    async def save_pattern(self, pattern: LearnedPattern) -> bool:
        """Save a learned pattern (upsert by title)."""
        data = pattern.to_dict()
        data["type"] = "pattern"
        try:
            if self._use_db and hasattr(self.database, "save_memory_entry"):
                await self.database.save_memory_entry(data, upsert_key="title")
            else:
                for i, p in enumerate(self._patterns):
                    if p.get("title") == pattern.title:
                        data["confidence"] = min(1.0, pattern.confidence + 0.05)
                        data["usage_count"] = p.get("usage_count", 0) + 1
                        self._patterns[i] = data
                        return True
                self._patterns.append(data)
            return True
        except Exception as e:
            logger.warning(f"Memory: could not save pattern: {e}")
            self._patterns.append(data)
            return False

    async def get_relevant_patterns(
        self,
        context: str,
        pattern_types: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[LearnedPattern]:
        """Fetch patterns whose keywords match the given context."""
        try:
            if self._use_db and hasattr(self.database, "get_memory_entries"):
                all_patterns = await self.database.get_memory_entries("pattern", limit=200)
            else:
                all_patterns = self._patterns
        except Exception as e:
            logger.warning(f"Memory: could not load patterns: {e}")
            all_patterns = self._patterns

        if not all_patterns:
            return []

        context_words = set(_tokenize(context))
        scored: List[tuple] = []
        for p in all_patterns:
            if pattern_types and p.get("pattern_type") not in pattern_types:
                continue
            kw_words = set(_tokenize(" ".join(p.get("context_keywords", []))))
            if not kw_words:
                continue
            overlap = len(context_words & kw_words)
            score = overlap / len(kw_words) if kw_words else 0
            score *= 1 + p.get("confidence", 0.5)
            if score > 0.1:
                scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [LearnedPattern.from_dict(p) for _, p in scored[:limit]]

    # ── Project events ───────────────────────────────────────

    async def add_project_event(
        self, project_id: str, event: str, detail: str = ""
    ) -> bool:
        """Log a project-level event."""
        entry = {
            "project_id": project_id,
            "event": event,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "project_event",
        }
        try:
            if self._use_db and hasattr(self.database, "save_memory_entry"):
                await self.database.save_memory_entry(entry)
            else:
                if project_id not in self._project_events:
                    self._project_events[project_id] = []
                self._project_events[project_id].append(entry)
            return True
        except Exception as e:
            logger.warning(f"Memory: could not add project event: {e}")
            if project_id not in self._project_events:
                self._project_events[project_id] = []
            self._project_events[project_id].append(entry)
            return False

    async def get_project_history(
        self, project_id: str, limit: int = 20
    ) -> List[Dict]:
        """Get event history for a project."""
        try:
            if self._use_db and hasattr(self.database, "get_memory_entries_for_project"):
                return await self.database.get_memory_entries_for_project(
                    project_id, limit=limit
                )
            else:
                return self._project_events.get(project_id, [])[-limit:]
        except Exception as e:
            logger.warning(f"Memory: could not load project history: {e}")
            return self._project_events.get(project_id, [])[-limit:]

    # ── High-level helper ────────────────────────────────────

    async def get_context_for_prompt(
        self, prompt: str, project_id: Optional[str] = None
    ) -> MemoryContext:
        """Assemble full MemoryContext for a given prompt in one call."""
        similar = await self.get_similar_builds(prompt)
        patterns = await self.get_relevant_patterns(prompt)
        history: List[Dict] = []
        if project_id:
            history = await self.get_project_history(project_id)
        return MemoryContext(
            similar_builds=similar,
            relevant_patterns=patterns,
            project_history=history,
        )

    # ── Seed built-in best practices ─────────────────────────

    async def seed_default_patterns(self):
        """Seed the memory with essential React / app-builder best practices."""
        defaults = [
            LearnedPattern(
                pattern_type="architecture",
                title="Mock data with useState for CRUD",
                description=(
                    "When Supabase is not connected, use useState arrays with unique IDs"
                    " for CRUD operations."
                ),
                context_keywords=[
                    "mock", "data", "crud", "todo", "list", "add", "delete", "edit",
                ],
                solution=(
                    "Initialize state with array of objects (id, ...fields). "
                    "Use uuid or Date.now() for IDs. Provide add/update/delete helpers."
                ),
                confidence=0.95,
            ),
            LearnedPattern(
                pattern_type="ui",
                title="Tailwind + Lucide icons",
                description="Use Tailwind CSS for styling and Lucide React for icons.",
                context_keywords=["ui", "design", "icons", "style", "tailwind"],
                solution=(
                    "Import icons from 'lucide-react'. "
                    "Use Tailwind utility classes for layout/spacing/colors. "
                    "Never use inline style objects when a Tailwind class exists."
                ),
                confidence=0.9,
            ),
            LearnedPattern(
                pattern_type="error_fix",
                title="Undefined component reference",
                description=(
                    "ReferenceError: SomeComponent is not defined —"
                    " component used before import/definition."
                ),
                context_keywords=[
                    "undefined", "reference", "not defined", "component", "import",
                ],
                solution=(
                    "Move component definitions above the component that uses them. "
                    "Never forward-reference components in JSX without hoisting."
                ),
                confidence=0.9,
            ),
            LearnedPattern(
                pattern_type="error_fix",
                title="Switch/Redirect not defined (React Router v5 vs v6)",
                description=(
                    "Uncaught ReferenceError: Switch is not defined —"
                    " v5 API used in v6 environment."
                ),
                context_keywords=[
                    "switch", "redirect", "router", "react router", "v5", "v6",
                ],
                solution=(
                    "Replace <Switch> with <Routes> and <Redirect> with <Navigate>. "
                    "Use useNavigate() instead of useHistory(). "
                    "Wrap app with <BrowserRouter> at the top level."
                ),
                confidence=0.95,
            ),
            LearnedPattern(
                pattern_type="architecture",
                title="Single App.jsx entry point",
                description=(
                    "Always export a default App component from App.jsx"
                    " as the main entry point."
                ),
                context_keywords=["app", "entry", "main", "root", "app.jsx"],
                solution=(
                    "App.jsx must export default App. "
                    "All routing and layout wrappers go inside App. "
                    "Never split the root render call across multiple files."
                ),
                confidence=0.95,
            ),
            LearnedPattern(
                pattern_type="ui",
                title="Responsive layout with flex/grid",
                description="Build mobile-friendly layouts using Tailwind flex and grid utilities.",
                context_keywords=[
                    "responsive", "mobile", "layout", "grid", "flex", "dashboard",
                ],
                solution=(
                    "Use flex-col on mobile, md:flex-row on desktop. "
                    "Grid: grid-cols-1 sm:grid-cols-2 lg:grid-cols-3. "
                    "Always add max-w-* and mx-auto for content centering."
                ),
                confidence=0.85,
            ),
            LearnedPattern(
                pattern_type="architecture",
                title="Component file structure",
                description="Organize components into logical folders for maintainability.",
                context_keywords=[
                    "components", "structure", "folder", "organize", "pages",
                ],
                solution=(
                    "Place pages in pages/, reusable UI in components/. "
                    "Data helpers in lib/ or utils/. "
                    "Mock data in data/mockData.js. "
                    "Keep App.jsx clean — delegate rendering to page components."
                ),
                confidence=0.85,
            ),
        ]
        for pattern in defaults:
            await self.save_pattern(pattern)
        logger.info(f"Memory: seeded {len(defaults)} default patterns")


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "is", "are", "was", "be",
    "this", "that", "it", "i", "me", "my", "we", "you", "he", "she",
    "create", "build", "make", "app", "application", "use", "using",
}


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer, lowercase, stops removed."""
    tokens = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


# ──────────────────────────────────────────────────────────
# Global singleton (initialised once in server startup)
# ──────────────────────────────────────────────────────────

_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> Optional[MemoryStore]:
    return _memory_store


def init_memory_store(database=None) -> MemoryStore:
    global _memory_store
    _memory_store = MemoryStore(database)
    return _memory_store

