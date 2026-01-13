"""Main daemon poller for NLP Pack worker with metrics, dry-run mode, and partial idempotency."""

import os
import sys
import time
import argparse
import traceback
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .utils import get_logger, count_paragraphs, count_subtitle_blocks
from .supabase_client import get_supabase_client, SupabaseClient
from .r2_client import get_r2_client, R2Client
from .qwen_client import get_qwen_client, QwenClient
from .key_builder import build_key_from_segment
from .character_merge import process_character_updates
from .text_extractors import extract_subtitle_text, extract_novel_text, extract_manhwa_text

logger = get_logger(__name__)

POLL_SECONDS = int(os.environ.get('POLL_SECONDS', '3'))
MAX_RETRIES_PER_JOB = int(os.environ.get('MAX_RETRIES_PER_JOB', '2'))
MODEL_VERSION = os.environ.get('MODEL_VERSION', 'qwen2.5-7b-awq_nlp_pack_v1')


class NLPPackWorker:
    """NLP Pack worker that processes summarize jobs with metrics and partial idempotency."""
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.db = get_supabase_client() if not dry_run else None
        self.r2 = get_r2_client() if not dry_run else None
        self.qwen = get_qwen_client()
        logger.info(f"NLP Pack Worker initialized (dry_run={dry_run})")
    
    def _init_clients_for_read(self):
        """Initialize clients for reading (used in dry-run mode)."""
        if self.db is None:
            self.db = get_supabase_client()
        if self.r2 is None:
            self.r2 = get_r2_client()
    
    def extract_source_text(
        self,
        segment_id: str,
        media_type: str
    ) -> tuple[Optional[str], Dict[str, Any]]:
        """
        Extract source text based on media type.
        
        Returns:
            (extracted_text, extraction_stats)
        """
        self._init_clients_for_read()
        
        stats = {
            'media_type': media_type,
            'page_count': 0,
            'paragraph_count': 0,
            'subtitle_blocks': 0
        }
        
        if media_type == 'anime':
            assets = self.db.get_segment_assets(segment_id, 'raw_subtitle')
            if not assets:
                logger.error(f"No raw_subtitle asset found for segment {segment_id}")
                return None, stats
            
            asset = assets[0]
            content = self.r2.download_text(asset['r2_key'])
            text = extract_subtitle_text(content, asset['r2_key'])
            stats['subtitle_blocks'] = count_subtitle_blocks(content)
            return text, stats
        
        elif media_type == 'novel':
            assets = self.db.get_segment_assets(segment_id, 'raw_html')
            if not assets:
                logger.error(f"No raw_html asset found for segment {segment_id}")
                return None, stats
            
            asset = assets[0]
            content = self.r2.download_text(asset['r2_key'])
            text = extract_novel_text(content)
            stats['paragraph_count'] = count_paragraphs(text)
            return text, stats
        
        elif media_type == 'manhwa':
            assets = self.db.get_segment_assets(segment_id, 'ocr_json')
            if not assets:
                logger.error(f"No ocr_json assets found for segment {segment_id}")
                return None, stats
            
            stats['page_count'] = len(assets)
            ocr_contents = []
            for asset in assets:
                content = self.r2.download_text(asset['r2_key'])
                ocr_contents.append(content)
            
            text = extract_manhwa_text(assets, ocr_contents)
            return text, stats
        
        else:
            logger.error(f"Unknown media type: {media_type}")
            return None, stats
    
    def check_existing_outputs(
        self,
        segment_id: str,
        cleaned_r2_key: str
    ) -> Dict[str, bool]:
        """Check which outputs already exist."""
        self._init_clients_for_read()
        
        existing = {
            'cleaned_text': False,
            'segment_summaries': False,
            'segment_entities': False
        }
        
        if self.db.get_asset_by_r2_key(cleaned_r2_key):
            existing['cleaned_text'] = True
        
        if self.db.get_segment_summary(segment_id):
            existing['segment_summaries'] = True
        
        if self.db.get_segment_entities(segment_id):
            existing['segment_entities'] = True
        
        return existing
    
    def write_cleaned_text(
        self,
        cleaned_text: str,
        r2_key: str,
        segment_id: str,
        bucket: str
    ) -> Dict[str, Any]:
        """Write cleaned text to R2 and create asset record."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would write cleaned text to {r2_key}")
            return {'asset_id': 'dry-run', 'r2_key': r2_key, 'bytes': len(cleaned_text.encode())}
        
        upload_result = self.r2.upload_text(r2_key, cleaned_text)
        
        asset = self.db.insert_asset(
            r2_key=r2_key,
            asset_type='cleaned_text',
            content_type='text/plain; charset=utf-8',
            bytes_size=upload_result['bytes'],
            sha256=upload_result['sha256'],
            bucket=bucket
        )
        
        self.db.link_segment_asset(segment_id, asset['id'], role='cleaned_text')
        
        return {
            'asset_id': asset['id'],
            'r2_key': r2_key,
            'bytes': upload_result['bytes']
        }
    
    def process_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single NLP pack job with metrics and partial idempotency.
        
        Returns:
            Output dict with stats for pipeline_jobs.output
        """
        job_id = job['id']
        segment_id = job['segment_id']
        job_input = job.get('input', {})
        force = job_input.get('force', False)
        
        logger.info(f"Processing job {job_id} for segment {segment_id}")
        
        self._init_clients_for_read()
        segment = self.db.get_segment_with_edition(segment_id)
        if not segment:
            raise ValueError(f"Segment {segment_id} not found")
        
        edition = segment['editions']
        media_type = edition['media_type']
        work_id = edition['work_id']
        segment_type = segment['segment_type']
        segment_number = int(segment['number'])
        
        logger.info(f"Segment {segment_id}: {media_type} {segment_type}-{segment_number}, work={work_id}")
        
        cleaned_r2_key = build_key_from_segment(segment, edition)
        
        existing = self.check_existing_outputs(segment_id, cleaned_r2_key)
        all_exist = all(existing.values())
        
        output_result = {
            'model_version': MODEL_VERSION,
            'cleaned_r2_key': cleaned_r2_key,
            'stats': {
                'media_type': media_type,
                'segment_type': segment_type,
                'segment_number': segment_number
            }
        }
        
        if all_exist and not force:
            logger.info(f"All outputs exist for segment {segment_id}, skipping")
            return {
                'skipped': True,
                'reason': 'already_exists',
                'existing': existing,
                **output_result
            }
        
        source_text, extraction_stats = self.extract_source_text(segment_id, media_type)
        if not source_text:
            raise ValueError(f"Failed to extract source text for segment {segment_id}")
        
        output_result['stats'].update(extraction_stats)
        logger.info(f"Extracted {len(source_text)} chars of source text")
        
        model_output, model_stats = self.qwen.process_text(source_text, media_type)
        if not model_output:
            raise ValueError("Model processing failed to produce valid output")
        
        output_result['stats'].update(model_stats)
        output_result['upserted'] = True
        
        if not existing['cleaned_text'] or force:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would write cleaned text ({len(model_output['cleaned_text'])} chars)")
                output_result['cleaned_bytes'] = len(model_output['cleaned_text'].encode())
            else:
                cleaned_result = self.write_cleaned_text(
                    model_output['cleaned_text'],
                    cleaned_r2_key,
                    segment_id,
                    self.r2.bucket
                )
                output_result['cleaned_asset_id'] = cleaned_result['asset_id']
                output_result['cleaned_bytes'] = cleaned_result['bytes']
            logger.info(f"Wrote cleaned text: {cleaned_r2_key}")
        else:
            logger.info("Cleaned text already exists, skipped write")
            output_result['cleaned_text_skipped'] = True
        
        if not existing['segment_summaries'] or force:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would upsert segment summary")
            else:
                summary_data = model_output['segment_summary']
                self.db.upsert_segment_summary(
                    segment_id=segment_id,
                    summary=summary_data.get('summary', ''),
                    summary_short=summary_data.get('summary_short', ''),
                    events=summary_data.get('events', []),
                    beats=summary_data.get('beats', []),
                    key_dialogue=summary_data.get('key_dialogue', []),
                    tone=summary_data.get('tone', {}),
                    model_version=MODEL_VERSION
                )
            output_result['summary_upserted'] = True
        else:
            logger.info("Segment summary already exists, skipped upsert")
            output_result['summary_skipped'] = True
        
        if not existing['segment_entities'] or force:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would upsert segment entities")
            else:
                self.db.upsert_segment_entities(
                    segment_id=segment_id,
                    entities=model_output['segment_entities'],
                    model_version=MODEL_VERSION
                )
            output_result['entities_upserted'] = True
        else:
            logger.info("Segment entities already exists, skipped upsert")
            output_result['entities_skipped'] = True
        
        if media_type == 'novel':
            character_updates = model_output.get('character_updates', [])
            if character_updates:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would process {len(character_updates)} character updates")
                    output_result['characters'] = {'would_process': len(character_updates)}
                else:
                    work_characters = self.db.get_work_characters(work_id)
                    char_stats = process_character_updates(
                        work_id=work_id,
                        work_characters=work_characters,
                        character_updates=character_updates,
                        segment_number=segment_number,
                        model_version=MODEL_VERSION,
                        db_client=self.db,
                        media_type=media_type
                    )
                    output_result['characters'] = char_stats
                logger.info(f"Character updates: {output_result.get('characters')}")
        
        return output_result
    
    def process_segment_direct(self, segment_id: str) -> Dict[str, Any]:
        """
        Process a segment directly without job queue (for dry-run mode).
        
        Args:
            segment_id: The segment UUID to process
        
        Returns:
            Output dict with results
        """
        fake_job = {
            'id': 'direct-' + segment_id[:8],
            'segment_id': segment_id,
            'input': {'task': 'nlp_pack_v1', 'force': True}
        }
        return self.process_job(fake_job)
    
    def run_once(self) -> bool:
        """
        Poll and process one job.
        
        Returns:
            True if a job was processed, False if queue empty
        """
        if self.dry_run:
            logger.warning("run_once called in dry-run mode - use process_segment_direct instead")
            return False
        
        job = self.db.poll_next_job()
        
        if not job:
            return False
        
        job_id = job['id']
        segment_id = job.get('segment_id', 'unknown')
        attempt = job.get('attempt') or 0
        
        logger.info(f"Processing job_id={job_id}, segment_id={segment_id}")
        
        if attempt >= MAX_RETRIES_PER_JOB:
            logger.warning(f"Job {job_id} exceeded max retries ({MAX_RETRIES_PER_JOB}), marking failed")
            self.db.set_job_failed(job_id, f"Exceeded max retries ({MAX_RETRIES_PER_JOB})")
            return True
        
        self.db.set_job_running(job_id, attempt)
        
        try:
            output = self.process_job(job)
            self.db.set_job_success(job_id, output)
            
            skipped_reason = output.get('reason', 'processed')
            stats = output.get('stats', {})
            logger.info(
                f"Job {job_id} completed: segment_id={segment_id}, "
                f"media_type={stats.get('media_type')}, "
                f"output_r2_key={output.get('cleaned_r2_key')}, "
                f"skipped_reason={skipped_reason if output.get('skipped') else 'none'}"
            )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Job {job_id} failed: {error_msg}")
            self.db.set_job_failed(job_id, error_msg)
        
        return True
    
    def run_forever(self):
        """Run the worker daemon loop."""
        if self.dry_run:
            logger.error("Cannot run daemon in dry-run mode")
            return
        
        logger.info(f"Starting NLP Pack Worker daemon (poll every {POLL_SECONDS}s)")
        
        while True:
            try:
                had_work = self.run_once()
                
                if not had_work:
                    time.sleep(POLL_SECONDS)
            except KeyboardInterrupt:
                logger.info("Shutting down worker...")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                time.sleep(POLL_SECONDS)


def run_dry_run(segment_id: str):
    """Run a dry-run for a specific segment."""
    import json
    
    logger.info("=" * 60)
    logger.info(f"DRY RUN for segment: {segment_id}")
    logger.info("=" * 60)
    
    worker = NLPPackWorker(dry_run=True)
    
    try:
        result = worker.process_segment_direct(segment_id)
        
        print("\n" + "=" * 60)
        print("DRY RUN RESULTS")
        print("=" * 60)
        
        stats = result.get('stats', {})
        print(f"\nMedia Type: {stats.get('media_type')}")
        print(f"Segment: {stats.get('segment_type')}-{stats.get('segment_number')}")
        print(f"R2 Key: {result.get('cleaned_r2_key')}")
        
        print(f"\nInput Stats:")
        print(f"  - Input chars: {stats.get('input_chars', 0):,}")
        print(f"  - Input tokens (est): {stats.get('input_tokens_est', 0):,}")
        if stats.get('page_count'):
            print(f"  - Pages: {stats.get('page_count')}")
        if stats.get('paragraph_count'):
            print(f"  - Paragraphs: {stats.get('paragraph_count')}")
        if stats.get('subtitle_blocks'):
            print(f"  - Subtitle blocks: {stats.get('subtitle_blocks')}")
        
        print(f"\nModel Stats:")
        print(f"  - Output chars: {stats.get('output_chars', 0):,}")
        print(f"  - Model latency: {stats.get('model_latency_ms', 0):,}ms")
        print(f"  - Retries: {stats.get('retries_count', 0)}")
        if stats.get('repair_attempted'):
            print(f"  - Repair attempted: {stats.get('repair_succeeded', False)}")
        
        if result.get('skipped'):
            print(f"\nSkipped: {result.get('reason')}")
        else:
            print(f"\nWould write:")
            print(f"  - Cleaned text: {result.get('cleaned_bytes', 0):,} bytes")
            print(f"  - Summary: {'yes' if result.get('summary_upserted') else 'no'}")
            print(f"  - Entities: {'yes' if result.get('entities_upserted') else 'no'}")
            if result.get('characters'):
                print(f"  - Characters: {result.get('characters')}")
        
        print("\n" + "=" * 60)
        
    except Exception as e:
        logger.error(f"Dry run failed: {e}")
        traceback.print_exc()
        sys.exit(1)


def main():
    """Entry point for the worker."""
    parser = argparse.ArgumentParser(description='NLP Pack Worker')
    parser.add_argument('--segment-id', type=str, help='Process a specific segment (for dry-run)')
    parser.add_argument('--no-write', '--dry-run', action='store_true', 
                        help='Dry run mode - process but do not write to DB/R2')
    args = parser.parse_args()
    
    if args.segment_id:
        if not args.no_write:
            logger.warning("--segment-id provided without --no-write, enabling dry-run mode")
        run_dry_run(args.segment_id)
        return
    
    if args.no_write:
        logger.error("--no-write requires --segment-id")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("NLP Pack Worker Starting")
    logger.info("=" * 60)
    
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_SERVICE_ROLE_KEY',
        'R2_ENDPOINT',
        'R2_ACCESS_KEY_ID',
        'R2_SECRET_ACCESS_KEY'
    ]
    
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)
    
    worker = NLPPackWorker()
    worker.run_forever()


if __name__ == '__main__':
    main()
