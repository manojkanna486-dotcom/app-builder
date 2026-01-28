"""
Database abstraction layer supporting MongoDB and Supabase PostgreSQL.
Set DB_TYPE=supabase in .env to use PostgreSQL, otherwise uses MongoDB.
"""
import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import json

logger = logging.getLogger(__name__)

# Database type from environment
DB_TYPE = os.environ.get('DB_TYPE', 'mongodb')  # 'mongodb' or 'supabase'


class DatabaseInterface:
    """Abstract database interface"""
    
    async def init(self):
        """Initialize database connection"""
        raise NotImplementedError
    
    async def close(self):
        """Close database connection"""
        raise NotImplementedError
    
    # Projects
    async def create_project(self, project: dict) -> dict:
        raise NotImplementedError
    
    async def get_projects(self) -> List[dict]:
        raise NotImplementedError
    
    async def get_project(self, project_id: str) -> Optional[dict]:
        raise NotImplementedError
    
    async def update_project(self, project_id: str, updates: dict) -> bool:
        raise NotImplementedError
    
    async def delete_project(self, project_id: str) -> bool:
        raise NotImplementedError
    
    # Versions
    async def create_version(self, version: dict) -> dict:
        raise NotImplementedError
    
    async def get_versions(self, project_id: str) -> List[dict]:
        raise NotImplementedError
    
    async def get_latest_version(self, project_id: str) -> Optional[dict]:
        raise NotImplementedError
    
    # Messages
    async def create_message(self, message: dict) -> dict:
        raise NotImplementedError
    
    async def get_messages(self, project_id: str) -> List[dict]:
        raise NotImplementedError
    
    async def delete_project_data(self, project_id: str) -> bool:
        raise NotImplementedError
    
    # OAuth Token Storage (optional - only needed for Supabase OAuth)
    async def store_oauth_token(self, token_state: str, token_data: dict) -> bool:
        raise NotImplementedError
    
    async def get_oauth_token(self, token_state: str) -> Optional[dict]:
        raise NotImplementedError
    
    async def delete_oauth_token(self, token_state: str) -> bool:
        raise NotImplementedError


class MongoDatabase(DatabaseInterface):
    """MongoDB implementation"""
    
    def __init__(self, mongo_url: str, db_name: str):
        from motor.motor_asyncio import AsyncIOMotorClient
        self.client = AsyncIOMotorClient(mongo_url)
        self.db = self.client[db_name]
    
    async def init(self):
        logger.info("MongoDB connection initialized")
    
    async def close(self):
        self.client.close()
    
    async def create_project(self, project: dict) -> dict:
        await self.db.projects.insert_one(project)
        return project
    
    async def get_projects(self) -> List[dict]:
        return await self.db.projects.find({}, {"_id": 0}).to_list(100)
    
    async def get_project(self, project_id: str) -> Optional[dict]:
        return await self.db.projects.find_one({"id": project_id}, {"_id": 0})
    
    async def update_project(self, project_id: str, updates: dict) -> bool:
        result = await self.db.projects.update_one({"id": project_id}, {"$set": updates})
        return result.modified_count > 0
    
    async def delete_project(self, project_id: str) -> bool:
        result = await self.db.projects.delete_one({"id": project_id})
        return result.deleted_count > 0
    
    async def create_version(self, version: dict) -> dict:
        await self.db.versions.insert_one(version)
        return version
    
    async def get_versions(self, project_id: str) -> List[dict]:
        return await self.db.versions.find(
            {"project_id": project_id}, {"_id": 0}
        ).sort("version_number", -1).to_list(100)
    
    async def get_latest_version(self, project_id: str) -> Optional[dict]:
        return await self.db.versions.find_one(
            {"project_id": project_id, "status": "success"},
            {"_id": 0},
            sort=[("version_number", -1)]
        )
    
    async def create_message(self, message: dict) -> dict:
        await self.db.chat_messages.insert_one(message)
        return message
    
    async def get_messages(self, project_id: str) -> List[dict]:
        return await self.db.chat_messages.find(
            {"project_id": project_id}, {"_id": 0}
        ).sort("created_at", 1).to_list(1000)
    
    async def delete_project_data(self, project_id: str) -> bool:
        await self.db.versions.delete_many({"project_id": project_id})
        await self.db.chat_messages.delete_many({"project_id": project_id})
        return True
    
    # OAuth Token Storage
    async def store_oauth_token(self, token_state: str, token_data: dict) -> bool:
        """Store OAuth token data with TTL"""
        token_data["token_state"] = token_state
        token_data["created_at"] = datetime.now(timezone.utc).isoformat()
        await self.db.oauth_tokens.update_one(
            {"token_state": token_state},
            {"$set": token_data},
            upsert=True
        )
        return True
    
    async def get_oauth_token(self, token_state: str) -> Optional[dict]:
        """Retrieve OAuth token data"""
        return await self.db.oauth_tokens.find_one({"token_state": token_state}, {"_id": 0})
    
    async def delete_oauth_token(self, token_state: str) -> bool:
        """Delete OAuth token after use"""
        result = await self.db.oauth_tokens.delete_one({"token_state": token_state})
        return result.deleted_count > 0
    
    async def cleanup_expired_tokens(self, max_age_hours: int = 24) -> int:
        """Clean up expired OAuth tokens"""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        result = await self.db.oauth_tokens.delete_many({"created_at": {"$lt": cutoff}})
        return result.deleted_count


class SupabaseDatabase(DatabaseInterface):
    """
    Supabase PostgreSQL implementation using asyncpg.
    
    IMPORTANT: Use Transaction Pooler connection string (port 6543), NOT Direct Connection (5432).
    Get it from: Supabase Dashboard -> Project -> Connect -> Transaction Pooler
    
    Example: postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
    """
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = None
    
    async def init(self):
        import asyncpg
        
        # Parse URL and handle password with special characters
        self.pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        
        # Create tables if not exist
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR(255) PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    current_version INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS versions (
                    id VARCHAR(255) PRIMARY KEY,
                    project_id VARCHAR(255) REFERENCES projects(id) ON DELETE CASCADE,
                    version_number INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    delta_plan JSONB DEFAULT '{}',
                    files JSONB DEFAULT '[]',
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id VARCHAR(255) PRIMARY KEY,
                    project_id VARCHAR(255) REFERENCES projects(id) ON DELETE CASCADE,
                    role VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            ''')
            
            # Create indexes
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_versions_project_id ON versions(project_id)
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_project_id ON chat_messages(project_id)
            ''')
        
        logger.info("Supabase PostgreSQL connection initialized")
    
    async def close(self):
        if self.pool:
            await self.pool.close()
    
    async def create_project(self, project: dict) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO projects (id, name, description, summary, current_version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            ''', project['id'], project['name'], project.get('description', ''),
                project.get('summary', ''), project.get('current_version', 0),
                project.get('created_at', datetime.now(timezone.utc).isoformat()),
                project.get('updated_at', datetime.now(timezone.utc).isoformat()))
        return project
    
    async def get_projects(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT * FROM projects ORDER BY updated_at DESC LIMIT 100')
            return [dict(row) for row in rows]
    
    async def get_project(self, project_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM projects WHERE id = $1', project_id)
            return dict(row) if row else None
    
    async def update_project(self, project_id: str, updates: dict) -> bool:
        set_clauses = []
        values = []
        for i, (key, value) in enumerate(updates.items(), 1):
            set_clauses.append(f"{key} = ${i}")
            values.append(value)
        values.append(project_id)
        
        query = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = ${len(values)}"
        
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, *values)
            return 'UPDATE' in result
    
    async def delete_project(self, project_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute('DELETE FROM projects WHERE id = $1', project_id)
            return 'DELETE' in result
    
    async def create_version(self, version: dict) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO versions (id, project_id, version_number, prompt, delta_plan, files, status, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ''', version['id'], version['project_id'], version['version_number'],
                version['prompt'], json.dumps(version.get('delta_plan', {})),
                json.dumps(version.get('files', [])), version.get('status', 'pending'),
                version.get('created_at', datetime.now(timezone.utc).isoformat()))
        return version
    
    async def get_versions(self, project_id: str) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM versions WHERE project_id = $1 ORDER BY version_number DESC LIMIT 100
            ''', project_id)
            result = []
            for row in rows:
                d = dict(row)
                d['delta_plan'] = json.loads(d['delta_plan']) if d['delta_plan'] else {}
                d['files'] = json.loads(d['files']) if d['files'] else []
                result.append(d)
            return result
    
    async def get_latest_version(self, project_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM versions 
                WHERE project_id = $1 AND status = 'success'
                ORDER BY version_number DESC LIMIT 1
            ''', project_id)
            if row:
                d = dict(row)
                d['delta_plan'] = json.loads(d['delta_plan']) if d['delta_plan'] else {}
                d['files'] = json.loads(d['files']) if d['files'] else []
                return d
            return None
    
    async def create_message(self, message: dict) -> dict:
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO chat_messages (id, project_id, role, content, created_at)
                VALUES ($1, $2, $3, $4, $5)
            ''', message['id'], message['project_id'], message['role'],
                message['content'], message.get('created_at', datetime.now(timezone.utc).isoformat()))
        return message
    
    async def get_messages(self, project_id: str) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT * FROM chat_messages WHERE project_id = $1 ORDER BY created_at ASC LIMIT 1000
            ''', project_id)
            return [dict(row) for row in rows]
    
    async def delete_project_data(self, project_id: str) -> bool:
        # CASCADE will handle versions and messages
        return True


def get_database() -> DatabaseInterface:
    """Factory function to get the appropriate database instance"""
    db_type = os.environ.get('DB_TYPE', 'mongodb')
    
    if db_type == 'supabase':
        database_url = os.environ.get('SUPABASE_DB_URL')
        if not database_url:
            raise ValueError("SUPABASE_DB_URL environment variable is required for Supabase")
        return SupabaseDatabase(database_url)
    else:
        mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
        db_name = os.environ.get('DB_NAME', 'test_database')
        return MongoDatabase(mongo_url, db_name)
