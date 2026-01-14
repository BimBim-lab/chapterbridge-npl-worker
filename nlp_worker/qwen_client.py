"""OpenAI-compatible client for vLLM server running Qwen model."""

import os
import json
import time
from typing import Dict, Any, Optional, Tuple
from openai import OpenAI, APIError, APIConnectionError, APITimeoutError, RateLimitError
from .schema import (
    get_vllm_guided_json_schema, 
    validate_and_normalize, 
    build_repair_prompt,
    normalize_model_output
)
from .utils import get_logger

logger = get_logger(__name__)

MODEL_TIMEOUT = int(os.environ.get('MODEL_TIMEOUT_SECONDS', '360'))
MODEL_MAX_RETRIES = int(os.environ.get('MODEL_MAX_RETRIES', '2'))


def build_system_prompt(media_type: str, work_title: Optional[str] = None) -> str:
    """Build the system prompt for NLP processing."""
    work_context = ""
    if work_title:
        work_context = f"""\n\n⚠️ WORK: "{work_title}" - Extract ONLY from the text below. NO external knowledge.\n"""
    
    char_instruction = ""
    char_example = ""
    if media_type == 'novel':
        char_instruction = """
- character_updates: Array of character objects. For EACH **NAMED** character:
  * name: Character's REAL NAME as written in text (e.g., "Arthur Leywin", "Alice Leywin")
    ⚠️ NEVER use generic terms ("ayah", "pria", "the protagonist") or names from other stories
  * aliases: Array of alternate names/nicknames (empty array [] if none)
  * facts: Array of SHORT fact strings about this character extracted from THIS segment:
    - Role: "protagonist", "antagonist", "supporting", etc.
    - Occupation: "student", "hunter E-rank", "doctor", "princess"
    - Traits: "brave", "protective", "smart", "quiet"
    - Abilities: "has magic", "expert swordsman", "can fly"
    - Goals: "wants to protect family", "seeking revenge"
    - Relationships: "son of X", "friend of Y"
    - Appearance: "white hair", "scar on face"
    - Any other notable facts
  
  ⚠️ CRITICAL: Only extract characters with ACTUAL NAMES in the text"""
        
        char_example = """
  "character_updates": [
    {
      "name": "Arthur Leywin",
      "aliases": ["Art"],
      "facts": [
        "protagonist",
        "reincarnated from another world",
        "young child",
        "learning magic",
        "protective of his family"
      ]
    }
  ]
  
  // Use actual names from the text, extract simple facts as strings"""
    else:
        char_instruction = "- character_updates: Return empty array [] (not applicable for this media type)"
        char_example = '  "character_updates": []'

    return f"""You are an expert NLP processor for story content analysis. Your task is to process raw text from stories and produce structured analysis output.{work_context}

TASK: Analyze the provided story text and output a JSON object with the following structure:

1. **segment_summary**: Analyze the narrative:
   - summary: Detailed factual summary of events (2-4 paragraphs)
   - summary_short: 1-2 sentence headline
   - events: Chronological bullet list of key events (array of strings)
   - beats: Story structure beats (array of objects with type and description)
   - key_dialogue: Important quotes (array of objects with speaker, text, optional to and importance)
   - tone: Object with primary (string), secondary (array of strings), and intensity (0-1 number)

2. **segment_entities**: Extract all entities. EVERY field MUST be an array (never null):
   - characters, locations, items, time_refs, organizations, factions, titles_ranks,
   - skills, creatures, concepts, relationships, emotions, keywords

3. **character_updates** (media_type: {media_type}):
{char_instruction}

EXAMPLE OUTPUT STRUCTURE:
{{
  "segment_summary": {{...}},
  "segment_entities": {{...}},
{char_example}
}}

CRITICAL RULES:
- ⚠️ Extract ONLY from the provided text. NO external knowledge, NO other stories.
- ⚠️ Character names MUST be actual proper nouns from the text. NO "the protagonist", NO generic terms.
- All segment_entities fields MUST be arrays (use [] if empty).
- Empty string "" for profile fields not mentioned in text.
- OUTPUT ONLY VALID JSON."""


def build_user_prompt(source_text: str, media_type: str, work_title: Optional[str] = None) -> str:
    """Build the user prompt with source text."""
    return f"""Analyze this {media_type} content and output structured JSON.

---BEGIN CONTENT---
{source_text}
---END CONTENT---

Extract ONLY from the content above. Output valid JSON only."""


class QwenClient:
    """Client for vLLM OpenAI-compatible API with robust retry logic."""
    
    def __init__(self):
        self.base_url = os.environ.get('VLLM_BASE_URL', 'http://localhost:8000/v1')
        self.api_key = os.environ.get('VLLM_API_KEY', 'token-anything')
        self.model = os.environ.get('VLLM_MODEL', 'qwen2.5-7b')
        self.timeout = MODEL_TIMEOUT
        self.max_retries = MODEL_MAX_RETRIES
        
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout
        )
        logger.info(f"QwenClient initialized with model: {self.model}, timeout: {self.timeout}s")
    
    def _should_retry(self, error: Exception) -> bool:
        """Determine if an error should trigger a retry."""
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            return True
        if isinstance(error, RateLimitError):
            return True
        if isinstance(error, APIError):
            status = getattr(error, 'status_code', 0) or 0
            return status >= 500 or status == 429
        return False
    
    def _call_model(
        self,
        messages: list,
        max_tokens: int,
        temperature: float
    ) -> Tuple[Optional[str], float, int]:
        """
        Call the model with retry logic.
        
        Returns:
            (response_content, latency_ms, retry_count)
        """
        guided_json = get_vllm_guided_json_schema()
        retry_count = 0
        last_error = None
        
        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    # Disable KV cache reuse to prevent cross-contamination
                    extra_body={
                        "use_beam_search": False,
                        "ignore_eos": False
                    }
                    # Note: Disabled guided_json for now as it may cause issues with long texts
                    # extra_body={
                    #     "guided_json": guided_json,
                    #     "guided_decoding_backend": "outlines"
                    # }
                )
                
                latency_ms = (time.time() - start_time) * 1000
                content = response.choices[0].message.content
                return content, latency_ms, retry_count
                
            except Exception as e:
                last_error = e
                latency_ms = (time.time() - start_time) * 1000
                
                if self._should_retry(e) and attempt < self.max_retries:
                    retry_count += 1
                    wait_time = min(2 ** attempt * 2, 30)
                    logger.warning(f"Model call failed (attempt {attempt + 1}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Model call failed after {attempt + 1} attempts: {e}")
                    raise
        
        raise last_error
    
    def _repair_json(
        self,
        invalid_content: str,
        error: str,
        max_tokens: int
    ) -> Optional[str]:
        """Attempt to repair invalid JSON by calling model again."""
        repair_prompt = build_repair_prompt(invalid_content, error)
        
        logger.info("Attempting JSON repair with model...")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a JSON repair assistant. Fix the invalid JSON to match the schema."},
                    {"role": "user", "content": repair_prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"JSON repair call failed: {e}")
            return None
    
    def process_text(
        self, 
        source_text: str, 
        media_type: str,
        work_title: Optional[str] = None,
        max_tokens: int = 16000,
        temperature: float = 0.3
    ) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        """
        Process source text through Qwen model with structured output.
        
        Args:
            source_text: The text to analyze
            media_type: 'novel', 'manhwa', or 'anime'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
        
        Returns:
            (normalized_output, stats_dict)
            normalized_output is None if processing failed
            stats_dict contains metrics for logging
        """
        stats = {
            'input_chars': len(source_text),
            'input_tokens_est': len(source_text) // 4,
            'output_chars': 0,
            'model_latency_ms': 0,
            'retries_count': 0,
            'repair_attempted': False,
            'repair_succeeded': False
        }
        
        system_prompt = build_system_prompt(media_type, work_title)
        user_prompt = build_user_prompt(source_text, media_type, work_title)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        logger.info(f"Sending {stats['input_chars']} chars ({stats['input_tokens_est']} est tokens) to model for {media_type}")
        
        try:
            content, latency_ms, retry_count = self._call_model(messages, max_tokens, temperature)
            stats['model_latency_ms'] = int(latency_ms)
            stats['retries_count'] = retry_count
            stats['output_chars'] = len(content) if content else 0
            
        except Exception as e:
            logger.error(f"Model API call failed: {e}")
            return None, stats
        
        try:
            result = json.loads(content)
            logger.debug(f"Parsed JSON keys: {list(result.keys())}")
            if 'character_updates' in result:
                char_updates = result.get('character_updates')
                logger.debug(f"character_updates type: {type(char_updates)}, value: {char_updates}")
                if isinstance(char_updates, list) and char_updates:
                    logger.debug(f"First item type: {type(char_updates[0])}, value: {char_updates[0]}")
            logger.debug(f"Parsed JSON keys: {list(result.keys())}")
            if 'character_updates' in result:
                char_updates = result.get('character_updates')
                logger.debug(f"character_updates type: {type(char_updates)}, value: {char_updates}")
                if isinstance(char_updates, list) and char_updates:
                    logger.debug(f"First item type: {type(char_updates[0])}, value: {char_updates[0]}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse model response as JSON: {e}")
            logger.warning(f"Raw response content (first 1000 chars): {content[:1000]!r}")
            stats['repair_attempted'] = True
            
            repaired = self._repair_json(content, str(e), max_tokens)
            if repaired:
                try:
                    result = json.loads(repaired)
                    stats['repair_succeeded'] = True
                    logger.info("JSON repair succeeded")
                except json.JSONDecodeError:
                    logger.error("JSON repair also failed")
                    return None, stats
            else:
                return None, stats
        
        is_valid, normalized, error = validate_and_normalize(result)
        
        if not is_valid:
            logger.warning(f"Validation issue: {error}")
            stats['repair_attempted'] = True
            
            repaired = self._repair_json(json.dumps(result), error, max_tokens)
            if repaired:
                try:
                    repaired_result = json.loads(repaired)
                    is_valid2, normalized, error2 = validate_and_normalize(repaired_result)
                    if is_valid2:
                        stats['repair_succeeded'] = True
                        logger.info("Schema repair succeeded")
                except Exception:
                    pass
            
            if not stats['repair_succeeded']:
                logger.error(f"Validation failed after repair: {error}")
                return None, stats
        
        logger.info(f"Model processing completed (latency: {stats['model_latency_ms']}ms, retries: {stats['retries_count']})")
        return normalized, stats


_qwen_client: Optional[QwenClient] = None

def get_qwen_client() -> QwenClient:
    """Get singleton QwenClient instance."""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenClient()
    return _qwen_client
