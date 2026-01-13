"""Main daemon poller for NLP Pack worker."""

import os
import sys
import time
import traceback
from typing import Dict, Any, Optional, List

from .utils import get_logger
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
    """NLP Pack worker that processes summarize jobs."""
    
    def __init__(self):
        self.db = get_supabase_client()
        self.r2 = get_r2_client()
        self.qwen = get_qwen_client()
        logger.info("NLP Pack Worker initialized")
    
    def extract_source_text(
        self,
        segment_id: str,
        media_type: str
    ) -> Optional[str]:
        """
        Extract source text based on media type.
        
        Args:
            segment_id: The segment ID
            media_type: 'novel', 'manhwa', or 'anime'
        
        Returns:
            Extracted text or None if no source found
        """
        if media_type == 'anime':
            assets = self.db.get_segment_assets(segment_id, 'raw_subtitle')
            if not assets:
                logger.error(f"No raw_subtitle asset found for segment {segment_id}")
                return None
            
            asset = assets[0]
            content = self.r2.download_text(asset['r2_key'])
            return extract_subtitle_text(content, asset['r2_key'])
        
        elif media_type == 'novel':
            assets = self.db.get_segment_assets(segment_id, 'raw_html')
            if not assets:
                logger.error(f"No raw_html asset found for segment {segment_id}")
                return None
            
            asset = assets[0]
            content = self.r2.download_text(asset['r2_key'])
            return extract_novel_text(content)
        
        elif media_type == 'manhwa':
            assets = self.db.get_segment_assets(segment_id, 'ocr_json')
            if not assets:
                logger.error(f"No ocr_json assets found for segment {segment_id}")
                return None
            
            ocr_contents = []
            for asset in assets:
                content = self.r2.download_text(asset['r2_key'])
                ocr_contents.append(content)
            
            return extract_manhwa_text(assets, ocr_contents)
        
        else:
            logger.error(f"Unknown media type: {media_type}")
            return None
    
    def check_existing_outputs(
        self,
        segment_id: str,
        cleaned_r2_key: str
    ) -> Dict[str, bool]:
        """Check which outputs already exist."""
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
        Process a single NLP pack job.
        
        Args:
            job: The pipeline_jobs record
        
        Returns:
            Output dict for success
        
        Raises:
            Exception: On processing failure
        """
        job_id = job['id']
        segment_id = job['segment_id']
        job_input = job.get('input', {})
        force = job_input.get('force', False)
        
        logger.info(f"Processing job {job_id} for segment {segment_id}")
        
        segment = self.db.get_segment_with_edition(segment_id)
        if not segment:
            raise ValueError(f"Segment {segment_id} not found")
        
        edition = segment['editions']
        media_type = edition['media_type']
        work_id = edition['work_id']
        
        logger.info(f"Segment {segment_id}: {media_type}, work={work_id}")
        
        cleaned_r2_key = build_key_from_segment(segment, edition)
        
        existing = self.check_existing_outputs(segment_id, cleaned_r2_key)
        all_exist = all(existing.values())
        
        if all_exist and not force:
            logger.info(f"All outputs exist for segment {segment_id}, skipping")
            return {
                'skipped': True,
                'reason': 'already_exists',
                'existing': existing
            }
        
        source_text = self.extract_source_text(segment_id, media_type)
        if not source_text:
            raise ValueError(f"Failed to extract source text for segment {segment_id}")
        
        logger.info(f"Extracted {len(source_text)} chars of source text")
        
        model_output = self.qwen.process_text(source_text, media_type)
        if not model_output:
            raise ValueError("Model processing failed to produce valid output")
        
        output_result = {
            'upserted': True,
            'cleaned_r2_key': cleaned_r2_key,
            'model_version': MODEL_VERSION
        }
        
        if not existing['cleaned_text'] or force:
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
            logger.info("Cleaned text already exists, skipped")
        
        if not existing['segment_summaries'] or force:
            summary_data = model_output['segment_summary']
            self.db.upsert_segment_summary(
                segment_id=segment_id,
                summary=summary_data['summary'],
                summary_short=summary_data['summary_short'],
                events=summary_data['events'],
                beats=summary_data['beats'],
                key_dialogue=summary_data['key_dialogue'],
                tone=summary_data['tone'],
                model_version=MODEL_VERSION
            )
            output_result['summary_upserted'] = True
        else:
            logger.info("Segment summary already exists, skipped")
        
        if not existing['segment_entities'] or force:
            self.db.upsert_segment_entities(
                segment_id=segment_id,
                entities=model_output['segment_entities'],
                model_version=MODEL_VERSION
            )
            output_result['entities_upserted'] = True
        else:
            logger.info("Segment entities already exists, skipped")
        
        if media_type == 'novel':
            character_updates = model_output.get('character_updates', [])
            if character_updates:
                work_characters = self.db.get_work_characters(work_id)
                char_stats = process_character_updates(
                    work_id=work_id,
                    work_characters=work_characters,
                    character_updates=character_updates,
                    segment_number=int(segment['number']),
                    model_version=MODEL_VERSION,
                    db_client=self.db
                )
                output_result['characters'] = char_stats
                logger.info(f"Character updates: {char_stats}")
        
        return output_result
    
    def run_once(self) -> bool:
        """
        Poll and process one job.
        
        Returns:
            True if a job was processed, False if queue empty
        """
        job = self.db.poll_next_job()
        
        if not job:
            return False
        
        job_id = job['id']
        attempt = job.get('attempt', 0)
        
        if attempt >= MAX_RETRIES_PER_JOB:
            logger.warning(f"Job {job_id} exceeded max retries ({MAX_RETRIES_PER_JOB}), marking failed")
            self.db.set_job_failed(job_id, f"Exceeded max retries ({MAX_RETRIES_PER_JOB})")
            return True
        
        self.db.set_job_running(job_id, attempt)
        
        try:
            output = self.process_job(job)
            self.db.set_job_success(job_id, output)
            logger.info(f"Job {job_id} completed successfully")
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            logger.error(f"Job {job_id} failed: {error_msg}")
            self.db.set_job_failed(job_id, error_msg)
        
        return True
    
    def run_forever(self):
        """Run the worker daemon loop."""
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


def main():
    """Entry point for the worker."""
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
