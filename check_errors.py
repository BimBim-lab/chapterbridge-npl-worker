"""Check error messages from failed jobs."""
from nlp_worker.supabase_client import get_supabase_client
from dotenv import load_dotenv

load_dotenv()

db = get_supabase_client()
result = db.client.table('pipeline_jobs').select('id,segment_id,error').eq(
    'status', 'failed'
).order('created_at', desc=True).limit(3).execute()

for r in result.data:
    print(f"Segment: {r['segment_id']}")
    print(f"Error: {r['error'][:500] if r['error'] else 'No error'}")
    print("-" * 80)
