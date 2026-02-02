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
        
        supabase_url = supabase_config.get("url")
        service_key = supabase_config.get("service_key")
        project_ref = supabase_config.get("project_ref")
        
        if not supabase_url:
            result["status"] = "error"
            result["errors"].append("No Supabase URL configured")
            return result
        
        # Separate migration files and edge functions
        migration_files = [f for f in files if f.get("file_type") == "sql"]
        edge_function_files = [f for f in files if f.get("file_type") == "edge_function"]
        
        # Run migrations using service role key (direct SQL execution)
        if migration_files:
            if service_key:
                migration_result = await self._run_migrations_direct(
                    supabase_url, 
                    service_key, 
                    migration_files
                )
            elif access_token and project_ref:
                # Fallback to Management API if OAuth available
                migration_result = await self._run_migrations_management_api(
                    project_ref, 
                    access_token, 
                    migration_files
                )
            else:
                migration_result = {
                    "executed": [],
                    "errors": [{"path": "all", "error": "No service key or OAuth token available for migrations"}]
                }
            
            result["migrations"] = migration_result.get("executed", [])
            if migration_result.get("errors"):
                result["errors"].extend(migration_result["errors"])
        
        # Deploy Edge Functions (requires Management API / OAuth)
        if edge_function_files and access_token and project_ref:
            deploy_result = await self._deploy_edge_functions(
                project_ref,
                access_token,
                edge_function_files
            )
            result["edge_functions"] = deploy_result.get("deployed", [])
            if deploy_result.get("errors"):
                result["errors"].extend(deploy_result["errors"])
        elif edge_function_files:
            result["errors"].append({
                "path": "edge_functions",
                "error": "Edge Function deployment requires OAuth connection"
            })
        
        if result["errors"]:
            result["status"] = "partial" if result["migrations"] or result["edge_functions"] else "error"
        
        return result
    
    async def _run_migrations_direct(
        self, 
        supabase_url: str, 
        service_key: str, 
        migration_files: List[Dict]
    ) -> Dict:
        """Execute SQL migrations directly via Supabase REST API using service role key"""
        
        result = {
            "executed": [],
            "errors": []
        }
        
        # Sort migrations by filename
        sorted_migrations = sorted(migration_files, key=lambda f: f.get("path", ""))
        
        headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for migration in sorted_migrations:
                sql = migration.get("content", "")
                path = migration.get("path", "unknown")
                
                if not sql.strip():
                    continue
                
                try:
                    # Execute SQL via Supabase's RPC endpoint
                    # First, try to use the pg_query function if available
                    # Otherwise, we'll need to execute statements one by one
                    
                    # Split SQL into individual statements
                    statements = self._split_sql_statements(sql)
                    
                    executed_count = 0
                    for stmt in statements:
                        stmt = stmt.strip()
                        if not stmt:
                            continue
                        
                        # Try to execute via rpc call
                        response = await client.post(
                            f"{supabase_url}/rest/v1/rpc/exec_sql",
                            headers=headers,
                            json={"query": stmt}
                        )
                        
                        if response.status_code == 404:
                            # exec_sql function doesn't exist, try direct approach
                            # For CREATE TABLE, we can't use REST API directly
                            # Log and continue - the table creation will be handled differently
                            logger.warning(f"exec_sql not available, migration may need manual execution: {path}")
                            result["errors"].append({
                                "path": path,
                                "error": "Direct SQL execution not available. Please run migration manually in Supabase Dashboard."
                            })
                            break
                        elif response.status_code in [200, 201, 204]:
                            executed_count += 1
                        else:
                            error_text = response.text
                            try:
                                error_data = response.json()
                                error_text = error_data.get("message", error_text)
                            except:
                                pass
                            
                            # Check if it's a "already exists" error - that's OK
                            if "already exists" in error_text.lower():
                                logger.info(f"Migration {path}: Object already exists (OK)")
                                executed_count += 1
                            else:
                                result["errors"].append({
                                    "path": path,
                                    "error": error_text
                                })
                    
                    if executed_count > 0:
                        result["executed"].append({
                            "path": path,
                            "status": "success",
                            "statements": executed_count
                        })
                        logger.info(f"Migration executed: {path} ({executed_count} statements)")
                        
                except Exception as e:
                    result["errors"].append({
                        "path": path,
                        "error": str(e)
                    })
                    logger.error(f"Migration exception: {path} - {e}")
        
        return result
    
    def _split_sql_statements(self, sql: str) -> List[str]:
        """Split SQL into individual statements"""
        # Simple split by semicolon, but handle edge cases
        statements = []
        current = ""
        in_string = False
        string_char = None
        
        for char in sql:
            if char in ("'", '"') and not in_string:
                in_string = True
                string_char = char
            elif char == string_char and in_string:
                in_string = False
                string_char = None
            
            if char == ';' and not in_string:
                if current.strip():
                    statements.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            statements.append(current.strip())
        
        return statements
    
    async def _run_migrations_management_api(
        self, 
        project_ref: str, 
        access_token: str, 
        migration_files: List[Dict]
    ) -> Dict:
        """Execute SQL migrations via Supabase Management API (OAuth required)"""
        
        result = {
            "executed": [],
            "errors": []
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        sorted_migrations = sorted(migration_files, key=lambda f: f.get("path", ""))
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for migration in sorted_migrations:
                sql = migration.get("content", "")
                path = migration.get("path", "unknown")
                
                if not sql.strip():
                    continue
                
                try:
                    response = await client.post(
                        f"{self.management_api}/projects/{project_ref}/database/query",
                        headers=headers,
                        json={"query": sql}
                    )
                    
                    if response.status_code in [200, 201]:
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
