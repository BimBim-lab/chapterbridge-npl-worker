#!/usr/bin/env python3
"""Quick test script for vLLM connection"""
import os
from openai import OpenAI

# Test vLLM connection
base_url = os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
api_key = os.getenv("VLLM_API_KEY", "token-anything")

print(f"Testing connection to: {base_url}")
print(f"Using API key: {api_key[:10]}...")

try:
    client = OpenAI(base_url=base_url, api_key=api_key)
    
    print("\n1. Listing models...")
    models = client.models.list()
    print(f"   ✓ Found {len(models.data)} model(s)")
    for model in models.data:
        print(f"     - {model.id}")
    
    print("\n2. Testing chat completion...")
    response = client.chat.completions.create(
        model="qwen2.5-7b",
        messages=[{"role": "user", "content": "Say 'Hello World' in one sentence."}],
        max_tokens=20,
        temperature=0.7
    )
    
    content = response.choices[0].message.content
    print(f"   ✓ Response: {content}")
    print(f"   ✓ Tokens used: {response.usage.total_tokens}")
    
    print("\n✅ All tests passed! vLLM server is working correctly.")
    
except Exception as e:
    print(f"\n❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
