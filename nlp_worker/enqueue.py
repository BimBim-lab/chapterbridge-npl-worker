"""Enqueue script to create NLP pack jobs for segments missing processing."""

import os
import sys
import argparse
from typing import List, Dict, Optional
from dotenv import load_dotenv

from .utils import get_logger
from .supabase_client import get_supabase_client

load_dotenv()
logger = get_logger(__name__)


def get_segments_missing_nlp(
    db, 
    limit: Optional[int] = None,
    work_id: Optional[str] = None,
    edition_id: Optional[str] = None
) -> List[Dict]:
    """
    Find segments that are missing any NLP outputs using efficient batch query.
    
    Checks for missing:
    - segment_summaries row
    - segment_entities row
    
    Args:
        db: Database client
        limit: Maximum results to return (applied after filtering)
        work_id: Filter by specific work_id
        edition_id: Filter by specific edition_id
    """
    # Try using SQL with LEFT JOINs - much more efficient!
    query = """
    SELECT 
        s.id as segment_id,
        s.segment_type,
        s.number,
        s.title,
        e.media_type,
        e.work_id,
        e.id as edition_id,
        CASE WHEN ss.segment_id IS NOT NULL THEN true ELSE false END as has_summary,
        CASE WHEN se.segment_id IS NOT NULL THEN true ELSE false END as has_entities
    FROM segments s
    JOIN editions e ON s.edition_id = e.id
    LEFT JOIN segment_summaries ss ON ss.segment_id = s.id
    LEFT JOIN segment_entities se ON se.segment_id = s.id
    WHERE (ss.segment_id IS NULL OR se.segment_id IS NULL)
    """
    
    # Add filters to SQL query
    if work_id:
        query += f" AND e.work_id = '{work_id}'"
    if edition_id:
        query += f" AND e.id = '{edition_id}'"
    
    query += " ORDER BY e.work_id, s.number"
    
    if limit:
        query += f" LIMIT {limit}"
    
    try:
        # Try direct SQL execution via RPC or raw SQL
        result = db.client.rpc('execute_sql', {'query': query}).execute()
        if result.data:
            return result.data
    except Exception as e:
        logger.debug(f"RPC execute_sql not available: {e}")
    
    # Fallback: use optimized Supabase query with single request
    try:
        # If work_id provided, get edition_ids first to filter properly
        edition_ids_to_filter = []
        if work_id:
            logger.info(f"Fetching editions for work_id: {work_id}")
            editions = db.client.table('editions').select('id').eq('work_id', work_id).execute()
            edition_ids_to_filter = [e['id'] for e in editions.data]
            logger.info(f"Found {len(edition_ids_to_filter)} editions: {edition_ids_to_filter}")
            if not edition_ids_to_filter:
                logger.warning(f"No editions found for work_id {work_id}")
                return []
        
        if edition_id:
            edition_ids_to_filter = [edition_id]
            logger.info(f"Using edition_id filter: {edition_id}")
        
        query_builder = db.client.table('segments').select(
            '''
            id,
            segment_type,
            number,
            title,
            edition_id,
            editions!inner(id, work_id, media_type),
            segment_summaries!left(segment_id),
            segment_entities!left(segment_id),
            segment_assets!left(assets(asset_type))
            '''
        )
        
        # Filter by edition_id directly (more reliable than nested filter)
        if edition_ids_to_filter:
            logger.info(f"Applying edition_id filter, fetching up to 10000 segments")
            query_builder = query_builder.in_('edition_id', edition_ids_to_filter)
            # Fetch all segments for this work (no 1000 limit)
            query_builder = query_builder.limit(10000)
        elif limit:
            # Only apply limit if no work/edition filter
            query_builder = query_builder.limit(limit * 3)
        else:
            # Default: fetch first 1000
            query_builder = query_builder.limit(1000)
        
        logger.info("Executing segments query...")
        result = query_builder.execute()
        logger.info(f"Query returned {len(result.data or [])} segments")
        
        segments = []
        for row in result.data or []:
            media_type = row['editions']['media_type']
            
            # Check if segment has required raw asset based on media type
            segment_assets = row.get('segment_assets') or []
            has_raw_asset = False
            
            for asset in segment_assets:
                asset_type = asset.get('assets', {}).get('asset_type', '')
                if media_type == 'novel' and asset_type in ('raw_html', 'cleaned_text'):
                    has_raw_asset = True
                    break
                elif media_type == 'manhwa' and asset_type == 'raw_image':
                    has_raw_asset = True
                    break
                elif media_type == 'anime' and asset_type == 'raw_subtitle':
                    has_raw_asset = True
                    break
            
            # Skip segments without raw assets
            if not has_raw_asset:
                continue
            
            # Check if outputs exist
            has_summary = len(row.get('segment_summaries') or []) > 0
            has_entities = len(row.get('segment_entities') or []) > 0
            
            # Only include if missing any output
            if not (has_summary and has_entities):
                segments.append({
                    'segment_id': row['id'],
                    'segment_type': row['segment_type'],
                    'number': row['number'],
                    'title': row.get('title'),
                    'media_type': media_type,
                    'work_id': row['editions']['work_id'],
                    'edition_id': row['editions']['id'],
                    'has_summary': has_summary,
                    'has_entities': has_entities
                })
                
                if limit and len(segments) >= limit:
                    break
        
        return segments
    except Exception as e:
        logger.error(f"Failed to query missing segments: {e}")
        return []


def check_pending_job(db, segment_id: str) -> bool:
    """Check if there's already a pending job for this segment."""
    result = db.client.table('pipeline_jobs').select('id').eq(
        'segment_id', segment_id
    ).eq(
        'job_type', 'summarize'
    ).in_(
        'status', ['queued', 'running']
    ).execute()
    
    return bool(result.data)


def enqueue_jobs(
    force: bool = False,
    limit: Optional[int] = None,
    work_id: Optional[str] = None,
    media_type: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Enqueue NLP pack jobs for segments missing processing.
    
    Args:
    # Pass work_id to query to avoid pagination issues
    segments = get_segments_missing_nlp(db, limit=None, work_id=work_id)
        dry_run: If True, only show what would be enqueued
    
    Returns:
        Stats dict with counts
    """
    db = get_supabase_client()
    
    logger.info("Finding segments missing NLP processing...")
    # Pass work_id to query function to avoid pagination issues
    segments = get_segments_missing_nlp(db, limit=None, work_id=work_id)
    
    if media_type:
        segments = [s for s in segments if s['media_type'] == media_type]
    
    logger.info(f"Found {len(segments)} segments missing NLP")
    
    # Apply limit after all filtering
    if limit:
        segments = segments[:limit]
        logger.info(f"Limited to {len(segments)} segments")
    
    logger.info(f"Will process {len(segments)} segments")
    
    stats = {'enqueued': 0, 'skipped_pending': 0, 'skipped_complete': 0}
    
    for seg in segments:
        segment_id = seg['segment_id']
        
        if not force:
            has_all = seg.get('has_cleaned', False) and seg.get('has_summary', False) and seg.get('has_entities', False)
            if has_all:
                stats['skipped_complete'] += 1
                continue
        
        if check_pending_job(db, segment_id):
            logger.debug(f"Segment {segment_id} already has pending job")
            stats['skipped_pending'] += 1
            continue
        
        if dry_run:
            logger.info(f"[DRY RUN] Would enqueue: {seg['media_type']} {seg['segment_type']}-{seg['number']}")
            stats['enqueued'] += 1
            continue
        
        db.enqueue_nlp_job(segment_id, force=force)
        logger.info(f"Enqueued job for segment {segment_id}: {seg['media_type']} {seg['segment_type']}-{seg['number']}")
        stats['enqueued'] += 1
    
    return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Enqueue NLP pack jobs for segments missing processing'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force reprocessing even if outputs exist'
    )
    parser.add_argument(
        '--limit', '-l',
        type=int,
        default=None,
        help='Maximum number of jobs to enqueue'
    )
    parser.add_argument(
        '--work-id', '-w',
        type=str,
        default=None,
        help='Filter to specific work UUID'
    )
    parser.add_argument(
        '--media-type', '-m',
        type=str,
        choices=['novel', 'manhwa', 'anime'],
        default=None,
        help='Filter to specific media type'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be enqueued without actually enqueueing'
    )
    
    args = parser.parse_args()
    
    required_vars = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY']
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)
    
    stats = enqueue_jobs(
        force=args.force,
        limit=args.limit,
        work_id=args.work_id,
        media_type=args.media_type,
        dry_run=args.dry_run
    )
    
    logger.info("=" * 40)
    logger.info(f"Enqueued: {stats['enqueued']}")
    logger.info(f"Skipped (pending): {stats['skipped_pending']}")
    logger.info(f"Skipped (complete): {stats['skipped_complete']}")
    logger.info("=" * 40)


if __name__ == '__main__':
    main()
