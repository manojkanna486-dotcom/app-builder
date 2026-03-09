"""
Agent Orchestrator - Coordinates the multi-agent pipeline
Manages the flow: Clarify → Generate → Deploy → Test → Fix (loop)
"""

import json
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
from datetime import datetime, timezone

from .clarification_agent import ClarificationAgent, format_requirements_for_storage
from .code_generation_agent import CodeGenerationAgent
from .deployment_agent import DeploymentAgent
from .testing_agent import TestingAgent, MAX_FIX_RETRIES
from .dev_agent import DevAgent

logger = logging.getLogger(__name__)

# Pipeline stages
STAGE_CLARIFY = "clarify"
STAGE_GENERATE = "generate"
STAGE_DEPLOY = "deploy"
STAGE_TEST = "test"
STAGE_FIX = "fix"
STAGE_COMPLETE = "complete"


class AgentOrchestrator:
    """
    Orchestrates the multi-agent pipeline for app building.
    
    Flow:
    1. Clarification Agent: Analyze prompt, extract requirements, ask questions
    2. Code Generation Agent: Generate React + Supabase code
    3. Deployment Agent: Run migrations, deploy Edge Functions
    4. Testing Agent: Deep test against requirements
    5. Dev Agent: Fix issues (max 3 retries)
    6. Loop back to Deploy → Test → Fix until success or max retries
    """
    
    def __init__(self, openrouter_api_key: str, openrouter_base_url: str):
        self.clarification_agent = ClarificationAgent(openrouter_api_key, openrouter_base_url)
        self.code_generation_agent = CodeGenerationAgent(openrouter_api_key, openrouter_base_url)
        self.deployment_agent = DeploymentAgent()
        self.testing_agent = TestingAgent(openrouter_api_key, openrouter_base_url)
        self.dev_agent = DevAgent(openrouter_api_key, openrouter_base_url)
        
    async def analyze_prompt(self, prompt: str, project_context: Optional[Dict] = None) -> Dict:
        """
        Stage 1: Analyze the prompt and extract requirements.
        Returns analysis with requirements and optional questions.
        """
        logger.info(f"Orchestrator: Analyzing prompt")
        return await self.clarification_agent.analyze_prompt(prompt, project_context)
    
    async def refine_requirements(self, analysis: Dict, user_answers: Dict[str, str]) -> Dict:
        """
        Stage 1b: Refine requirements based on user answers.
        """
        logger.info(f"Orchestrator: Refining requirements with user answers")
        return await self.clarification_agent.refine_requirements(analysis, user_answers)
    
    async def run_pipeline(
        self,
        requirements: Dict,
        supabase_config: Dict,
        access_token: str,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False,
        max_fix_retries: int = MAX_FIX_RETRIES,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[Dict, None]:
        """
        Run the complete pipeline: Generate → Deploy → Test → Fix
        Yields status updates throughout the process.
        """
        
        current_files = existing_files or []
        fix_attempt = 0
        
        # Stage 2: Generate Code
        yield {"stage": STAGE_GENERATE, "status": "starting", "message": "🚀 Starting code generation..."}
        
        try:
            generation_result = await self.code_generation_agent.generate_code(
                requirements=requirements,
                supabase_config=supabase_config,
                existing_files=existing_files,
                is_update=is_update,
                conversation_history=conversation_history,
            )
            current_files = generation_result.get("files", [])
            yield {
                "stage": STAGE_GENERATE, 
                "status": "complete", 
                "message": f"✅ Generated {len(current_files)} files",
                "files": current_files,
                "summary": generation_result.get("summary", "")
            }
        except Exception as e:
            logger.error(f"Code generation failed: {e}")
            yield {"stage": STAGE_GENERATE, "status": "error", "message": f"❌ Generation failed: {str(e)}"}
            return
        
        # Pipeline loop: Deploy → Test → Fix
        while fix_attempt <= max_fix_retries:
            # Stage 3: Deploy
            yield {"stage": STAGE_DEPLOY, "status": "starting", "message": "📦 Deploying to Supabase..."}
            
            try:
                deploy_result = await self.deployment_agent.deploy(
                    files=current_files,
                    supabase_config=supabase_config,
                    access_token=access_token
                )
                
                if deploy_result.get("errors"):
                    yield {
                        "stage": STAGE_DEPLOY,
                        "status": "partial",
                        "message": f"⚠️ Deployment completed with errors",
                        "result": deploy_result
                    }
                else:
                    yield {
                        "stage": STAGE_DEPLOY,
                        "status": "complete",
                        "message": f"✅ Deployed: {len(deploy_result.get('migrations', []))} migrations, {len(deploy_result.get('edge_functions', []))} functions",
                        "result": deploy_result
                    }
            except Exception as e:
                logger.error(f"Deployment failed: {e}")
                yield {"stage": STAGE_DEPLOY, "status": "error", "message": f"❌ Deployment failed: {str(e)}"}
                # Continue to testing anyway - frontend may still work
            
            # Stage 4: Test
            yield {"stage": STAGE_TEST, "status": "starting", "message": "🧪 Running deep tests..."}
            
            try:
                test_results = await self.testing_agent.run_tests(
                    files=current_files,
                    requirements=requirements,
                    supabase_config=supabase_config
                )
                
                yield {
                    "stage": STAGE_TEST,
                    "status": "complete",
                    "message": test_results.get("summary", ""),
                    "result": test_results
                }
                
                # Check if all tests passed
                if test_results.get("failed", 0) == 0:
                    yield {
                        "stage": STAGE_COMPLETE,
                        "status": "success",
                        "message": "🎉 All tests passed! App is ready.",
                        "files": current_files
                    }
                    return
                
            except Exception as e:
                logger.error(f"Testing failed: {e}")
                yield {"stage": STAGE_TEST, "status": "error", "message": f"❌ Testing failed: {str(e)}"}
                test_results = {"failed": 1, "issues": [{"error": str(e)}]}
            
            # Stage 5: Fix (if tests failed)
            if fix_attempt < max_fix_retries:
                fix_attempt += 1
                yield {
                    "stage": STAGE_FIX,
                    "status": "starting",
                    "message": f"🔧 Fixing issues (attempt {fix_attempt}/{max_fix_retries})..."
                }
                
                try:
                    fix_result = await self.dev_agent.fix_issues(
                        files=current_files,
                        test_results=test_results,
                        requirements=requirements,
                        attempt=fix_attempt,
                        conversation_history=conversation_history,
                    )
                    
                    if fix_result.get("fixes_applied"):
                        current_files = fix_result.get("files", current_files)
                        yield {
                            "stage": STAGE_FIX,
                            "status": "complete",
                            "message": f"✅ Applied {len(fix_result.get('fixes_applied', []))} fixes",
                            "files": current_files,
                            "fixes": fix_result.get("fixes_applied", [])
                        }
                    else:
                        yield {
                            "stage": STAGE_FIX,
                            "status": "no_changes",
                            "message": "⚠️ No fixes could be applied"
                        }
                        
                except Exception as e:
                    logger.error(f"Fix attempt failed: {e}")
                    yield {"stage": STAGE_FIX, "status": "error", "message": f"❌ Fix failed: {str(e)}"}
            else:
                # Max retries reached
                yield {
                    "stage": STAGE_COMPLETE,
                    "status": "partial",
                    "message": f"⚠️ Max fix attempts ({max_fix_retries}) reached. Some issues remain.",
                    "files": current_files,
                    "remaining_issues": test_results.get("issues", [])
                }
                return
        
        # Should not reach here, but just in case
        yield {
            "stage": STAGE_COMPLETE,
            "status": "complete",
            "message": "Pipeline completed",
            "files": current_files
        }
    
    async def run_pipeline_stream(
        self,
        requirements: Dict,
        supabase_config: Dict,
        access_token: str,
        existing_files: Optional[List[Dict]] = None,
        is_update: bool = False,
        max_fix_retries: int = MAX_FIX_RETRIES,
        conversation_history: Optional[List[Dict]] = None
    ) -> AsyncGenerator[str, None]:
        """
        Run pipeline with streaming code generation for UI.
        Yields SSE-formatted messages.
        """
        
        current_files = existing_files or []
        fix_attempt = 0
        
        # Stage 2: Generate Code (streaming)
        yield f"data: {json.dumps({'type': 'status', 'stage': STAGE_GENERATE, 'message': '🚀 Generating code...'})}\n\n"
        
        full_content = ""
        try:
            async for chunk in self.code_generation_agent.generate_code_stream(
                requirements=requirements,
                supabase_config=supabase_config,
                existing_files=existing_files,
                is_update=is_update,
                conversation_history=conversation_history,
            ):
                full_content += chunk
                yield f"data: {json.dumps({'type': 'code', 'content': chunk})}\n\n"
            
            # Parse the complete response
            generation_result = self.code_generation_agent._parse_generation_response(full_content)
            current_files = generation_result.get("files", [])
            
            # Sanitize to fix common syntax errors before deploy/test/fix
            try:
                from code_utils import sanitize_frontend_files
                sanitize_frontend_files(current_files)
            except Exception as e:
                logger.warning(f"Sanitize warning: {e}")
            
            yield f"data: {json.dumps({'type': 'status', 'stage': STAGE_GENERATE, 'message': f'✅ Generated {len(current_files)} files'})}\n\n"
            
        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': f'Generation failed: {str(e)}'})}\n\n"
            return
        
        # Continue with non-streaming stages
        async for update in self._run_post_generation_pipeline(
            current_files=current_files,
            requirements=requirements,
            supabase_config=supabase_config,
            access_token=access_token,
            max_fix_retries=max_fix_retries
        ):
            yield f"data: {json.dumps(update)}\n\n"
    
    async def _run_post_generation_pipeline(
        self,
        current_files: List[Dict],
        requirements: Dict,
        supabase_config: Dict,
        access_token: str,
        max_fix_retries: int
    ) -> AsyncGenerator[Dict, None]:
        """Run the deploy → test → fix loop"""
        
        fix_attempt = 0
        
        while fix_attempt <= max_fix_retries:
            # Deploy
            yield {"type": "status", "stage": STAGE_DEPLOY, "message": "📦 Deploying to Supabase..."}
            
            try:
                deploy_result = await self.deployment_agent.deploy(
                    files=current_files,
                    supabase_config=supabase_config,
                    access_token=access_token
                )
                
                if deploy_result.get("status") == "error":
                    yield {"type": "deploy_result", "status": "error", "errors": deploy_result.get("errors", [])}
                else:
                    yield {"type": "deploy_result", "status": "success", "result": deploy_result}
                    
            except Exception as e:
                yield {"type": "deploy_result", "status": "error", "message": str(e)}
            
            # Test
            yield {"type": "status", "stage": STAGE_TEST, "message": "🧪 Running tests..."}
            
            try:
                test_results = await self.testing_agent.run_tests(
                    files=current_files,
                    requirements=requirements,
                    supabase_config=supabase_config
                )
                
                yield {
                    "type": "test_result",
                    "passed": test_results.get("passed", 0),
                    "failed": test_results.get("failed", 0),
                    "total": test_results.get("total", 0),
                    "summary": test_results.get("summary", ""),
                    "issues": test_results.get("issues", [])
                }
                
                if test_results.get("failed", 0) == 0:
                    yield {
                        "type": "complete",
                        "status": "success",
                        "message": "🎉 All tests passed!",
                        "files": current_files
                    }
                    return
                    
            except Exception as e:
                yield {"type": "test_result", "status": "error", "message": str(e)}
                test_results = {"failed": 1, "issues": []}
            
            # Fix
            if fix_attempt < max_fix_retries:
                fix_attempt += 1
                yield {"type": "status", "stage": STAGE_FIX, "message": f"🔧 Fixing issues ({fix_attempt}/{max_fix_retries})..."}
                
                try:
                    fix_result = await self.dev_agent.fix_issues(
                        files=current_files,
                        test_results=test_results,
                        requirements=requirements,
                        attempt=fix_attempt
                    )
                    
                    if fix_result.get("fixes_applied"):
                        current_files = fix_result.get("files", current_files)
                        yield {
                            "type": "fix_result",
                            "status": "success",
                            "fixes": fix_result.get("fixes_applied", []),
                            "files": current_files
                        }
                    else:
                        yield {"type": "fix_result", "status": "no_changes"}
                        
                except Exception as e:
                    yield {"type": "fix_result", "status": "error", "message": str(e)}
            else:
                yield {
                    "type": "complete",
                    "status": "partial",
                    "message": f"⚠️ Max retries reached. {test_results.get('failed', 0)} issues remain.",
                    "files": current_files,
                    "remaining_issues": test_results.get("issues", [])
                }
                return
