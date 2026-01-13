"""Enqueue script to create NLP pack jobs for segments missing processing."""

import os
import sys
import argparse
from typing import List, Dict, Optional

from .utils import get_logger
from .supabase_client import get_supabase_client

logger = get_logger(__name__)


def get_segments_missing_nlp(db) -> List[Dict]:
    """
    Find segments that are missing any NLP outputs.
    
    Checks for missing:
    - cleaned_text asset
    - segment_summaries row
    - segment_entities row
    """
    query = """
    SELECT 
        s.id as segment_id,
        s.segment_type,
        s.number,
        s.title,
        e.media_type,
        e.work_id,
        e.id as edition_id,
        CASE WHEN EXISTS (
            SELECT 1 FROM segment_assets sa 
            JOIN assets a ON sa.asset_id = a.id 
            WHERE sa.segment_id = s.id AND a.asset_type = 'cleaned_text'
        ) THEN true ELSE false END as has_cleaned,
        CASE WHEN EXISTS (
            SELECT 1 FROM segment_summaries ss WHERE ss.segment_id = s.id
        ) THEN true ELSE false END as has_summary,
        CASE WHEN EXISTS (
            SELECT 1 FROM segment_entities se WHERE se.segment_id = s.id
        ) THEN true ELSE false END as has_entities
    FROM segments s
    JOIN editions e ON s.edition_id = e.id
    WHERE NOT (
        EXISTS (
            SELECT 1 FROM segment_assets sa 
            JOIN assets a ON sa.asset_id = a.id 
            WHERE sa.segment_id = s.id AND a.asset_type = 'cleaned_text'
        )
        AND EXISTS (
            SELECT 1 FROM segment_summaries ss WHERE ss.segment_id = s.id
        )
        AND EXISTS (
            SELECT 1 FROM segment_entities se WHERE se.segment_id = s.id
        )
    )
    ORDER BY e.work_id, s.number
    """
    
    result = db.client.rpc('get_segments_missing_nlp_outputs', {}).execute()
    
    if result.data:
        return result.data
    
    from supabase import PostgrestAPIError
    try:
        result = db.client.table('segments').select(
            'id, segment_type, number, title, editions!inner(id, work_id, media_type)'
        ).execute()
        
        segments = []
        for row in result.data or []:
            segment_id = row['id']
            
            has_cleaned = bool(db.get_segment_assets(segment_id, 'cleaned_text'))
            has_summary = bool(db.get_segment_summary(segment_id))
            has_entities = bool(db.get_segment_entities(segment_id))
            
            if not (has_cleaned and has_summary and has_entities):
                segments.append({
                    'segment_id': segment_id,
                    'segment_type': row['segment_type'],
                    'number': row['number'],
                    'title': row.get('title'),
                    'media_type': row['editions']['media_type'],
                    'work_id': row['editions']['work_id'],
                    'edition_id': row['editions']['id'],
                    'has_cleaned': has_cleaned,
                    'has_summary': has_summary,
                    'has_entities': has_entities
                })
        
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
        force: If True, enqueue even if some outputs exist
        limit: Maximum number of jobs to enqueue
        work_id: Filter to specific work
        media_type: Filter to specific media type
        dry_run: If True, only show what would be enqueued
    
    Returns:
        Stats dict with counts
    """
    db = get_supabase_client()
    
    logger.info("Finding segments missing NLP processing...")
    segments = get_segments_missing_nlp(db)
    
    if work_id:
        segments = [s for s in segments if s['work_id'] == work_id]
    
    if media_type:
        segments = [s for s in segments if s['media_type'] == media_type]
    
    if limit:
        segments = segments[:limit]
    
    logger.info(f"Found {len(segments)} segments to process")
    
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
