#!/usr/bin/env python3
"""Verification script to check NLP worker imports and configuration."""

import sys

def main():
    print("=" * 60)
    print("ChapterBridge NLP Pack Worker - Verification")
    print("=" * 60)
    
    errors = []
    
    print("\n[1/6] Checking Python version...")
    print(f"  Python {sys.version}")
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ required")
    else:
        print("  OK")
    
    print("\n[2/6] Checking core dependencies...")
    try:
        import boto3
        print(f"  boto3: {boto3.__version__}")
    except ImportError as e:
        errors.append(f"boto3: {e}")
    
    try:
        from supabase import create_client
        print("  supabase: OK")
    except ImportError as e:
        errors.append(f"supabase: {e}")
    
    try:
        import openai
        print(f"  openai: {openai.__version__}")
    except ImportError as e:
        errors.append(f"openai: {e}")
    
    try:
        from bs4 import BeautifulSoup
        print("  beautifulsoup4: OK")
    except ImportError as e:
        errors.append(f"beautifulsoup4: {e}")
    
    try:
        import pydantic
        print(f"  pydantic: {pydantic.__version__}")
    except ImportError as e:
        errors.append(f"pydantic: {e}")
    
    print("\n[3/6] Checking worker modules...")
    try:
        from nlp_worker import utils
        print("  nlp_worker.utils: OK")
    except ImportError as e:
        errors.append(f"nlp_worker.utils: {e}")
    
    try:
        from nlp_worker import schema
        print("  nlp_worker.schema: OK")
    except ImportError as e:
        errors.append(f"nlp_worker.schema: {e}")
    
    try:
        from nlp_worker import key_builder
        print("  nlp_worker.key_builder: OK")
    except ImportError as e:
        errors.append(f"nlp_worker.key_builder: {e}")
    
    try:
        from nlp_worker.text_extractors import extract_subtitle_text, extract_novel_text, extract_manhwa_text
        print("  nlp_worker.text_extractors: OK")
    except ImportError as e:
        errors.append(f"nlp_worker.text_extractors: {e}")
    
    try:
        from nlp_worker import character_merge
        print("  nlp_worker.character_merge: OK")
    except ImportError as e:
        errors.append(f"nlp_worker.character_merge: {e}")
    
    print("\n[4/6] Testing text extractors...")
    try:
        from nlp_worker.text_extractors import extract_subtitle_text, extract_novel_text
        from nlp_worker.utils import count_paragraphs, count_subtitle_blocks
        
        test_srt = """1
00:00:01,000 --> 00:00:04,000
Hello, this is a test.

2
00:00:05,000 --> 00:00:08,000
[MUSIC]

3
00:00:09,000 --> 00:00:12,000
This is dialogue text.
"""
        result = extract_subtitle_text(test_srt, "test.srt")
        blocks = count_subtitle_blocks(test_srt)
        print(f"  SRT extraction: {len(result)} chars, {blocks} blocks")
        
        test_html = """
<html>
<head><style>.ad { display: none; }</style></head>
<body>
<nav>Navigation</nav>
<article>
<p>This is the first paragraph of the story.</p>
<p>This is the second paragraph with more content.</p>
</article>
<footer>Footer content</footer>
</body>
</html>
"""
        result = extract_novel_text(test_html)
        paras = count_paragraphs(result)
        print(f"  HTML extraction: {len(result)} chars, {paras} paragraphs")
        print("  Extractors: OK")
    except Exception as e:
        errors.append(f"Text extractors: {e}")
    
    print("\n[5/6] Testing Pydantic schema validation...")
    try:
        from nlp_worker.schema import validate_and_normalize, normalize_model_output, NLPOutputModel
        
        test_output = {
            "cleaned_text": "This is test content.",
            "segment_summary": {
                "summary": "A test summary.",
                "summary_short": "Test",
                "events": ["Event 1", "Event 2"],
                "beats": [{"type": "setup", "description": "Beginning"}],
                "key_dialogue": [{"speaker": "Alice", "text": "Hello"}],
                "tone": {"primary": "neutral", "secondary": [], "intensity": 0.5}
            },
            "segment_entities": {
                "characters": ["Alice"],
                "locations": [],
                "items": None,
                "time_refs": [],
                "organizations": [],
                "factions": [],
                "titles_ranks": [],
                "skills": [],
                "creatures": [],
                "concepts": [],
                "relationships": [],
                "emotions": [],
                "keywords": []
            }
        }
        
        is_valid, normalized, error = validate_and_normalize(test_output)
        print(f"  Validation: {'passed' if is_valid else 'failed'}")
        
        if normalized['segment_entities']['items'] == []:
            print("  Null-to-list normalization: OK")
        else:
            errors.append("Null-to-list normalization failed")
        
        incomplete = {"cleaned_text": "Test", "segment_summary": {}, "segment_entities": {}}
        normalized2 = normalize_model_output(incomplete)
        if all(isinstance(normalized2['segment_entities'][k], list) for k in ['characters', 'locations', 'items']):
            print("  Empty field defaults: OK")
        else:
            errors.append("Empty field defaults failed")
        
        print("  Schema: OK")
    except Exception as e:
        import traceback
        traceback.print_exc()
        errors.append(f"Schema validation: {e}")
    
    print("\n[6/6] Testing key builder...")
    try:
        from nlp_worker.key_builder import build_cleaned_text_key
        
        key = build_cleaned_text_key(
            media_type="novel",
            work_id="abc123",
            edition_id="def456",
            segment_type="chapter",
            segment_number=13
        )
        expected = "derived/novel/abc123/def456/chapter-0013/cleaned.txt"
        if key == expected:
            print(f"  Key format: OK ({key})")
        else:
            errors.append(f"Key format mismatch: {key} != {expected}")
    except Exception as e:
        errors.append(f"Key builder: {e}")
    
    print("\n" + "=" * 60)
    if errors:
        print("ERRORS FOUND:")
        for err in errors:
            print(f"  - {err}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("All checks passed!")
        print("=" * 60)
        print("\nTo run the worker, set environment variables:")
        print("  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")
        print("  R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        print("  VLLM_BASE_URL, VLLM_API_KEY, VLLM_MODEL")
        print("\nNew features:")
        print("  - Dry-run mode: python -m nlp_worker.main --segment-id <uuid> --no-write")
        print("  - Strict schema validation with auto-repair")
        print("  - Partial idempotency (only writes missing outputs)")
        print("  - Metrics in pipeline_jobs.output.stats")
        print("\nThen run:")
        print("  python -m nlp_worker.enqueue  # To enqueue jobs")
        print("  python -m nlp_worker.main     # To start worker daemon")
        sys.exit(0)


if __name__ == "__main__":
    main()
