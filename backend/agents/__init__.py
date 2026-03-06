# Multi-Agent System for App Builder
# 
# Agent Responsibilities:
# 1. Orchestrator (Brain) - Owns workflow, decides agent order, tracks state
# 2. Requirements Agent - Converts prompts to requirements.json
# 3. Dev Agent (CodeGeneration) - Generates frontend + Supabase code
# 4. Deployment Agent - Deploys preview builds safely
# 5. Tester Agent - Conversational testing like a real user
# 6. Fix Agent - Fixes only reported issues, minimal changes

from .requirements_agent import RequirementsAgent
from .code_generation_agent import CodeGenerationAgent
from .deployment_agent import DeploymentAgent
from .tester_agent import ConversationalTesterAgent
from .fix_agent import FixAgent
from .thinking_agent import ThinkingAgent
from .orchestrator_v2 import Orchestrator, BuildState, BuildContext

# Legacy imports for backwards compatibility
from .clarification_agent import ClarificationAgent
from .testing_agent import TestingAgent
from .dev_agent import DevAgent
from .orchestrator import AgentOrchestrator

__all__ = [
    # New architecture
    'Orchestrator',
    'RequirementsAgent',
    'CodeGenerationAgent',
    'DeploymentAgent',
    'ConversationalTesterAgent',
    'FixAgent',
    'ThinkingAgent',
    'BuildState',
    'BuildContext',
    
    # Legacy (for backwards compatibility)
    'AgentOrchestrator',
    'ClarificationAgent',
    'TestingAgent',
    'DevAgent'
]
