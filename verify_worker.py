#!/usr/bin/env python3
"""Verification script to check NLP worker imports and configuration."""

import sys

def main():
    print("=" * 60)
    print("ChapterBridge NLP Pack Worker - Verification")
    print("=" * 60)
    
    errors = []
    
    print("\n[1/5] Checking Python version...")
    print(f"  Python {sys.version}")
    if sys.version_info < (3, 10):
        errors.append("Python 3.10+ required")
    else:
        print("  OK")
    
    print("\n[2/5] Checking core dependencies...")
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
        import jsonschema
        print(f"  jsonschema: {jsonschema.__version__}")
    except ImportError as e:
        errors.append(f"jsonschema: {e}")
    
    print("\n[3/5] Checking worker modules...")
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
    
    print("\n[4/5] Testing text extractors...")
    try:
        from nlp_worker.text_extractors import extract_subtitle_text, extract_novel_text
        
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
        print(f"  SRT extraction: {len(result)} chars extracted")
        
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
        print(f"  HTML extraction: {len(result)} chars extracted")
        print("  Extractors: OK")
    except Exception as e:
        errors.append(f"Text extractors: {e}")
    
    print("\n[5/5] Checking JSON schema...")
    try:
        from nlp_worker.schema import get_vllm_guided_json_schema, validate_model_output
        schema = get_vllm_guided_json_schema()
        print(f"  Schema properties: {list(schema.get('properties', {}).keys())}")
        print("  Schema: OK")
    except Exception as e:
        errors.append(f"Schema: {e}")
    
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
        print("\nThen run:")
        print("  python -m nlp_worker.enqueue  # To enqueue jobs")
        print("  python -m nlp_worker.main     # To start worker daemon")
        sys.exit(0)


if __name__ == "__main__":
    main()
