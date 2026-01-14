"""Supabase database client and helpers."""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from supabase import create_client, Client
from .utils import get_logger

logger = get_logger(__name__)

class SupabaseClient:
    """Client for interacting with Supabase database."""
    
    def __init__(self):
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
        
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        
        self.client: Client = create_client(url, key)
        logger.info("Supabase client initialized")
    
    def poll_next_job(self, job_type: str = 'summarize', task: str = 'nlp_pack_v1') -> Optional[Dict]:
        """
        Poll for the next queued job with row-level locking to prevent race conditions.
        
        Uses PostgreSQL FOR UPDATE SKIP LOCKED to ensure only one worker gets each job.
        """
        try:
            # Use raw SQL for row-level locking (FOR UPDATE SKIP LOCKED)
            # This prevents multiple workers from grabbing the same job
            query = """
            SELECT *
            FROM pipeline_jobs
            WHERE status = 'queued'
              AND job_type = %s
              AND input->>'task' = %s
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
            
            # Execute via RPC if available, otherwise fallback
            try:
                result = self.client.rpc('exec_sql', {
                    'query': query,
                    'params': [job_type, task]
                }).execute()
                
                if result.data and len(result.data) > 0:
                    return result.data[0]
            except Exception:
                # Fallback: use regular query (less safe but works)
                result = self.client.table('pipeline_jobs') \
                    .select('*') \
                    .eq('status', 'queued') \
                    .eq('job_type', job_type) \
                    .filter('input->>task', 'eq', task) \
                    .order('created_at', desc=False) \
                    .limit(1) \
                    .execute()
                
                if result.data and len(result.data) > 0:
                    return result.data[0]
            
            return None
        except Exception as e:
            logger.error(f"Failed to poll jobs: {e}")
            raise
    
    def set_job_running(self, job_id: str, attempt: int) -> None:
        """Mark a job as running."""
        self.client.table('pipeline_jobs').update({
            'status': 'running',
            'started_at': datetime.utcnow().isoformat(),
            'attempt': attempt + 1
        }).eq('id', job_id).execute()
        logger.info(f"Job {job_id} marked as running (attempt {attempt + 1})")
    
    def set_job_success(self, job_id: str, output: Dict) -> None:
        """Mark a job as successful."""
        self.client.table('pipeline_jobs').update({
            'status': 'success',
            'finished_at': datetime.utcnow().isoformat(),
            'output': output
        }).eq('id', job_id).execute()
        logger.info(f"Job {job_id} completed successfully")
    
    def set_job_failed(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        self.client.table('pipeline_jobs').update({
            'status': 'failed',
            'finished_at': datetime.utcnow().isoformat(),
            'error': error
        }).eq('id', job_id).execute()
        logger.error(f"Job {job_id} failed: {error}")
    
    def get_segment_with_edition(self, segment_id: str) -> Optional[Dict]:
        """Get segment with edition info."""
        result = self.client.table('segments') \
            .select('*, editions!inner(id, work_id, media_type)') \
            .eq('id', segment_id) \
            .limit(1) \
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    
    def get_segment_assets(self, segment_id: str, asset_type: str) -> List[Dict]:
        """Get assets linked to a segment by type."""
        result = self.client.table('segment_assets') \
            .select('asset_id, assets!inner(*)') \
            .eq('segment_id', segment_id) \
            .eq('assets.asset_type', asset_type) \
            .execute()
        
        return [row['assets'] for row in result.data] if result.data else []
    
    def get_asset_by_r2_key(self, r2_key: str) -> Optional[Dict]:
        """Get asset by R2 key."""
        result = self.client.table('assets') \
            .select('*') \
            .eq('r2_key', r2_key) \
            .limit(1) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def insert_asset(
        self,
        r2_key: str,
        asset_type: str,
        content_type: str,
        bytes_size: int,
        sha256: str,
        bucket: str = 'chapterbridge-data'
    ) -> Dict:
        """Insert a new asset record."""
        result = self.client.table('assets').insert({
            'provider': 'cloudflare_r2',
            'bucket': bucket,
            'r2_key': r2_key,
            'asset_type': asset_type,
            'content_type': content_type,
            'bytes': bytes_size,
            'sha256': sha256,
            'upload_source': 'pipeline'
        }).execute()
        
        return result.data[0] if result.data else None
    
    def link_segment_asset(self, segment_id: str, asset_id: str, role: str = None) -> None:
        """Link an asset to a segment."""
        data = {'segment_id': segment_id, 'asset_id': asset_id}
        if role:
            data['role'] = role
        
        self.client.table('segment_assets').upsert(data).execute()
    
    def get_segment_summary(self, segment_id: str) -> Optional[Dict]:
        """Get segment summary if exists."""
        result = self.client.table('segment_summaries') \
            .select('*') \
            .eq('segment_id', segment_id) \
            .limit(1) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def upsert_segment_summary(
        self,
        segment_id: str,
        summary: str,
        summary_short: str,
        events: List,
        beats: List,
        key_dialogue: List,
        tone: Dict,
        model_version: str
    ) -> Dict:
        """Upsert segment summary."""
        result = self.client.table('segment_summaries').upsert({
            'segment_id': segment_id,
            'summary': summary,
            'summary_short': summary_short,
            'events': events,
            'beats': beats,
            'key_dialogue': key_dialogue,
            'tone': tone,
            'model_version': model_version
        }, on_conflict='segment_id').execute()
        
        logger.info(f"Upserted segment_summaries for {segment_id}")
        return result.data[0] if result.data else None
    
    def get_segment_entities(self, segment_id: str) -> Optional[Dict]:
        """Get segment entities if exists."""
        result = self.client.table('segment_entities') \
            .select('*') \
            .eq('segment_id', segment_id) \
            .limit(1) \
            .execute()
        
        return result.data[0] if result.data else None
    
    def upsert_segment_entities(
        self,
        segment_id: str,
        entities: Dict,
        model_version: str
    ) -> Dict:
        """Upsert segment entities."""
        data = {
            'segment_id': segment_id,
            'characters': entities.get('characters', []),
            'locations': entities.get('locations', []),
            'items': entities.get('items', []),
            'time_refs': entities.get('time_refs', []),
            'organizations': entities.get('organizations', []),
            'factions': entities.get('factions', []),
            'titles_ranks': entities.get('titles_ranks', []),
            'skills': entities.get('skills', []),
            'creatures': entities.get('creatures', []),
            'concepts': entities.get('concepts', []),
            'relationships': entities.get('relationships', []),
            'emotions': entities.get('emotions', []),
            'keywords': entities.get('keywords', []),
            'model_version': model_version
        }
        
        result = self.client.table('segment_entities').upsert(
            data, on_conflict='segment_id'
        ).execute()
        
        logger.info(f"Upserted segment_entities for {segment_id}")
        return result.data[0] if result.data else None
    
    def get_work_characters(self, work_id: str) -> List[Dict]:
        """Get all characters for a work."""
        result = self.client.table('characters') \
            .select('*') \
            .eq('work_id', work_id) \
            .execute()
        
        return result.data if result.data else []
    
    def upsert_character(
        self,
        work_id: str,
        name: str,
        aliases: List[str],
        character_facts: List[Dict],
        description: str,
        model_version: str
    ) -> Dict:
        """Upsert a character (novel only)."""
        result = self.client.table('characters').upsert({
            'work_id': work_id,
            'name': name,
            'aliases': aliases,
            'character_facts': character_facts,
            'description': description or '',
            'model_version': model_version
        }, on_conflict='work_id,name').execute()
        
        return result.data[0] if result.data else None
    
    def update_character(self, char_id: str, updates: Dict) -> None:
        """Update an existing character."""
        self.client.table('characters').update(updates).eq('id', char_id).execute()
    
    def get_segments_missing_nlp(self) -> List[Dict]:
        """Get segments that are missing NLP processing."""
        result = self.client.rpc('get_segments_missing_nlp').execute()
        return result.data if result.data else []
    
    def enqueue_nlp_job(self, segment_id: str, force: bool = False) -> Dict:
        """Enqueue an NLP pack job for a segment."""
        # Get segment with edition and work info
        seg_result = self.client.table('segments').select(
            'id, edition_id, editions!inner(work_id)'
        ).eq('id', segment_id).limit(1).execute()
        
        if not seg_result.data:
            raise ValueError(f"Segment {segment_id} not found")
        
        seg = seg_result.data[0]
        
        result = self.client.table('pipeline_jobs').insert({
            'job_type': 'summarize',
            'segment_id': segment_id,
            'edition_id': seg['edition_id'],
            'work_id': seg['editions']['work_id'],
            'input': {'task': 'nlp_pack_v1', 'force': force},
            'status': 'queued'
        }).execute()
        
        return result.data[0] if result.data else None
    
    def reset_stale_jobs(
        self, 
        job_type: str = 'summarize',
        timeout_minutes: int = 3,
        max_attempts: int = 3
    ) -> int:
        """
        Reset stale running jobs that have been stuck for too long.
        
        This handles cases where:
        - Pod was interrupted (interruptible instance)
        - Worker crashed without marking job failed
        - Network issues caused job to hang
        
        Args:
            job_type: Job type to check (default: 'summarize')
            timeout_minutes: Consider job stale if running longer than this
            max_attempts: Maximum retry attempts before marking as permanently failed
        
        Returns:
            Number of jobs reset
        """
        from datetime import datetime, timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(minutes=timeout_minutes)
        
        # Find stale running jobs
        result = self.client.table('pipeline_jobs') \
            .select('id, segment_id, attempt, started_at') \
            .eq('status', 'running') \
            .eq('job_type', job_type) \
            .lt('started_at', cutoff_time.isoformat()) \
            .execute()
        
        if not result.data:
            return 0
        
        reset_count = 0
        for job in result.data:
            job_id = job['id']
            attempt = job.get('attempt', 0)
            
            if attempt >= max_attempts:
                # Exceeded max retries, mark as permanently failed
                self.client.table('pipeline_jobs').update({
                    'status': 'failed',
                    'finished_at': datetime.utcnow().isoformat(),
                    'error': f'Job timeout after {timeout_minutes} minutes (interrupted/crashed). Max retries exceeded.'
                }).eq('id', job_id).execute()
                logger.warning(f"Job {job_id} marked as permanently failed (max retries exceeded)")
            else:
                # Reset to queued for retry
                self.client.table('pipeline_jobs').update({
                    'status': 'failed',
                    'finished_at': datetime.utcnow().isoformat(),
                    'error': f'Job timeout after {timeout_minutes} minutes (interrupted/crashed). Will retry.'
                }).eq('id', job_id).execute()
                logger.warning(f"Job {job_id} reset from stale running state (attempt {attempt}/{max_attempts})")
            
            reset_count += 1
        
        if reset_count > 0:
            logger.info(f"Reset {reset_count} stale running jobs (timeout: {timeout_minutes}min)")
        
        return reset_count


_supabase_client: Optional[SupabaseClient] = None

def get_supabase_client() -> SupabaseClient:
    """Get singleton Supabase client instance."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = SupabaseClient()
    return _supabase_client
