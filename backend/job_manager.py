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


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARSING_REQUIREMENTS = "parsing_requirements"
    AWAITING_CLARIFICATION = "awaiting_clarification"
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
    GENERATE = "generate"
    DEPLOY = "deploy"
    TEST = "test"
    FIX = "fix"
    SAVE = "save"
    DONE = "done"


class JobManager:
    """
    Manages async generation jobs that persist independently of browser sessions.
    Uses the new Orchestrator v2 architecture.
    """
    
    def __init__(self, database, orchestrator):
        self.database = database
        self.orchestrator = orchestrator
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._job_locks: Dict[str, asyncio.Lock] = {}
        self._cancelled_jobs: set = set()
        
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
            "max_fix_attempts": 3,
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
        4. Tester Agent: Conversational testing
        5. Fix Agent: Fix issues (max 3 retries)
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
        max_fix_attempts = job.get("max_fix_attempts", 3)
        
        # ==================== STEP 1: REQUIREMENTS ====================
        if not requirements or not requirements.get("is_complete"):
            await self._update_job(job_id, {
                "current_step": JobStep.REQUIREMENTS,
                "status": JobStatus.PARSING_REQUIREMENTS,
                "progress": 10,
            })
            
            try:
                logger.info(f"Job {job_id}: Parsing requirements")
                requirements = await self.orchestrator.parse_requirements(prompt, requirements)
                
                # For async jobs, auto-confirm requirements (skip clarification)
                if requirements.get("ambiguities"):
                    # Auto-resolve ambiguities with defaults
                    for amb in requirements.get("ambiguities", []):
                        amb["resolved"] = True
                        amb["answer"] = amb.get("default") or amb.get("options", [""])[0]
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
        
        # ==================== STEP 2: CODE GENERATION ====================
        await self._update_job(job_id, {
            "current_step": JobStep.GENERATE,
            "status": JobStatus.GENERATING,
            "progress": 20,
        })
        
        try:
            logger.info(f"Job {job_id}: Generating code")
            
            generation_result = await self.orchestrator.code_generation_agent.generate_code(
                requirements=requirements,
                supabase_config=supabase_config,
                existing_files=existing_files,
                is_update=is_update,
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
            
            logger.info(f"Job {job_id}: Generated {len(files)} files - proceeding to deploy")
            
        except Exception as e:
            logger.error(f"Job {job_id}: Code generation failed: {e}")
            import traceback
            traceback.print_exc()
            await self._fail_job(job_id, f"Code generation failed: {str(e)}")
            return
        
        # ==================== STEP 3-5: DEPLOY → TEST → FIX LOOP ====================
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
                "progress": 60 + (fix_attempts * 10),
            })
            
            try:
                logger.info(f"Job {job_id}: Running conversational tests")
                
                test_results = await self.orchestrator.tester_agent.run_tests(
                    files=files,
                    requirements=requirements,
                    supabase_config=supabase_config,
                )
                
                step_results[f"test_{fix_attempts}"] = {
                    "passed": test_results.get("passed", 0),
                    "failed": test_results.get("failed", 0),
                    "total": test_results.get("total", 0),
                }
                
                await self._update_job(job_id, {
                    "test_results": test_results,
                    "step_results": step_results,
                })
                
                logger.info(f"Job {job_id}: Tests - {test_results.get('passed')}/{test_results.get('total')} passed")
                
                # All tests passed!
                if test_results.get("failed", 0) == 0:
                    await self._complete_job(job_id, files, requirements, prompt)
                    return
                    
            except Exception as e:
                logger.error(f"Job {job_id}: Testing error: {e}")
                test_results = {"failed": 1, "passed": 0, "total": 1, "issues": [{"error": str(e)}]}
                step_results[f"test_{fix_attempts}"] = {"error": str(e)}
            
            # --- STEP 5: FIX (if tests failed and retries remain) ---
            if fix_attempts < max_fix_attempts:
                fix_attempts += 1
                
                await self._update_job(job_id, {
                    "current_step": JobStep.FIX,
                    "status": JobStatus.FIXING,
                    "fix_attempts": fix_attempts,
                    "progress": 70 + (fix_attempts * 5),
                })
                
                try:
                    logger.info(f"Job {job_id}: Fix attempt {fix_attempts}/{max_fix_attempts}")
                    
                    fix_result = await self.orchestrator.fix_agent.fix_issues(
                        files=files,
                        test_results=test_results,
                        requirements=requirements,
                        attempt=fix_attempts,
                    )
                    
                    if fix_result.get("fixes_applied"):
                        files = fix_result.get("files", files)
                        step_results[f"fix_{fix_attempts}"] = {
                            "fixes_count": len(fix_result.get("fixes_applied", [])),
                            "files_modified": fix_result.get("files_modified", []),
                        }
                        await self._update_job(job_id, {
                            "files": files,
                            "step_results": step_results,
                        })
                        logger.info(f"Job {job_id}: Applied {len(fix_result.get('fixes_applied', []))} fixes")
                    else:
                        step_results[f"fix_{fix_attempts}"] = {"status": "no_changes"}
                        logger.warning(f"Job {job_id}: No fixes could be applied")
                        
                except Exception as e:
                    logger.error(f"Job {job_id}: Fix error: {e}")
                    step_results[f"fix_{fix_attempts}"] = {"status": "error", "error": str(e)}
            else:
                # Max retries reached - complete with partial success
                logger.warning(f"Job {job_id}: Max fix attempts reached")
                await self._complete_job(
                    job_id, files, requirements, prompt,
                    partial=True,
                    remaining_issues=test_results.get("issues", [])
                )
                return
    
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
