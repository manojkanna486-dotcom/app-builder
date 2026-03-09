"""
Async Job Manager - Runs generation jobs independently of browser sessions
Uses the new Orchestrator (v2) with proper agent separation.

Key Features:
1. Jobs run independently of any browser or UI session
2. Jobs continue execution until completed or canceled
3. Progress is persisted after every step
4. Jobs are resumable after failure or restart
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from enum import Enum
import uuid

logger = logging.getLogger(__name__)

# Fix loop: max 3 fix attempts after test failures
MAX_FIX_ATTEMPTS = 3


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARSING_REQUIREMENTS = "parsing_requirements"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    GENERATING_TESTS = "generating_tests"
    GENERATING = "generating"
    DEPLOYING = "deploying"
    TESTING = "testing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStep(str, Enum):
    INIT = "init"
    REQUIREMENTS = "requirements"
    TEST_PLAN = "test_plan"
    GENERATE = "generate"
    DEPLOY = "deploy"
    TEST = "test"
    FIX = "fix"
    SAVE = "save"
    DONE = "done"


class JobManager:
    """
    Manages async generation jobs that persist independently of browser sessions.
    Uses the new Orchestrator v2 architecture with Thinking + Memory layers.
    """

    def __init__(self, database, orchestrator):
        self.database = database
        self.orchestrator = orchestrator
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._job_locks: Dict[str, asyncio.Lock] = {}
        self._cancelled_jobs: set = set()
        self._memory_store = None   # lazy-loaded via _get_memory()

    # ── Helper: lazy access to MemoryStore ──────────────────────────────

    def _get_memory(self):
        """Return the global MemoryStore, initialising if needed."""
        if self._memory_store is None:
            try:
                from agents.memory import get_memory_store, init_memory_store
                store = get_memory_store()
                if store is None:
                    store = init_memory_store(self.database)
                self._memory_store = store
            except Exception as e:
                logger.warning(f"MemoryStore unavailable: {e}")
        return self._memory_store

    # ── Helper: lazy access to ThinkingAgent ────────────────────────────

    def _get_thinking(self):
        """Return the ThinkingAgent from the orchestrator."""
        try:
            return self.orchestrator.thinking_agent
        except AttributeError:
            return None
        
    async def create_job(
        self,
        project_id: str,
        prompt: str,
        requirements: Optional[Dict] = None,
        supabase_config: Optional[Dict] = None,
    ) -> str:
        """Create a new generation job and store it in the database"""
        
        job_id = str(uuid.uuid4())
        
        job_data = {
            "id": job_id,
            "project_id": project_id,
            "prompt": prompt,
            "status": JobStatus.PENDING,
            "current_step": JobStep.INIT,
            "progress": 0,
            "requirements": requirements,
            "supabase_config": supabase_config,
            "files": [],
            "step_results": {},
            "test_results": None,
            "error": None,
            "fix_attempts": 0,
            "max_fix_attempts": MAX_FIX_ATTEMPTS,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": None,
            "completed_at": None,
        }
        
        # Store job in database for persistence
        await self.database.create_job(job_data)
        
        logger.info(f"Created job {job_id} for project {project_id}")
        return job_id
    
    async def start_job(self, job_id: str) -> bool:
        """Start or resume a job. Returns True if job was started."""
        
        job = await self.database.get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return False
        
        # Check if already running
        if job_id in self._running_jobs and not self._running_jobs[job_id].done():
            logger.warning(f"Job {job_id} is already running")
            return False
        
        # Check if job is in a runnable state
        if job["status"] in [JobStatus.COMPLETED, JobStatus.CANCELED]:
            logger.warning(f"Job {job_id} is already {job['status']}")
            return False
        
        # Create lock for this job
        if job_id not in self._job_locks:
            self._job_locks[job_id] = asyncio.Lock()
        
        # Start the job as a background task
        task = asyncio.create_task(self._run_job(job_id))
        self._running_jobs[job_id] = task
        
        logger.info(f"Started job {job_id}")
        return True
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job"""
        
        self._cancelled_jobs.add(job_id)
        
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            
        await self._update_job(job_id, {
            "status": JobStatus.CANCELED,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Also notify orchestrator
        self.orchestrator.cancel_build(job_id)
        
        logger.info(f"Canceled job {job_id}")
        return True
    
    async def get_job_status(self, job_id: str) -> Optional[Dict]:
        """Get current job status"""
        return await self.database.get_job(job_id)
    
    async def get_project_jobs(self, project_id: str) -> List[Dict]:
        """Get all jobs for a project"""
        return await self.database.get_project_jobs(project_id)
    
    async def _run_job(self, job_id: str):
        """Main job execution loop - runs independently until completion"""
        
        try:
            job = await self.database.get_job(job_id)
            if not job:
                return
            
            # Update status to running
            await self._update_job(job_id, {
                "status": JobStatus.RUNNING,
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
            
            # Get project data
            project = await self.database.get_project(job["project_id"])
            if not project:
                await self._fail_job(job_id, "Project not found")
                return
            
            # Execute the pipeline using new orchestrator
            await self._execute_pipeline_v2(job_id, job, project)
            
        except asyncio.CancelledError:
            logger.info(f"Job {job_id} was canceled")
            await self._update_job(job_id, {"status": JobStatus.CANCELED})
        except Exception as e:
            logger.error(f"Job {job_id} failed with error: {e}")
            import traceback
            traceback.print_exc()
            await self._fail_job(job_id, str(e))
    
    async def _execute_pipeline_v2(self, job_id: str, job: Dict, project: Dict):
        """
        Execute the build pipeline using new Orchestrator v2.
        
        Workflow:
        1. Requirements Agent: Parse prompt → requirements.json
        2. Dev Agent: Generate code from requirements
        3. Deployment Agent: Deploy to Supabase
        4. Save and complete job
        """
        
        project_id = job["project_id"]
        prompt = job["prompt"]
        
        supabase_config = job.get("supabase_config") or {
            "url": project.get("supabase_url"),
            "anon_key": project.get("supabase_anon_key"),
            "service_key": project.get("supabase_service_key"),
            "project_ref": project.get("supabase_project_ref"),
        }
        
        # Get existing files for updates
        existing_files = None
        is_update = project.get("current_version", 0) > 0
        if is_update:
            all_versions = await self.database.get_all_versions(project_id)
            if all_versions:
                # Merge files from all versions
                merged = {}
                for v in reversed(all_versions):
                    for f in v.get("files", []):
                        merged[f.get("path")] = f
                existing_files = list(merged.values())
        
        step_results = job.get("step_results", {})
        requirements = job.get("requirements")
        files = job.get("files", [])
        fix_attempts = job.get("fix_attempts", 0)
        max_fix_attempts = MAX_FIX_ATTEMPTS  # Fix done max 3 times

        # ==================== STEP 0: THINK + MEMORY ====================
        # Only run for fresh builds (not resumes that already have requirements)
        thinking_guidance = {}
        memory_context = None
        if not requirements or not requirements.get("is_complete"):
            memory = self._get_memory()
            thinking = self._get_thinking()

            # 0a. Load memory context for this prompt
            if memory:
                try:
                    memory_context = await memory.get_context_for_prompt(
                        prompt, project_id=project_id
                    )
                    await memory.add_project_event(
                        project_id, "build_started",
                        f"Prompt: {prompt[:80]}"
                    )
                    logger.info(
                        f"Job {job_id}: Memory loaded — "
                        f"{len(memory_context.relevant_patterns)} patterns, "
                        f"{len(memory_context.similar_builds)} similar builds"
                    )
                except Exception as e:
                    logger.warning(f"Job {job_id}: Memory context failed (non-fatal): {e}")

            # 0b. Deep thinking about the request
            if thinking:
                try:
                    await self._update_job(job_id, {
                        "current_step": "thinking",
                        "status": "thinking",
                        "progress": 5,
                    })
                    thinking_guidance = await thinking.think_about_request(
                        user_prompt=prompt,
                        memory_context=memory_context,
                        project_state={
                            "is_update": is_update,
                            "existing_files": [f.get("path") for f in (existing_files or [])],
                        },
                    )
                    logger.info(
                        f"Job {job_id}: Thinking complete — "
                        f"app_type={thinking_guidance.get('app_type')}, "
                        f"confidence={thinking_guidance.get('confidence')}, "
                        f"features={thinking_guidance.get('essential_features', [])[:3]}"
                    )
                    step_results["thinking"] = thinking_guidance
                    await self._update_job(job_id, {"step_results": step_results})
                except Exception as e:
                    logger.warning(f"Job {job_id}: Thinking step failed (non-fatal): {e}")

        # ==================== STEP 1: REQUIREMENTS ====================
        if not requirements or not requirements.get("is_complete"):
            await self._update_job(job_id, {
                "current_step": JobStep.REQUIREMENTS,
                "status": JobStatus.PARSING_REQUIREMENTS,
                "progress": 10,
            })
            
            try:
                logger.info(f"Job {job_id}: Parsing requirements")
                # Create a temporary BuildContext for message history
                from agents.context_builder import MessageHistory, build_agent_context
                temp_history = MessageHistory()
                
                # Build context for requirements agent (schema + history only, no codebase)
                agent_context = build_agent_context(
                    agent_name="requirements",
                    files=None,  # Requirements agent doesn't get codebase
                    supabase_config=supabase_config,
                    message_history=temp_history,
                    user_prompt=prompt
                )
                
                requirements = await self.orchestrator.requirements_agent.parse_prompt(prompt, requirements, agent_context)
                
                # For async jobs, auto-confirm requirements (skip clarification)
                if requirements.get("ambiguities"):
                    # Auto-resolve ambiguities with defaults
                    for amb in requirements.get("ambiguities", []):
                        amb["resolved"] = True
                        options = amb.get("options") or [""]
                        amb["answer"] = amb.get("default") or (options[0] if options else "")
                    requirements["ambiguities"] = []
                
                requirements["is_complete"] = True
                
                step_results["requirements"] = {
                    "success": True,
                    "features_count": len(requirements.get("features", [])),
                    "pages_count": len(requirements.get("pages", [])),
                    "models_count": len(requirements.get("data_models", []))
                }
                
                await self._update_job(job_id, {
                    "requirements": requirements,
                    "step_results": step_results,
                    "progress": 15,
                })
                
                logger.info(f"Job {job_id}: Requirements parsed - {len(requirements.get('features', []))} features")
                
            except Exception as e:
                logger.error(f"Job {job_id}: Requirements parsing failed: {e}")
                await self._fail_job(job_id, f"Requirements parsing failed: {str(e)}")
                return
        
        # Check cancellation
        if job_id in self._cancelled_jobs:
            return

        # ==================== STEP 1.5: GENERATE TEST CASES (TDD) ====================
        test_cases = job.get("test_cases")
        if not test_cases:
            await self._update_job(job_id, {
                "current_step": JobStep.TEST_PLAN,
                "status": JobStatus.GENERATING_TESTS,
                "progress": 17,
            })

            try:
                logger.info(f"Job {job_id}: Generating test cases from requirements (TDD)")
                test_cases = await self.orchestrator.tester_agent.generate_test_cases(requirements)
                test_cases_dict = [t.to_dict() if hasattr(t, "to_dict") else t for t in test_cases]

                step_results["test_plan"] = {
                    "success": True,
                    "test_count": len(test_cases_dict),
                }

                await self._update_job(job_id, {
                    "test_cases": test_cases_dict,
                    "step_results": step_results,
                    "progress": 18,
                })
                logger.info(f"Job {job_id}: Generated {len(test_cases_dict)} test cases")
            except Exception as e:
                logger.warning(f"Job {job_id}: Test case generation failed (non-fatal): {e}")
                test_cases = []
                test_cases_dict = []
        else:
            test_cases_dict = test_cases if isinstance(test_cases[0], dict) else [t.to_dict() for t in test_cases]

        # Check cancellation
        if job_id in self._cancelled_jobs:
            return
        
        # ==================== STEP 2: CODE GENERATION ====================
        await self._update_job(job_id, {
            "current_step": JobStep.GENERATE,
            "status": JobStatus.GENERATING,
            "progress": 20,
        })

        try:
            logger.info(f"Job {job_id}: Generating code (with {len(test_cases_dict)} acceptance test cases)")

            # 2a. Think about the best code generation strategy
            code_gen_thinking = {}
            thinking = self._get_thinking()
            if thinking:
                try:
                    code_gen_thinking = await thinking.think_before_code_gen(
                        requirements=requirements,
                        memory_context=memory_context,
                        existing_files=existing_files,
                    )
                    logger.info(
                        f"Job {job_id}: Code-gen thinking — "
                        f"components={code_gen_thinking.get('component_plan', [])[:3]}, "
                        f"warnings={code_gen_thinking.get('warnings', [])[:2]}"
                    )
                except Exception as e:
                    logger.warning(f"Job {job_id}: Code-gen thinking failed (non-fatal): {e}")

            # Build context for dev agent (full codebase + schema + history + thinking)
            from agents.context_builder import MessageHistory, build_agent_context
            temp_history = MessageHistory()

            # Enrich context with thinking guidance and memory
            thinking_block = ""
            if thinking_guidance:
                thinking_block += (
                    f"\n\nTHINKING GUIDANCE FOR THIS BUILD:\n"
                    f"  App type: {thinking_guidance.get('app_type')}\n"
                    f"  Architecture: {thinking_guidance.get('architecture_recommendation', '')}\n"
                    f"  Essential features: {', '.join(thinking_guidance.get('essential_features', []))}\n"
                    f"  Pitfalls to avoid: {', '.join(thinking_guidance.get('pitfalls_to_avoid', []))}\n"
                )
            if code_gen_thinking:
                thinking_block += (
                    f"\nCODE GENERATION PLAN:\n"
                    f"  Components: {', '.join(code_gen_thinking.get('component_plan', []))}\n"
                    f"  State strategy: {code_gen_thinking.get('state_strategy', '')}\n"
                    f"  Key patterns: {', '.join(code_gen_thinking.get('key_patterns', []))}\n"
                    f"  Warnings: {', '.join(code_gen_thinking.get('warnings', []))}\n"
                    f"  Instructions: {code_gen_thinking.get('generation_instructions', '')}\n"
                )
            if memory_context and not memory_context.is_empty():
                thinking_block += "\n" + memory_context.format_for_prompt()

            enriched_prompt = prompt + thinking_block if thinking_block else prompt

            agent_context = build_agent_context(
                agent_name="dev",
                files=existing_files,
                supabase_config=supabase_config,
                message_history=temp_history,
                user_prompt=enriched_prompt,
            )

            generation_result = await self.orchestrator.code_generation_agent.generate_code(
                requirements=requirements,
                supabase_config=supabase_config,
                existing_files=existing_files,
                is_update=is_update,
                agent_context=agent_context,
                test_cases=test_cases_dict,
            )
            
            logger.info(f"Job {job_id}: Code generation returned, parsing result...")
            
            files = generation_result.get("files", [])
            
            logger.info(f"Job {job_id}: Got {len(files)} files from generation")
            
            step_results["generate"] = {
                "success": True,
                "files_count": len(files),
                "summary": generation_result.get("summary", ""),
            }
            
            logger.info(f"Job {job_id}: Updating job with files...")
            
            await self._update_job(job_id, {
                "files": files,
                "step_results": step_results,
                "progress": 40,
            })
            
            logger.info(f"Job {job_id}: Generated {len(files)} files - sanitizing and proceeding to deploy")
            
            # Sanitize to fix common syntax errors before deploy/test/fix loop
            try:
                from code_utils import sanitize_frontend_files
                sanitize_frontend_files(files)
            except Exception as e:
                logger.warning(f"Job {job_id}: Sanitize warning: {e}")
            
        except Exception as e:
            logger.error(f"Job {job_id}: Code generation failed: {e}")
            import traceback
            traceback.print_exc()
            await self._fail_job(job_id, f"Code generation failed: {str(e)}")
            return
        
        # ==================== STEP 3-5: DEPLOY → TEST → FIX LOOP ====================
        # Run up to 3 fix loops: Test → Fix → Test → Fix → Test → Fix → Test
        while fix_attempts <= max_fix_attempts:
            
            # Check cancellation
            if job_id in self._cancelled_jobs:
                return
            
            # --- STEP 3: DEPLOY ---
            await self._update_job(job_id, {
                "current_step": JobStep.DEPLOY,
                "status": JobStatus.DEPLOYING,
                "progress": 50 + (fix_attempts * 10),
            })
            
            try:
                logger.info(f"Job {job_id}: Deploying to Supabase")
                
                deploy_result = await self.orchestrator.deployment_agent.deploy(
                    files=files,
                    supabase_config=supabase_config,
                    access_token=supabase_config.get("service_key"),
                )
                
                step_results[f"deploy_{fix_attempts}"] = deploy_result
                await self._update_job(job_id, {"step_results": step_results})
                
                if deploy_result.get("status") == "error":
                    logger.warning(f"Job {job_id}: Deployment had errors: {deploy_result.get('errors')}")
                else:
                    logger.info(f"Job {job_id}: Deployment successful")
                    
            except Exception as e:
                logger.warning(f"Job {job_id}: Deployment error: {e}")
                step_results[f"deploy_{fix_attempts}"] = {"status": "error", "error": str(e)}
            
            # --- STEP 4: TEST ---
            await self._update_job(job_id, {
                "current_step": JobStep.TEST,
                "status": JobStatus.TESTING,
                "progress": 60 + (fix_attempts * 8),
                "fix_attempts": fix_attempts,
            })

            try:
                logger.info(f"Job {job_id}: Running tests (attempt {fix_attempts + 1}/{max_fix_attempts + 1}) - reusing same {len(test_cases_dict)} test cases")
                test_results = await self.orchestrator.tester_agent.run_tests(
                    files=files,
                    requirements=requirements,
                    supabase_config=supabase_config,
                    test_cases=test_cases_dict,
                )
                step_results[f"test_{fix_attempts}"] = test_results
                await self._update_job(job_id, {
                    "test_results": test_results,
                    "step_results": step_results,
                })

                failed = test_results.get("failed", 0)
                passed = test_results.get("passed", 0)
                total = test_results.get("total", 0)
                logger.info(f"Job {job_id}: Tests {passed}/{total} passed, {failed} failed")

                if failed == 0:
                    await self._complete_job(job_id, files, requirements, prompt)
                    return

            except Exception as e:
                logger.warning(f"Job {job_id}: Testing error: {e}")
                test_results = {
                    "failed": 1,
                    "passed": 0,
                    "total": 1,
                    "issues": [{"error": str(e), "description": "Test execution failed"}],
                    "summary": f"Testing error: {e}",
                }
                step_results[f"test_{fix_attempts}"] = test_results
                await self._update_job(job_id, {"test_results": test_results, "step_results": step_results})

            # --- STEP 5: FIX (if tests failed and retries remain) ---
            if fix_attempts >= max_fix_attempts:
                logger.warning(f"Job {job_id}: Max fix attempts ({max_fix_attempts}) reached")
                await self._complete_job(
                    job_id, files, requirements, prompt,
                    partial=True,
                    remaining_issues=test_results.get("issues", []),
                )
                return

            fix_attempts += 1
            await self._update_job(job_id, {
                "current_step": JobStep.FIX,
                "status": JobStatus.FIXING,
                "progress": 70 + (fix_attempts * 8),
                "fix_attempts": fix_attempts,
            })

            try:
                logger.info(f"Job {job_id}: Fixing issues (attempt {fix_attempts}/{max_fix_attempts})")
                # Get chat history for full context (entire codebase + errors + chat sent to fix agent)
                chat_history = []
                try:
                    raw_messages = await self.database.get_messages(project_id)
                    chat_history = [
                        {"role": m.get("role", "user"), "content": m.get("content", "")}
                        for m in (raw_messages or [])[-20:]
                    ]
                except Exception as e:
                    logger.warning(f"Job {job_id}: Could not load chat history for fix: {e}")
                fix_result = await self.orchestrator.fix_agent.fix_issues(
                    files=files,
                    test_results=test_results,
                    requirements=requirements,
                    attempt=fix_attempts,
                    chat_history=chat_history,
                )
                step_results[f"fix_{fix_attempts}"] = fix_result
                await self._update_job(job_id, {"step_results": step_results})

                fixed_files = fix_result.get("files")
                if fixed_files:
                    files = fixed_files
                    # Sanitize fixed code before re-testing
                    try:
                        from code_utils import sanitize_frontend_files
                        sanitize_frontend_files(files)
                    except Exception as e:
                        logger.warning(f"Job {job_id}: Sanitize after fix: {e}")
                    logger.info(f"Job {job_id}: Applied fixes, re-testing...")
                else:
                    logger.warning(f"Job {job_id}: No fixes applied: {fix_result.get('summary', '')}")

            except Exception as e:
                logger.warning(f"Job {job_id}: Fix error: {e}")
                step_results[f"fix_{fix_attempts}"] = {"error": str(e)}
                await self._update_job(job_id, {"step_results": step_results})

        # Fallback: complete if we exit the loop without returning
        await self._complete_job(job_id, files, requirements, prompt)
    
    async def _complete_job(
        self,
        job_id: str,
        files: List[Dict],
        requirements: Dict,
        prompt: str,
        partial: bool = False,
        remaining_issues: List = None
    ):
        """Complete the job and save the version"""
        from code_utils import sanitize_frontend_files

        # Sanitize to fix common syntax errors before saving
        sanitize_frontend_files(files)

        job = await self.database.get_job(job_id)
        if not job:
            return
        
        project_id = job["project_id"]
        project = await self.database.get_project(project_id)
        
        # Save version
        version_number = project.get("current_version", 0) + 1
        
        version_data = {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "version_number": version_number,
            "prompt": prompt,
            "files": files,
            "status": "partial" if partial else "success",
            "requirements": requirements,
            "remaining_issues": remaining_issues or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await self.database.create_version(version_data)
        await self.database.update_project(project_id, {
            "current_version": version_number,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Save assistant message
        status_text = "partial success" if partial else "success"
        issues_text = f" ({len(remaining_issues or [])} issues remain)" if partial else ""
        
        await self.database.create_message({
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "role": "assistant",
            "content": f"Built version {version_number} with {len(files)} files.{issues_text}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Update job as completed
        await self._update_job(job_id, {
            "status": JobStatus.COMPLETED,
            "current_step": JobStep.DONE,
            "progress": 100,
            "files": files,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "version_number": version_number,
        })
        
        logger.info(f"Job {job_id} completed ({status_text}). Version {version_number} saved with {len(files)} files")

        # Save to memory so future builds learn from this outcome
        try:
            from agents.memory import BuildMemory
            memory = self._get_memory()
            if memory:
                total_tests = job.get("test_results", {}).get("total", 0)
                passed_tests = job.get("test_results", {}).get("passed", 0)
                test_score = (passed_tests / total_tests) if total_tests > 0 else 1.0
                build_record = BuildMemory(
                    project_id=project_id,
                    prompt=prompt[:500],
                    app_type=job.get("step_results", {}).get("thinking", {}).get("app_type", "general"),
                    features=job.get("step_results", {}).get("thinking", {}).get("essential_features", []),
                    files_generated=[f.get("path", "") for f in files],
                    test_score=test_score,
                    fix_attempts=job.get("fix_attempts", 0),
                    outcome="partial" if partial else "success",
                    patterns_used=job.get("step_results", {}).get("thinking", {}).get("patterns_to_apply", []),
                    lessons=(
                        f"Generated {len(files)} files. "
                        f"Tests: {passed_tests}/{total_tests}. "
                        f"Fix attempts: {job.get('fix_attempts', 0)}."
                    ),
                )
                await memory.save_build(build_record)
                await memory.add_project_event(
                    project_id, "build_completed",
                    f"v{version_number} — {len(files)} files, score {int(test_score*100)}%"
                )
                logger.info(f"Job {job_id}: Build outcome saved to memory")
        except Exception as e:
            logger.warning(f"Job {job_id}: Could not save to memory (non-fatal): {e}")
    
    async def _fail_job(self, job_id: str, error: str):
        """Mark job as failed"""
        await self._update_job(job_id, {
            "status": JobStatus.FAILED,
            "error": error,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(f"Job {job_id} failed: {error}")
    
    async def _update_job(self, job_id: str, updates: Dict):
        """Update job data in database"""
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.database.update_job(job_id, updates)
    
    async def resume_incomplete_jobs(self):
        """Resume any jobs that were interrupted (called on server startup)"""
        
        try:
            # Find all jobs that were running but not completed
            incomplete_jobs = await self.database.get_incomplete_jobs()
            
            for job in incomplete_jobs:
                job_id = job["id"]
                logger.info(f"Resuming interrupted job {job_id}")
                await self.start_job(job_id)
                
        except Exception as e:
            logger.error(f"Error resuming incomplete jobs: {e}")


# Singleton instance (initialized in server startup)
job_manager: Optional[JobManager] = None


def get_job_manager() -> Optional[JobManager]:
    return job_manager


def init_job_manager(database, orchestrator) -> JobManager:
    global job_manager
    job_manager = JobManager(database, orchestrator)
    return job_manager
