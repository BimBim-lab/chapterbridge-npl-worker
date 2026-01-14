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
    media_type: Optional[str] = None,
) -> List[Dict]:
    """
    Find segments that are missing any NLP outputs using efficient batch query.
    
    Checks for missing:
    - segment_summaries row
    - segment_entities row
    """
    page_size = 1000
    if limit:
        page_size = max(50, min(page_size, limit * 3))

    segments: List[Dict] = []
    offset = 0

    try:
        while True:
            query_builder = db.client.table('segments').select(
                '''
                id,
                segment_type,
                number,
                title,
                editions!inner(id, work_id, media_type),
                segment_summaries!left(segment_id),
                segment_entities!left(segment_id),
                segment_assets!left(assets(asset_type))
                '''
            )

            if work_id:
                query_builder = query_builder.eq('editions.work_id', work_id)
            if media_type:
                query_builder = query_builder.eq('editions.media_type', media_type)

            query_builder = query_builder.range(offset, offset + page_size - 1)
            result = query_builder.execute()
            rows = result.data or []

            for row in rows:
                row_media_type = row['editions']['media_type']

                # Require presence of raw asset per media type
                segment_assets = row.get('segment_assets') or []
                has_raw_asset = False
                for asset in segment_assets:
                    asset_type = asset.get('assets', {}).get('asset_type', '')
                    if row_media_type == 'novel' and asset_type in ('raw_html', 'cleaned_text'):
                        has_raw_asset = True
                        break
                    if row_media_type == 'manhwa' and asset_type == 'raw_image':
                        has_raw_asset = True
                        break
                    if row_media_type == 'anime' and asset_type == 'raw_subtitle':
                        has_raw_asset = True
                        break

                if not has_raw_asset:
                    continue

                has_summary = len(row.get('segment_summaries') or []) > 0
                has_entities = len(row.get('segment_entities') or []) > 0

                if has_summary and has_entities:
                    continue

                segments.append({
                    'segment_id': row['id'],
                    'segment_type': row['segment_type'],
                    'number': row['number'],
                    'title': row.get('title'),
                    'media_type': row_media_type,
                    'work_id': row['editions']['work_id'],
                    'edition_id': row['editions']['id'],
                    'has_summary': has_summary,
                    'has_entities': has_entities
                })

                if limit and len(segments) >= limit:
                    return segments

            if len(rows) < page_size:
                break

            offset += page_size

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


def get_pending_map(db, segment_ids: List[str], chunk_size: int = 200) -> set:
    """Batch check pending jobs for many segment ids, return set of pending segment_ids."""
    pending: set = set()
    if not segment_ids:
        return pending

    for i in range(0, len(segment_ids), chunk_size):
        chunk = segment_ids[i:i + chunk_size]
        result = db.client.table('pipeline_jobs').select('segment_id').in_(
            'segment_id', chunk
        ).eq(
            'job_type', 'summarize'
        ).in_(
            'status', ['queued', 'running']
        ).execute()

        for row in result.data or []:
            sid = row.get('segment_id')
            if sid:
                pending.add(sid)

    return pending


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
    segments = get_segments_missing_nlp(
        db,
        limit=limit,
        work_id=work_id,
        media_type=media_type
    )
    
    logger.info(f"Found {len(segments)} segments to process")
    
    stats = {'enqueued': 0, 'skipped_pending': 0, 'skipped_complete': 0}

    pending_map = get_pending_map(db, [s['segment_id'] for s in segments])
    
    for seg in segments:
        segment_id = seg['segment_id']
        
        if not force:
            has_all = seg.get('has_cleaned', False) and seg.get('has_summary', False) and seg.get('has_entities', False)
            if has_all:
                stats['skipped_complete'] += 1
                continue
        
        if segment_id in pending_map:
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
