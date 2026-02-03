"""
Async Job Manager - Runs generation jobs independently of browser sessions

Key Features:
1. Jobs run independently of any browser or UI session
2. Jobs continue execution until completed or explicitly canceled
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
    CLARIFYING = "clarifying"
    GENERATING = "generating"
    DEPLOYING = "deploying"
    TESTING = "testing"
    FIXING = "fixing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStep(str, Enum):
    INIT = "init"
    CLARIFY = "clarify"
    GENERATE = "generate"
    DEPLOY = "deploy"
    TEST = "test"
    FIX = "fix"
    SAVE = "save"
    DONE = "done"


class JobManager:
    """
    Manages async generation jobs that persist independently of browser sessions.
    """
    
    def __init__(self, database, orchestrator):
        self.database = database
        self.orchestrator = orchestrator
        self._running_jobs: Dict[str, asyncio.Task] = {}
        self._job_locks: Dict[str, asyncio.Lock] = {}
        
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
        
        if job_id in self._running_jobs:
            self._running_jobs[job_id].cancel()
            
        await self._update_job(job_id, {
            "status": JobStatus.CANCELED,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        
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
            
            # Resume from last step if recovering from failure
            current_step = job.get("current_step", JobStep.INIT)
            
            # Execute the pipeline
            await self._execute_pipeline(job_id, job, project, current_step)
            
        except asyncio.CancelledError:
            logger.info(f"Job {job_id} was canceled")
            await self._update_job(job_id, {"status": JobStatus.CANCELED})
        except Exception as e:
            logger.error(f"Job {job_id} failed with error: {e}")
            await self._fail_job(job_id, str(e))
    
    async def _execute_pipeline(
        self,
        job_id: str,
        job: Dict,
        project: Dict,
        start_step: str = JobStep.INIT
    ):
        """Execute the full generation pipeline with persistence at each step"""
        
        project_id = job["project_id"]
        prompt = job["prompt"]
        requirements = job.get("requirements")
        supabase_config = job.get("supabase_config") or {
            "url": project.get("supabase_url"),
            "anon_key": project.get("supabase_anon_key"),
            "service_key": project.get("supabase_service_key"),
            "project_ref": project.get("supabase_project_ref"),
        }
        
        # Get access token for Supabase operations
        access_token = supabase_config.get("service_key")
        
        files = job.get("files", [])
        fix_attempts = job.get("fix_attempts", 0)
        max_fix_attempts = job.get("max_fix_attempts", 3)
        step_results = job.get("step_results", {})
        
        # Step 1: Clarify (if needed)
        if start_step in [JobStep.INIT, JobStep.CLARIFY]:
            await self._update_job(job_id, {
                "current_step": JobStep.CLARIFY,
                "status": JobStatus.CLARIFYING,
                "progress": 10,
            })
            
            try:
                if not requirements:
                    requirements = await self.orchestrator.analyze_prompt(
                        prompt,
                        {
                            "supabase_connected": True,
                            "supabase_url": supabase_config.get("url", ""),
                            "project_name": project.get("name", ""),
                        }
                    )
                    requirements["is_clear"] = True  # Auto-confirm for async jobs
                
                step_results["clarify"] = {"success": True, "requirements": requirements}
                await self._update_job(job_id, {
                    "requirements": requirements,
                    "step_results": step_results,
                })
                
            except Exception as e:
                await self._fail_job(job_id, f"Clarification failed: {str(e)}")
                return
        
        # Step 2: Generate Code
        if start_step in [JobStep.INIT, JobStep.CLARIFY, JobStep.GENERATE]:
            await self._update_job(job_id, {
                "current_step": JobStep.GENERATE,
                "status": JobStatus.GENERATING,
                "progress": 20,
            })
            
            try:
                # Check for existing files (for updates)
                existing_files = None
                is_update = project.get("current_version", 0) > 0
                if is_update:
                    latest_version = await self.database.get_latest_version(project_id)
                    if latest_version:
                        existing_files = latest_version.get("files", [])
                
                # Generate code
                generation_result = await self.orchestrator.code_generation_agent.generate_code(
                    requirements=requirements,
                    supabase_config=supabase_config,
                    existing_files=existing_files,
                    is_update=is_update,
                )
                
                files = generation_result.get("files", [])
                
                step_results["generate"] = {
                    "success": True,
                    "files_count": len(files),
                    "summary": generation_result.get("summary", ""),
                }
                
                await self._update_job(job_id, {
                    "files": files,
                    "step_results": step_results,
                    "progress": 40,
                })
                
            except Exception as e:
                await self._fail_job(job_id, f"Code generation failed: {str(e)}")
                return
        
        # Pipeline loop: Deploy → Test → Fix
        while fix_attempts <= max_fix_attempts:
            
            # Step 3: Deploy
            await self._update_job(job_id, {
                "current_step": JobStep.DEPLOY,
                "status": JobStatus.DEPLOYING,
                "progress": 50 + (fix_attempts * 10),
            })
            
            try:
                deploy_result = await self.orchestrator.deployment_agent.deploy(
                    files=files,
                    supabase_config=supabase_config,
                    access_token=access_token,
                )
                
                step_results["deploy"] = deploy_result
                await self._update_job(job_id, {"step_results": step_results})
                
            except Exception as e:
                logger.warning(f"Deployment failed: {e}, continuing to testing...")
                step_results["deploy"] = {"status": "error", "error": str(e)}
            
            # Step 4: Test
            await self._update_job(job_id, {
                "current_step": JobStep.TEST,
                "status": JobStatus.TESTING,
                "progress": 60 + (fix_attempts * 10),
            })
            
            try:
                test_results = await self.orchestrator.testing_agent.run_tests(
                    files=files,
                    requirements=requirements,
                    supabase_config=supabase_config,
                )
                
                step_results["test"] = test_results
                await self._update_job(job_id, {"step_results": step_results})
                
                # Check if all tests passed
                if test_results.get("failed", 0) == 0:
                    # Success! Save and complete
                    await self._complete_job(job_id, files, requirements, prompt)
                    return
                
            except Exception as e:
                logger.error(f"Testing failed: {e}")
                test_results = {"failed": 1, "issues": [{"error": str(e)}]}
                step_results["test"] = test_results
            
            # Step 5: Fix (if tests failed and we have retries left)
            if fix_attempts < max_fix_attempts:
                fix_attempts += 1
                
                await self._update_job(job_id, {
                    "current_step": JobStep.FIX,
                    "status": JobStatus.FIXING,
                    "fix_attempts": fix_attempts,
                    "progress": 70 + (fix_attempts * 5),
                })
                
                try:
                    fix_result = await self.orchestrator.dev_agent.fix_issues(
                        files=files,
                        test_results=test_results,
                        requirements=requirements,
                        attempt=fix_attempts,
                    )
                    
                    if fix_result.get("fixes_applied"):
                        files = fix_result.get("files", files)
                        step_results[f"fix_{fix_attempts}"] = fix_result
                        await self._update_job(job_id, {
                            "files": files,
                            "step_results": step_results,
                        })
                    else:
                        step_results[f"fix_{fix_attempts}"] = {"status": "no_changes"}
                        
                except Exception as e:
                    logger.error(f"Fix attempt {fix_attempts} failed: {e}")
                    step_results[f"fix_{fix_attempts}"] = {"status": "error", "error": str(e)}
            else:
                # Max retries reached - complete with partial success
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
            "delta_plan": {
                "requirements": requirements,
                "remaining_issues": remaining_issues or [],
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        await self.database.create_version(version_data)
        await self.database.update_project(project_id, {
            "current_version": version_number,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        
        # Save assistant message
        await self.database.create_message({
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "role": "assistant",
            "content": f"Built version {version_number} with {len(files)} files." + (
                f" ({len(remaining_issues or [])} issues remain)" if partial else ""
            ),
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
        
        logger.info(f"Job {job_id} completed. Version {version_number} saved with {len(files)} files")
    
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
