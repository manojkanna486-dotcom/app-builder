"""
Deployment Agent - Handles Supabase migrations and Edge Function deployments
Runs SQL migrations and deploys functions to Supabase
"""

import json
import logging
from typing import Dict, List, Optional, Any
import httpx
import re

logger = logging.getLogger(__name__)

class DeploymentAgent:
    """Agent that deploys code to Supabase (migrations + Edge Functions)"""
    
    def __init__(self):
        self.management_api = "https://api.supabase.com/v1"
        
    async def deploy(
        self, 
        files: List[Dict],
        supabase_config: Dict,
        access_token: str
    ) -> Dict:
        """
        Deploy all backend components to Supabase.
        Returns deployment status and any errors.
        """
        
        result = {
            "status": "success",
            "migrations": [],
            "edge_functions": [],
            "errors": []
        }
        
        project_ref = supabase_config.get("project_ref")
        if not project_ref:
            result["status"] = "error"
            result["errors"].append("No Supabase project connected")
            return result
        
        # Separate migration files and edge functions
        migration_files = [f for f in files if f.get("file_type") == "sql"]
        edge_function_files = [f for f in files if f.get("file_type") == "edge_function"]
        
        # Run migrations first
        if migration_files:
            migration_result = await self._run_migrations(
                project_ref, 
                access_token, 
                migration_files
            )
            result["migrations"] = migration_result.get("executed", [])
            if migration_result.get("errors"):
                result["errors"].extend(migration_result["errors"])
        
        # Deploy Edge Functions
        if edge_function_files:
            deploy_result = await self._deploy_edge_functions(
                project_ref,
                access_token,
                edge_function_files
            )
            result["edge_functions"] = deploy_result.get("deployed", [])
            if deploy_result.get("errors"):
                result["errors"].extend(deploy_result["errors"])
        
        if result["errors"]:
            result["status"] = "partial" if result["migrations"] or result["edge_functions"] else "error"
        
        return result
    
    async def _run_migrations(
        self, 
        project_ref: str, 
        access_token: str, 
        migration_files: List[Dict]
    ) -> Dict:
        """Execute SQL migrations on Supabase"""
        
        result = {
            "executed": [],
            "errors": []
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Sort migrations by filename (they should be timestamped)
        sorted_migrations = sorted(migration_files, key=lambda f: f.get("path", ""))
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for migration in sorted_migrations:
                sql = migration.get("content", "")
                path = migration.get("path", "unknown")
                
                if not sql.strip():
                    continue
                
                try:
                    # Execute SQL via Supabase Management API
                    response = await client.post(
                        f"{self.management_api}/projects/{project_ref}/database/query",
                        headers=headers,
                        json={"query": sql}
                    )
                    
                    if response.status_code == 200 or response.status_code == 201:
                        result["executed"].append({
                            "path": path,
                            "status": "success"
                        })
                        logger.info(f"Migration executed: {path}")
                    else:
                        error_msg = response.text
                        try:
                            error_data = response.json()
                            error_msg = error_data.get("message", error_msg)
                        except:
                            pass
                        
                        result["errors"].append({
                            "path": path,
                            "error": error_msg
                        })
                        logger.error(f"Migration failed: {path} - {error_msg}")
                        
                except Exception as e:
                    result["errors"].append({
                        "path": path,
                        "error": str(e)
                    })
                    logger.error(f"Migration exception: {path} - {e}")
        
        return result
    
    async def _deploy_edge_functions(
        self, 
        project_ref: str,
        access_token: str,
        function_files: List[Dict]
    ) -> Dict:
        """Deploy Edge Functions to Supabase"""
        
        result = {
            "deployed": [],
            "errors": []
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Group files by function name
        functions = {}
        for f in function_files:
            path = f.get("path", "")
            # Extract function name from path like "supabase/functions/my-function/index.ts"
            match = re.search(r'functions/([^/]+)/', path)
            if match:
                func_name = match.group(1)
                if func_name not in functions:
                    functions[func_name] = []
                functions[func_name].append(f)
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            for func_name, files in functions.items():
                try:
                    # Find the main entry file (index.ts)
                    entry_file = next(
                        (f for f in files if f["path"].endswith("index.ts")),
                        files[0] if files else None
                    )
                    
                    if not entry_file:
                        continue
                    
                    # Deploy the function
                    response = await client.post(
                        f"{self.management_api}/projects/{project_ref}/functions",
                        headers=headers,
                        json={
                            "name": func_name,
                            "body": entry_file.get("content", ""),
                            "verify_jwt": True
                        }
                    )
                    
                    if response.status_code in [200, 201]:
                        result["deployed"].append({
                            "name": func_name,
                            "status": "deployed"
                        })
                        logger.info(f"Edge Function deployed: {func_name}")
                    elif response.status_code == 409:
                        # Function exists, try to update
                        update_response = await client.patch(
                            f"{self.management_api}/projects/{project_ref}/functions/{func_name}",
                            headers=headers,
                            json={"body": entry_file.get("content", "")}
                        )
                        
                        if update_response.status_code in [200, 201]:
                            result["deployed"].append({
                                "name": func_name,
                                "status": "updated"
                            })
                            logger.info(f"Edge Function updated: {func_name}")
                        else:
                            result["errors"].append({
                                "name": func_name,
                                "error": update_response.text
                            })
                    else:
                        result["errors"].append({
                            "name": func_name,
                            "error": response.text
                        })
                        
                except Exception as e:
                    result["errors"].append({
                        "name": func_name,
                        "error": str(e)
                    })
                    logger.error(f"Edge Function deployment error: {func_name} - {e}")
        
        return result
    
    async def verify_deployment(
        self,
        project_ref: str,
        access_token: str,
        expected_tables: List[str],
        expected_functions: List[str]
    ) -> Dict:
        """Verify that deployment was successful"""
        
        result = {
            "tables_verified": [],
            "tables_missing": [],
            "functions_verified": [],
            "functions_missing": []
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check tables
            try:
                response = await client.get(
                    f"{self.management_api}/projects/{project_ref}/database/tables",
                    headers=headers
                )
                
                if response.status_code == 200:
                    existing_tables = [t["name"] for t in response.json()]
                    for table in expected_tables:
                        if table in existing_tables:
                            result["tables_verified"].append(table)
                        else:
                            result["tables_missing"].append(table)
            except Exception as e:
                logger.error(f"Table verification error: {e}")
            
            # Check functions
            try:
                response = await client.get(
                    f"{self.management_api}/projects/{project_ref}/functions",
                    headers=headers
                )
                
                if response.status_code == 200:
                    existing_funcs = [f["name"] for f in response.json()]
                    for func in expected_functions:
                        if func in existing_funcs:
                            result["functions_verified"].append(func)
                        else:
                            result["functions_missing"].append(func)
            except Exception as e:
                logger.error(f"Function verification error: {e}")
        
        return result
