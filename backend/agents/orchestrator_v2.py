"""
Orchestrator Agent (Brain) - Owns the entire workflow
MUST DO: Start builds, track state, stop on cancel, enforce retry limits
MUST NOT: Write code, modify requirements directly
"""

import json
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, asdict

from .requirements_agent import RequirementsAgent
from .code_generation_agent import CodeGenerationAgent
from .deployment_agent import DeploymentAgent
from .tester_agent import ConversationalTesterAgent
from .fix_agent import FixAgent

logger = logging.getLogger(__name__)


class BuildState(str, Enum):
    """Build states"""
    PENDING = "pending"
    PARSING_REQUIREMENTS = "parsing_requirements"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    GENERATING_CODE = "generating_code"
    DEPLOYING = "deploying"
    TESTING = "testing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BuildContext:
    """Context passed between agents"""
    project_id: str
    prompt: str
    requirements: Optional[Dict] = None
    files: Optional[List[Dict]] = None
    test_results: Optional[Dict] = None
    supabase_config: Optional[Dict] = None
    conversation_history: Optional[List[Dict]] = None
    state: BuildState = BuildState.PENDING
    current_agent: Optional[str] = None
    fix_attempts: int = 0
    max_fix_attempts: int = 3
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class Orchestrator:
    """
    Brain of the multi-agent system.
    
    Responsibilities:
    - Owns the entire workflow
    - Decides which agent runs and in what order
    - Passes context between agents
    - Enforces system rules and limits
    
    Workflow:
    1. Requirements Agent: Parse prompt → requirements.json
    2. (Optional) Wait for user clarification
    3. Dev Agent: Generate code from requirements
    4. Deployment Agent: Deploy to Supabase
    5. Tester Agent: Conversational testing
    6. Fix Agent: Fix issues (max 3 retries)
    7. Loop 4-6 until success or max retries
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.requirements_agent = RequirementsAgent(openrouter_api_key, openrouter_base_url)
        self.code_generation_agent = CodeGenerationAgent(openrouter_api_key, openrouter_base_url)
        self.deployment_agent = DeploymentAgent()
        self.tester_agent = ConversationalTesterAgent(openrouter_api_key, openrouter_base_url)
        self.fix_agent = FixAgent(openrouter_api_key, openrouter_base_url)
        
        # Track active builds for cancellation
        self._active_builds: Dict[str, BuildContext] = {}
        self._cancelled_builds: set = set()
    
    # ==================== BUILD CONTROL ====================
    
    async def start_build(
        self,
        project_id: str,
        prompt: str,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[Dict, None]:
        """
        Start a new build.
        Yields status updates throughout the process.
        """
        
        # Initialize build context
        context = BuildContext(
            project_id=project_id,
            prompt=prompt,
            supabase_config=supabase_config,
            files=existing_files,
            conversation_history=conversation_history or [],
            started_at=datetime.now(timezone.utc).isoformat()
        )
        
        self._active_builds[project_id] = context
        
        try:
            async for update in self._run_build_pipeline(context):
                yield update
                
                # Check for cancellation
                if project_id in self._cancelled_builds:
                    context.state = BuildState.CANCELLED
                    yield self._status("cancelled", "Build cancelled by user")
                    return
                    
        finally:
            # Cleanup
            if project_id in self._active_builds:
                del self._active_builds[project_id]
            if project_id in self._cancelled_builds:
                self._cancelled_builds.remove(project_id)
    
    def cancel_build(self, project_id: str) -> bool:
        """Cancel a running build"""
        
        if project_id in self._active_builds:
            self._cancelled_builds.add(project_id)
            logger.info(f"Build {project_id} marked for cancellation")
            return True
        return False
    
    def get_build_state(self, project_id: str) -> Optional[Dict]:
        """Get current state of a build"""
        
        if project_id in self._active_builds:
            return self._active_builds[project_id].to_dict()
        return None
    
    # ==================== REQUIREMENTS PHASE ====================
    
    async def parse_requirements(self, prompt: str, existing: Optional[Dict] = None, conversation_history: Optional[List[Dict]] = None) -> Dict:
        """
        Phase 1: Parse prompt into requirements.json
        """
        agent_context = {"conversation_history": conversation_history} if conversation_history else None
        return await self.requirements_agent.parse_prompt(prompt, existing, agent_context=agent_context)
    
    async def resolve_ambiguities(self, requirements: Dict, answers: Dict[str, str]) -> Dict:
        """
        Phase 1b: Resolve ambiguities in requirements
        """
        return await self.requirements_agent.resolve_ambiguities(requirements, answers)
    
    # ==================== MAIN PIPELINE ====================
    
    async def _run_build_pipeline(self, context: BuildContext) -> AsyncGenerator[Dict, None]:
        """Run the complete build pipeline"""
        
        # Phase 1: Parse Requirements
        context.state = BuildState.PARSING_REQUIREMENTS
        context.current_agent = "requirements"
        yield self._status("parsing", "📋 Parsing requirements...")
        
        try:
            requirements = await self.requirements_agent.parse_prompt(
                context.prompt, conversation_history=context.conversation_history
            )
            context.requirements = requirements
            
            # Check for ambiguities
            if not requirements.get("is_complete", False):
                context.state = BuildState.AWAITING_CLARIFICATION
                yield {
                    "type": "clarification_needed",
                    "requirements": requirements,
                    "ambiguities": requirements.get("ambiguities", []),
                    "summary": self.requirements_agent.get_requirements_summary(requirements)
                }
                return  # Pause and wait for user input
            
            yield self._status("requirements_complete", "✅ Requirements parsed", {
                "requirements": requirements
            })
            
        except Exception as e:
            context.state = BuildState.FAILED
            context.error = str(e)
            yield self._error(f"Requirements parsing failed: {e}")
            return
        
        # Phase 2: Generate Code
        context.state = BuildState.GENERATING_CODE
        context.current_agent = "dev"
        yield self._status("generating", "💻 Generating code...")
        
        try:
            generation_result = await self.code_generation_agent.generate_code(
                requirements=context.requirements,
                supabase_config=context.supabase_config,
                existing_files=context.files,
                is_update=context.files is not None and len(context.files) > 0,
                conversation_history=context.conversation_history,
            )
            context.files = generation_result.get("files", [])
            
            yield self._status("code_generated", f"✅ Generated {len(context.files)} files", {
                "files": context.files,
                "summary": generation_result.get("summary", "")
            })
            
        except Exception as e:
            context.state = BuildState.FAILED
            context.error = str(e)
            yield self._error(f"Code generation failed: {e}")
            return
        
        # Phase 3-5: Deploy → Test → Fix Loop
        async for update in self._run_deploy_test_fix_loop(context):
            yield update
    
    async def _run_deploy_test_fix_loop(self, context: BuildContext) -> AsyncGenerator[Dict, None]:
        """Run the deploy → test → fix loop"""
        
        while context.fix_attempts <= context.max_fix_attempts:
            
            # Check for cancellation
            if context.project_id in self._cancelled_builds:
                return
            
            # Phase 3: Deploy
            context.state = BuildState.DEPLOYING
            context.current_agent = "deployment"
            yield self._status("deploying", "📦 Deploying to Supabase...")
            
            try:
                deploy_result = await self.deployment_agent.deploy(
                    files=context.files,
                    supabase_config=context.supabase_config,
                    access_token=context.supabase_config.get("service_key")
                )
                
                if deploy_result.get("status") == "error":
                    yield self._status("deploy_warning", "⚠️ Deployment had errors", {
                        "errors": deploy_result.get("errors", [])
                    })
                else:
                    yield self._status("deployed", "✅ Deployed successfully", {
                        "migrations": len(deploy_result.get("migrations", [])),
                        "edge_functions": len(deploy_result.get("edge_functions", []))
                    })
                    
            except Exception as e:
                logger.warning(f"Deployment error: {e}")
                yield self._status("deploy_warning", f"⚠️ Deployment error: {e}")
            
            # Phase 4: Test
            context.state = BuildState.TESTING
            context.current_agent = "tester"
            yield self._status("testing", "🧪 Running tests...")
            
            try:
                test_results = await self.tester_agent.run_tests(
                    files=context.files,
                    requirements=context.requirements,
                    supabase_config=context.supabase_config
                )
                context.test_results = test_results
                
                yield self._status("tested", test_results.get("summary", ""), {
                    "passed": test_results.get("passed", 0),
                    "failed": test_results.get("failed", 0),
                    "total": test_results.get("total", 0),
                    "issues": test_results.get("issues", [])
                })
                
                # All tests passed!
                if test_results.get("failed", 0) == 0:
                    context.state = BuildState.COMPLETED
                    context.completed_at = datetime.now(timezone.utc).isoformat()
                    yield {
                        "type": "complete",
                        "status": "success",
                        "message": "🎉 All tests passed! App is ready.",
                        "files": context.files,
                        "test_report": self.tester_agent.generate_test_report(test_results)
                    }
                    return
                    
            except Exception as e:
                logger.error(f"Testing error: {e}")
                context.test_results = {"failed": 1, "issues": [{"error": str(e)}]}
                yield self._status("test_error", f"⚠️ Testing error: {e}")
            
            # Phase 5: Fix (if tests failed and retries remain)
            if context.fix_attempts < context.max_fix_attempts:
                context.fix_attempts += 1
                context.state = BuildState.FIXING
                context.current_agent = "fix"
                yield self._status("fixing", f"🔧 Fixing issues (attempt {context.fix_attempts}/{context.max_fix_attempts})...")
                
                try:
                    fix_result = await self.fix_agent.fix_issues(
                        files=context.files,
                        test_results=context.test_results,
                        requirements=context.requirements,
                        attempt=context.fix_attempts,
                        chat_history=context.conversation_history or [],
                    )
                    
                    if fix_result.get("fixes_applied"):
                        context.files = fix_result.get("files", context.files)
                        yield self._status("fixed", fix_result.get("summary", ""), {
                            "fixes": fix_result.get("fixes_applied", []),
                            "files_modified": fix_result.get("files_modified", [])
                        })
                    else:
                        yield self._status("fix_failed", "⚠️ No fixes could be applied")
                        
                except Exception as e:
                    logger.error(f"Fix error: {e}")
                    yield self._status("fix_error", f"⚠️ Fix error: {e}")
            else:
                # Max retries reached
                context.state = BuildState.COMPLETED
                context.completed_at = datetime.now(timezone.utc).isoformat()
                yield {
                    "type": "complete",
                    "status": "partial",
                    "message": f"⚠️ Max fix attempts ({context.max_fix_attempts}) reached. {context.test_results.get('failed', 0)} issues remain.",
                    "files": context.files,
                    "remaining_issues": context.test_results.get("issues", [])
                }
                return
    
    async def continue_build(
        self,
        project_id: str,
        requirements: Dict,
        supabase_config: Dict,
        existing_files: Optional[List[Dict]] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[Dict, None]:
        """
        Continue build after clarification.
        Requirements should have is_complete=True.
        """
        
        context = BuildContext(
            project_id=project_id,
            prompt="",  # Already parsed
            requirements=requirements,
            supabase_config=supabase_config,
            files=existing_files,
            conversation_history=conversation_history or [],
            started_at=datetime.now(timezone.utc).isoformat()
        )
        
        self._active_builds[project_id] = context
        
        try:
            # Skip to code generation
            context.state = BuildState.GENERATING_CODE
            context.current_agent = "dev"
            yield self._status("generating", "💻 Generating code...")
            
            generation_result = await self.code_generation_agent.generate_code(
                requirements=requirements,
                supabase_config=supabase_config,
                existing_files=existing_files,
                is_update=existing_files is not None and len(existing_files) > 0,
                conversation_history=conversation_history,
            )
            context.files = generation_result.get("files", [])
            
            yield self._status("code_generated", f"✅ Generated {len(context.files)} files", {
                "files": context.files
            })
            
            # Continue with deploy → test → fix loop
            async for update in self._run_deploy_test_fix_loop(context):
                yield update
                
        finally:
            if project_id in self._active_builds:
                del self._active_builds[project_id]
    
    # ==================== HELPERS ====================
    
    def _status(self, stage: str, message: str, data: Optional[Dict] = None) -> Dict:
        """Create a status update"""
        update = {
            "type": "status",
            "stage": stage,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if data:
            update.update(data)
        return update
    
    def _error(self, message: str) -> Dict:
        """Create an error update"""
        return {
            "type": "error",
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


# Backwards compatibility aliases
AgentOrchestrator = Orchestrator
