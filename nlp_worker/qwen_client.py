"""OpenAI-compatible client for vLLM server running Qwen model."""

import os
import json
from typing import Dict, Any, Optional
from openai import OpenAI
from .schema import get_vllm_guided_json_schema, validate_model_output
from .utils import get_logger, retry_with_backoff

logger = get_logger(__name__)


def build_system_prompt(media_type: str) -> str:
    """Build the system prompt for NLP processing."""
    char_instruction = ""
    if media_type == 'novel':
        char_instruction = """
- character_updates: For each significant character, provide:
  - name: canonical name
  - aliases: list of alternate names/titles used
  - character_facts: list of facts learned in this chapter with chapter reference
  - description: brief physical/personality description if available"""
    else:
        char_instruction = "- character_updates: Return empty array (not applicable for this media type)"

    return f"""You are an expert NLP processor for story content analysis. Your task is to process raw text from stories and produce structured analysis output.

TASK: Analyze the provided story text and output a JSON object with the following structure:

1. **cleaned_text**: Clean the input text by:
   - Removing watermarks, credits, and boilerplate
   - Fixing spacing and punctuation issues
   - Removing duplicate lines
   - Keeping all story content in correct reading order
   - Do NOT summarize - preserve the full narrative text

2. **segment_summary**: Analyze the narrative:
   - summary: Detailed factual summary of events (2-4 paragraphs)
   - summary_short: 1-2 sentence headline
   - events: Chronological bullet list of key events
   - beats: Story structure beats (setup, conflict, twist, climax, resolution)
   - key_dialogue: Important quotes with speaker, optional target, and importance level
   - tone: Primary tone, secondary tones array, and intensity (0-1)

3. **segment_entities**: Extract all entities with minimal metadata:
   - characters: named characters appearing
   - locations: places mentioned
   - items: significant objects
   - time_refs: temporal references
   - organizations: groups/institutions
   - factions: competing groups
   - titles_ranks: titles or ranks mentioned
   - skills: abilities/powers
   - creatures: non-human entities
   - concepts: abstract concepts important to the story
   - relationships: connections between characters
   - emotions: emotional themes
   - keywords: important terms

4. **character_updates** (media_type: {media_type}):
{char_instruction}

OUTPUT ONLY VALID JSON. No markdown, no explanation, just the JSON object."""


def build_user_prompt(source_text: str, media_type: str) -> str:
    """Build the user prompt with source text."""
    return f"""Analyze this {media_type} content and produce the structured JSON output:

---BEGIN CONTENT---
{source_text}
---END CONTENT---

Remember: Output ONLY valid JSON matching the required schema."""


class QwenClient:
    """Client for vLLM OpenAI-compatible API."""
    
    def __init__(self):
        self.base_url = os.environ.get('VLLM_BASE_URL', 'http://localhost:8000/v1')
        self.api_key = os.environ.get('VLLM_API_KEY', 'token-anything')
        self.model = os.environ.get('VLLM_MODEL', 'qwen2.5-7b')
        
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )
        logger.info(f"QwenClient initialized with model: {self.model}")
    
    @retry_with_backoff(max_retries=3, base_delay=2.0)
    def process_text(
        self, 
        source_text: str, 
        media_type: str,
        max_tokens: int = 16384,
        temperature: float = 0.3
    ) -> Optional[Dict[str, Any]]:
        """
        Process source text through Qwen model with structured output.
        
        Args:
            source_text: The text to analyze
            media_type: 'novel', 'manhwa', or 'anime'
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
        
        Returns:
            Parsed and validated output dict, or None if failed
        """
        system_prompt = build_system_prompt(media_type)
        user_prompt = build_user_prompt(source_text, media_type)
        
        logger.info(f"Sending {len(source_text)} chars to model for {media_type} processing")
        
        try:
            guided_json = get_vllm_guided_json_schema()
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body={
                    "guided_json": guided_json,
                    "guided_decoding_backend": "outlines"
                }
            )
            
            content = response.choices[0].message.content
            logger.debug(f"Received {len(content)} chars from model")
            
            try:
                result = json.loads(content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse model response: {e}")
                logger.debug(f"Raw response: {content[:500]}...")
                return None
            
            is_valid, error = validate_model_output(result)
            if not is_valid:
                logger.error(f"Model output validation failed: {error}")
                return None
            
            logger.info("Model processing completed successfully")
            return result
            
        except Exception as e:
            logger.error(f"Model API call failed: {e}")
            raise


_qwen_client: Optional[QwenClient] = None

def get_qwen_client() -> QwenClient:
    """Get singleton QwenClient instance."""
    global _qwen_client
    if _qwen_client is None:
        _qwen_client = QwenClient()
    return _qwen_client
