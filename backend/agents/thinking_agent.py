"""
Thinking Agent - Deep reasoning layer for the AI App Builder

Uses Claude claude-sonnet-4-5 with extended thinking (budget_tokens) to reason carefully
before each pipeline step. Ingests MemoryContext so it applies lessons from past builds.

Key methods
-----------
think_about_request(prompt, memory_context, project_state)
    -> Before requirements: understand intent, pick architecture, spot ambiguities

think_before_code_gen(requirements, memory_context, existing_files)
    -> Before code gen: choose patterns, anticipate errors, set generation strategy

think_before_fix(test_results, files, memory_context, attempt)
    -> Before fix: diagnose root causes, pick minimal targeted fixes

generate_intelligent_response(user_msg, history, project_ctx, agent_actions)
    -> Natural conversational reply shown in the chat sidebar
"""

import json
import logging
import re
from typing import Dict, List, Optional, Any

import httpx

from .model_config import CLAUDE_LATEST

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# System prompts
# ──────────────────────────────────────────────────────────────────────────

_THINK_REQUEST_SYSTEM = """\
You are an expert app architect and product thinker for an AI App Builder.

Your job is to deeply reason about a user's app request BEFORE any agents build it.
You have access to memory from past builds - use it to avoid mistakes and apply patterns.

Reason step-by-step:
1. What is the user ACTUALLY trying to accomplish? (not just what they said)
2. What type of app is this? (CRUD, dashboard, landing page, tool, game, etc.)
3. What features are essential vs. nice-to-have?
4. What architecture fits best given past experience?
5. What are the likely pain points or edge cases?
6. What patterns from memory should guide this build?

Return ONLY valid JSON (no markdown fences):
{
  "understanding": "What the user truly wants",
  "app_type": "todo|dashboard|crud|landing|tool|other",
  "essential_features": ["feature1", "feature2"],
  "architecture_recommendation": "Specific advice on component structure, state management, routing",
  "patterns_to_apply": ["pattern title1", "pattern title2"],
  "pitfalls_to_avoid": ["potential issue 1", "potential issue 2"],
  "confidence": "high|medium|low",
  "needs_clarification": false,
  "clarification_questions": []
}"""

_THINK_CODE_GEN_SYSTEM = """\
You are a senior React developer and code architect.

Think carefully about the BEST WAY to generate code for this app.
You have the requirements, memory of past builds, and optionally existing files.

Reason step-by-step:
1. What component structure minimises complexity?
2. What state management approach fits (local useState, Context, or lifted state)?
3. What mock-data shape is needed for each feature?
4. What Lucide icons are appropriate?
5. Which patterns from memory apply directly?
6. What mistakes must be avoided (from memory)?

Return ONLY valid JSON:
{
  "component_plan": ["App.jsx", "components/Header.jsx", "..."],
  "state_strategy": "Describe how state will be managed",
  "mock_data_shape": "Describe the mock data arrays/objects needed",
  "key_patterns": ["pattern1", "pattern2"],
  "warnings": ["known pitfall 1", "..."],
  "generation_instructions": "Concise additional instructions for the code generation agent"
}"""

_THINK_FIX_SYSTEM = """\
You are a React debugging expert.

Tests have failed. Think carefully about the ROOT CAUSE and the MINIMAL FIX.
Do NOT suggest rewriting everything - prefer targeted, surgical fixes.

Reason step-by-step:
1. What do the test failures actually indicate?
2. Which files are most likely at fault?
3. What is the root cause (not a symptom)?
4. What is the smallest change that fixes it?
5. Have we seen this error pattern in memory before?

Return ONLY valid JSON:
{
  "root_cause": "Concise root cause description",
  "affected_files": ["file1.jsx", "..."],
  "fix_strategy": "Describe the minimal fix approach",
  "from_memory": "Any matching error pattern from past builds",
  "confidence": "high|medium|low"
}"""


# ──────────────────────────────────────────────────────────────────────────
# ThinkingAgent
# ──────────────────────────────────────────────────────────────────────────

class ThinkingAgent:
    """
    Deep reasoning layer.

    Uses Claude's extended thinking (budget_tokens) for rich internal reasoning,
    then returns structured JSON guidance for the rest of the pipeline.
    """

    # Tokens Claude is allowed to think internally (balance quality vs latency)
    THINKING_BUDGET = 8000
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.api_key = openrouter_api_key
        self.base_url = openrouter_base_url
    
    # ── Public API ────────────────────────────────────────────────────────

    async def think_about_request(
        self,
        user_prompt: str,
        memory_context=None,       # MemoryContext | None
        project_state: Optional[Dict] = None,
    ) -> Dict:
        """
        Think deeply about what the user wants before requirements are parsed.
        Returns a structured analysis dict.
        """
        context_block = self._format_memory(memory_context)
        state_block = ""
        if project_state:
            state_block = f"\nCURRENT PROJECT STATE:\n{json.dumps(project_state, indent=2)}"

        user_msg = (
            f"{context_block}{state_block}\n\n"
            f"USER REQUEST:\n{user_prompt}"
        )

        result = await self._think(
            system=_THINK_REQUEST_SYSTEM,
            user=user_msg,
            tag="think_request",
        )

        result.setdefault("understanding", user_prompt)
        result.setdefault("app_type", "general")
        result.setdefault("essential_features", [])
        result.setdefault("architecture_recommendation", "")
        result.setdefault("patterns_to_apply", [])
        result.setdefault("pitfalls_to_avoid", [])
        result.setdefault("confidence", "medium")
        result.setdefault("needs_clarification", False)
        result.setdefault("clarification_questions", [])
        return result

    async def think_before_code_gen(
        self,
        requirements: Dict,
        memory_context=None,
        existing_files: Optional[List[Dict]] = None,
    ) -> Dict:
        """
        Think about the best code generation strategy before code is written.
        """
        context_block = self._format_memory(memory_context)
        files_block = ""
        if existing_files:
            paths = [f.get("path", "") for f in existing_files[:10]]
            files_block = f"\nEXISTING FILES (update mode):\n{', '.join(paths)}"

        user_msg = (
            f"{context_block}{files_block}\n\n"
            f"REQUIREMENTS:\n{json.dumps(requirements, indent=2, default=str)}"
        )

        result = await self._think(
            system=_THINK_CODE_GEN_SYSTEM,
            user=user_msg,
            tag="think_code_gen",
        )

        result.setdefault("component_plan", [])
        result.setdefault("state_strategy", "Use local useState for all state")
        result.setdefault("mock_data_shape", "")
        result.setdefault("key_patterns", [])
        result.setdefault("warnings", [])
        result.setdefault("generation_instructions", "")
        return result

    async def think_before_fix(
        self,
        test_results: Dict,
        files: List[Dict],
        memory_context=None,
        attempt: int = 1,
    ) -> Dict:
        """
        Diagnose failing tests and determine the best fix strategy.
        """
        context_block = self._format_memory(memory_context)
        file_paths = [f.get("path", "") for f in files]

        issues = test_results.get("issues", [])
        failures_text = "\n".join(
            f"- [{i.get('severity', '?')}] {i.get('description', '?')}"
            f" in {i.get('file', '?')}"
            for i in issues[:10]
        )

        user_msg = (
            f"{context_block}\n\n"
            f"TEST RESULTS (attempt {attempt}):\n"
            f"  Passed: {test_results.get('passed', 0)}/{test_results.get('total', 0)}\n"
            f"  Failures:\n{failures_text or 'No detailed failure info'}\n\n"
            f"FILES IN PROJECT:\n{', '.join(file_paths)}"
        )

        result = await self._think(
            system=_THINK_FIX_SYSTEM,
            user=user_msg,
            tag="think_fix",
        )

        result.setdefault("root_cause", "Unknown - proceeding with best-effort fix")
        result.setdefault("affected_files", [])
        result.setdefault("fix_strategy", "Fix the most critical issues first")
        result.setdefault("from_memory", "")
        result.setdefault("confidence", "medium")
        return result
    
    async def generate_intelligent_response(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
        project_context: Optional[Dict] = None,
        agent_actions: Optional[List[Dict]] = None,
    ) -> str:
        """
        Generate a natural, helpful conversational response to the user.
        Used for chat messages in the sidebar.
        """
        system = self._build_response_system(project_context, agent_actions)
        messages = [{"role": "system", "content": system}]

        if conversation_history:
            for msg in conversation_history[-8:]:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })
        
        messages.append({"role": "user", "content": user_message})
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers("Intelligent Response"),
                    json={
                        "model": CLAUDE_LATEST,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 800,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"ThinkingAgent.generate_intelligent_response: {e}")
            return "I'm thinking through your request - the agents are on it!"

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _think(self, system: str, user: str, tag: str) -> Dict:
        """
        Core thinking call with Claude extended thinking.

        Tries extended thinking first; falls back to standard call if the
        model/provider doesn't support the thinking parameter.
        """
        messages = [{"role": "user", "content": user}]

        # ── Attempt 1: extended thinking ──────────────────────────────────
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "model": CLAUDE_LATEST,
                    "system": system,
                    "messages": messages,
                    "temperature": 1,      # required when thinking is enabled
                    "max_tokens": self.THINKING_BUDGET + 4000,
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": self.THINKING_BUDGET,
                    },
                }
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(tag),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                json_text = self._extract_json(content)
                result = json.loads(json_text)
                logger.info(
                    f"ThinkingAgent [{tag}]: extended thinking complete,"
                    f" confidence={result.get('confidence', '?')}"
                )
                return result

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"ThinkingAgent [{tag}]: parse error in extended thinking ({e})")
        except Exception as e:
            logger.warning(
                f"ThinkingAgent [{tag}]: extended thinking failed ({e}),"
                f" falling back to standard call"
            )

        # ── Attempt 2: standard call (no thinking budget) ────────────────
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": CLAUDE_LATEST,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4000,
                }
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(tag),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                json_text = self._extract_json(content)
                result = json.loads(json_text)
                logger.info(
                    f"ThinkingAgent [{tag}]: standard call complete,"
                    f" confidence={result.get('confidence', '?')}"
                )
                return result
                
        except Exception as e:
            logger.warning(f"ThinkingAgent [{tag}]: standard call also failed ({e})")
            return {}

    def _extract_json(self, content) -> str:
        """
        Extract the JSON portion from Claude's response.
        content can be a string or a list of content blocks.
        """
        if isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") == "text":
                    return self._strip_to_json(block["text"])
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict)]
            return self._strip_to_json(" ".join(text_parts))
        return self._strip_to_json(str(content))

    @staticmethod
    def _strip_to_json(text: str) -> str:
        """Strip markdown fences and extract the JSON object/array."""
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = re.sub(r"```", "", text)
        start = min(
            text.find("{") if "{" in text else len(text),
            text.find("[") if "[" in text else len(text),
        )
        end = max(text.rfind("}"), text.rfind("]")) + 1
        if start < end:
            return text[start:end]
        return text.strip()

    def _format_memory(self, memory_context) -> str:
        """Format memory context into a prompt block."""
        if memory_context is None:
            return ""
        try:
            formatted = memory_context.format_for_prompt()
            return f"\n{formatted}" if formatted else ""
        except Exception:
            return ""

    def _build_response_system(
        self,
        project_context: Optional[Dict],
        agent_actions: Optional[List[Dict]],
    ) -> str:
        prompt = (
            "You are a helpful, intelligent assistant embedded in an AI App Builder.\n\n"
            "Respond naturally and concisely. Show that you understand the user's goal.\n"
            "Explain what the agents are doing in plain, friendly language.\n\n"
        )
        if project_context:
            prompt += f"PROJECT:\n{json.dumps(project_context, indent=2)}\n\n"
        if agent_actions:
            prompt += "RECENT AGENT ACTIONS:\n"
            for a in agent_actions[-4:]:
                prompt += f"  - {a.get('agent', '?')}: {a.get('plan', '')}\n"
        return prompt

    def _headers(self, title: str) -> Dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://app-builder.local",
            "X-Title": f"App Builder - {title}",
            "Content-Type": "application/json",
        }
