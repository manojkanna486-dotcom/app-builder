"""
Deployment Agent - Handles Supabase migrations and Edge Function deployments
Runs SQL migrations directly via PostgreSQL connection
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Any
import httpx

logger = logging.getLogger(__name__)

class DeploymentAgent:
    """Agent that deploys code to Supabase (migrations + Edge Functions)"""
    
    def __init__(self):
        self.management_api = "https://api.supabase.com/v1"
        
    async def deploy(
        self, 
        files: List[Dict],
        supabase_config: Dict,
        access_token: str = None
    ) -> Dict:
        """
        Deploy all backend components to Supabase.
        Returns deployment status and any errors.
        """
        
        result = {
            "status": "success",
            "migrations": [],
            "edge_functions": [],
            "errors": [],
            "tables_created": []
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
        
        # Run migrations using direct PostgreSQL connection
        if migration_files:
            migration_result = await self._run_migrations_postgres(
                project_ref or self._extract_project_ref(supabase_url),
                migration_files
            )
            result["migrations"] = migration_result.get("executed", [])
            result["tables_created"] = migration_result.get("tables_created", [])
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
            logger.info("Edge Function deployment skipped - requires OAuth connection")
        
        if result["errors"]:
            result["status"] = "partial" if result["migrations"] or result["edge_functions"] else "error"
        
        logger.info(f"Deployment complete: {len(result['tables_created'])} tables created, {len(result['migrations'])} migrations run")
        
        return result
    
    def _extract_project_ref(self, supabase_url: str) -> Optional[str]:
        """Extract project reference from Supabase URL"""
        if not supabase_url:
            return None
        match = re.search(r'https://([a-z]+)\.supabase\.co', supabase_url)
        if match:
            return match.group(1)
        return None
    
    async def _run_migrations_postgres(
        self,
        project_ref: str,
        migration_files: List[Dict]
    ) -> Dict:
        """Execute SQL migrations directly via PostgreSQL connection"""
        
        result = {
            "executed": [],
            "errors": [],
            "tables_created": []
        }
        
        try:
            import asyncpg
        except ImportError:
            logger.error("asyncpg not installed")
            result["errors"].append({"path": "all", "error": "asyncpg library not installed"})
            return result
        
        # Get database password from environment
        db_password = os.environ.get("SUPABASE_DB_PASSWORD", "")
        
        if not db_password:
            # Try to get from the project's stored config (for user's projects)
            logger.warning("No SUPABASE_DB_PASSWORD in environment, migrations may fail")
        
        # Build connection string for pooler (transaction mode)
        # Format: postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
        conn_str = f"postgresql://postgres.{project_ref}:{db_password}@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
        
        # Sort migrations by filename to ensure correct order
        sorted_migrations = sorted(migration_files, key=lambda f: f.get("path", ""))
        
        try:
            conn = await asyncpg.connect(conn_str, timeout=30)
            logger.info(f"Connected to Supabase database for migrations")
            
            for migration in sorted_migrations:
                sql = migration.get("content", "")
                path = migration.get("path", "unknown")
                
                if not sql.strip():
                    continue
                
                logger.info(f"Executing migration: {path}")
                
                try:
                    # Execute the full SQL content
                    await conn.execute(sql)
                    
                    result["executed"].append({
                        "path": path,
                        "status": "success"
                    })
                    
                    # Extract table names from CREATE TABLE statements
                    table_matches = re.findall(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)',
                        sql,
                        re.IGNORECASE
                    )
                    for table in table_matches:
                        if table not in result["tables_created"]:
                            result["tables_created"].append(table)
                    
                    logger.info(f"Migration {path} executed successfully")
                    
                except asyncpg.exceptions.DuplicateTableError as e:
                    logger.info(f"Table already exists for {path} (OK)")
                    result["executed"].append({
                        "path": path,
                        "status": "already_exists"
                    })
                except asyncpg.exceptions.DuplicateObjectError as e:
                    logger.info(f"Object already exists for {path} (OK)")
                    result["executed"].append({
                        "path": path,
                        "status": "already_exists"
                    })
                except Exception as e:
                    error_msg = str(e)
                    # "already exists" errors are OK
                    if "already exists" in error_msg.lower():
                        logger.info(f"Object already exists for {path} (OK)")
                        result["executed"].append({
                            "path": path,
                            "status": "already_exists"
                        })
                    else:
                        logger.error(f"Migration {path} failed: {e}")
                        result["errors"].append({
                            "path": path,
                            "error": error_msg
                        })
            
            await conn.close()
            
        except asyncpg.exceptions.InvalidPasswordError:
            result["errors"].append({
                "path": "connection",
                "error": "Invalid database password. Please check SUPABASE_DB_PASSWORD."
            })
        except asyncpg.exceptions.ConnectionDoesNotExistError:
            result["errors"].append({
                "path": "connection", 
                "error": "Could not connect to database. Check project_ref and network."
            })
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            result["errors"].append({
                "path": "connection",
                "error": f"Database connection failed: {str(e)}"
            })
        
        return result
    
    async def _deploy_edge_functions(
        self,
        project_ref: str,
        access_token: str,
        function_files: List[Dict]
    ) -> Dict:
        """Deploy Edge Functions via Supabase Management API"""
        
        result = {
            "deployed": [],
            "errors": []
        }
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            for func_file in function_files:
                path = func_file.get("path", "")
                content = func_file.get("content", "")
                
                # Extract function name from path (e.g., "supabase/functions/my-func/index.ts" -> "my-func")
                func_name_match = re.search(r'functions/([^/]+)/', path)
                if not func_name_match:
                    continue
                    
                func_name = func_name_match.group(1)
                
                try:
                    # Check if function exists
                    check_response = await client.get(
                        f"{self.management_api}/projects/{project_ref}/functions/{func_name}",
                        headers=headers
                    )
                    
                    if check_response.status_code == 200:
                        # Update existing function
                        response = await client.patch(
                            f"{self.management_api}/projects/{project_ref}/functions/{func_name}",
                            headers=headers,
                            json={"body": content}
                        )
                    else:
                        # Create new function
                        response = await client.post(
                            f"{self.management_api}/projects/{project_ref}/functions",
                            headers=headers,
                            json={
                                "slug": func_name,
                                "name": func_name,
                                "body": content,
                                "verify_jwt": True
                            }
                        )
                    
                    if response.status_code in [200, 201]:
                        result["deployed"].append({
                            "name": func_name,
                            "path": path,
                            "status": "deployed"
                        })
                        logger.info(f"Deployed Edge Function: {func_name}")
                    else:
                        error_text = response.text
                        try:
                            error_data = response.json()
                            error_text = error_data.get("message", error_text)
                        except:
                            pass
                        result["errors"].append({
                            "path": path,
                            "function": func_name,
                            "error": error_text
                        })
                        
                except Exception as e:
                    result["errors"].append({
                        "path": path,
                        "function": func_name,
                        "error": str(e)
                    })
        
        return result
    
    def _split_sql_statements(self, sql: str) -> List[str]:
        """Split SQL into individual statements"""
        # Simple split on semicolons, but keep DO blocks together
        statements = []
        current = []
        in_do_block = False
        
        for line in sql.split('\n'):
            stripped = line.strip().upper()
            
            if stripped.startswith('DO $$') or stripped.startswith('DO $'):
                in_do_block = True
            
            current.append(line)
            
            if in_do_block and ('$$;' in line or '$$ ;' in line):
                in_do_block = False
                statements.append('\n'.join(current))
                current = []
            elif not in_do_block and line.rstrip().endswith(';'):
                statements.append('\n'.join(current))
                current = []
        
        if current:
            statements.append('\n'.join(current))
        
        return [s.strip() for s in statements if s.strip()]
