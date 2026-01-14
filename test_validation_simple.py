#!/usr/bin/env python
"""Simple test for validation flow."""

from nlp_worker.schema import validate_and_normalize

# Test case: personality as list (should convert to string)
test = {
    'segment_summary': {
        'summary': 'Test summary',
        'summary_short': 'Short',
        'events': [],
        'beats': [],
        'key_dialogue': [],
        'tone': {}
    },
    'segment_entities': {
        'characters': [], 'locations': [], 'items': [], 
        'time_refs': [], 'organizations': [], 'factions': [],
        'titles_ranks': [], 'skills': [], 'creatures': [],
        'concepts': [], 'relationships': [], 'emotions': [], 
        'keywords': []
    },
    'character_updates': [
        {
            'name': 'Arthur',
            'aliases': ['Art'],
            'facts': [
                'protagonist',
                'reincarnated from another world',
                'young child learning magic',
                'protective of his family'
            ]
        }
    ]
}

print("Testing validation with simple facts array...")
valid, normalized, err = validate_and_normalize(test)

print(f"\n✅ Valid: {valid}")
if err:
    print(f"❌ Error: {err}")
    exit(1)

char = normalized['character_updates'][0]
facts = char['facts']

print(f"\n📊 Results:")
print(f"  - Character name: {char['name']}")
print(f"  - Facts type: {type(facts)}")
print(f"  - Facts count: {len(facts)}")
print(f"  - Facts: {facts}")

if isinstance(facts, list) and all(isinstance(f, str) for f in facts):
    print(f"\n✅ SUCCESS! Facts is array of strings")
    for i, fact in enumerate(facts, 1):
        print(f"     {i}. {fact}")
else:
    print(f"\n❌ FAILED! Expected list of strings but got {type(facts)}")
    exit(1)
