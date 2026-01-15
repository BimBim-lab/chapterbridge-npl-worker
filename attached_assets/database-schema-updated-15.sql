-- Pipeline Admin Dashboard - Complete Database Schema
-- Last updated: January 2026
-- Use this file as reference when building workers

-- ============================================
-- EXTENSIONS
-- ============================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================
-- CORE TABLES
-- ============================================

-- Scraper Templates
CREATE TABLE scraper_templates (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  description TEXT,
  template_type TEXT NOT NULL CHECK (template_type IN ('wp_manga', 'custom_html', 'custom_json', 'subtitle')),
  config JSONB NOT NULL DEFAULT '{}',
  version TEXT NOT NULL DEFAULT '1.0.0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sources (scraping targets)
CREATE TABLE sources (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  media_type TEXT NOT NULL CHECK (media_type IN ('novel', 'manhwa', 'anime')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
  protection_level TEXT NOT NULL DEFAULT 'none' CHECK (protection_level IN ('none', 'mild', 'heavy')),
  rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
  default_template_id UUID REFERENCES scraper_templates(id) ON DELETE SET NULL,
  extractor_version TEXT NOT NULL DEFAULT '1.0.0',
  last_run_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Works (titles/series)
CREATE TABLE works (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT NOT NULL,
  slug TEXT,
  alt_titles JSONB NOT NULL DEFAULT '[]',
  synopsis TEXT,
  synopsis_short TEXT,
  genres JSONB NOT NULL DEFAULT '[]',
  tags JSONB NOT NULL DEFAULT '[]',
  content_rating TEXT NOT NULL DEFAULT 'unknown',
  status TEXT NOT NULL DEFAULT 'unknown',
  year INTEGER,
  authors JSONB NOT NULL DEFAULT '[]',
  cover_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_works_slug_unique ON works(slug);

-- Characters (extracted/tracked characters per work)
CREATE TABLE characters (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  aliases JSONB NOT NULL DEFAULT '[]',
  character_facts JSONB NOT NULL DEFAULT '[]',
  description TEXT,
  model_version TEXT NOT NULL DEFAULT 'v0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_characters_work_id ON characters(work_id);
CREATE UNIQUE INDEX idx_characters_work_name_ci ON characters(work_id, LOWER(name));
CREATE INDEX idx_characters_work_id_name ON characters(work_id, name);

-- Editions (different versions of a work - novel vs manhwa vs anime)
CREATE TABLE editions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  work_id UUID NOT NULL REFERENCES works(id) ON DELETE CASCADE,
  media_type TEXT NOT NULL CHECK (media_type IN ('novel', 'manhwa', 'anime')),
  provider TEXT NOT NULL,
  canonical_url TEXT,
  is_official BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_editions_work_id ON editions(work_id);

-- Segments (chapters/episodes)
CREATE TABLE segments (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  segment_type TEXT NOT NULL CHECK (segment_type IN ('chapter', 'episode')),
  number NUMERIC NOT NULL,
  title TEXT,
  canonical_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (edition_id, segment_type, number)
);
CREATE INDEX idx_segments_edition_id ON segments(edition_id);

-- Assets (files stored in R2)
-- Note: Raw files are not publicly accessible - only processed data is served to users via API
CREATE TABLE assets (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  provider TEXT NOT NULL DEFAULT 'cloudflare_r2',
  bucket TEXT NOT NULL,
  r2_key TEXT NOT NULL UNIQUE,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('raw_image', 'raw_subtitle', 'raw_html', 'ocr_json', 'cleaned_text', 'cleaned_json', 'other')),
  content_type TEXT,
  bytes BIGINT,
  sha256 TEXT,
  upload_source TEXT NOT NULL DEFAULT 'manual' CHECK (upload_source IN ('pipeline', 'manual', 'import')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_assets_r2_key ON assets(r2_key);
CREATE INDEX idx_assets_asset_type ON assets(asset_type);

-- Segment Assets (junction table)
CREATE TABLE segment_assets (
  segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  role TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (segment_id, asset_id)
);

-- Users (admin tracking)
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  name TEXT,
  role TEXT NOT NULL DEFAULT 'admin',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- PIPELINE TABLES
-- ============================================

-- Pipeline Jobs (job queue)
CREATE TABLE pipeline_jobs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  job_type TEXT NOT NULL CHECK (job_type IN ('scrape', 'clean', 'summarize', 'entities', 'embed', 'match', 'sync_assets')),
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'success', 'failed')),
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  work_id UUID REFERENCES works(id) ON DELETE SET NULL,
  edition_id UUID REFERENCES editions(id) ON DELETE SET NULL,
  segment_id UUID REFERENCES segments(id) ON DELETE SET NULL,
  input JSONB NOT NULL DEFAULT '{}',
  output JSONB,
  attempt INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);
CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX idx_pipeline_jobs_job_type ON pipeline_jobs(job_type);
CREATE INDEX idx_pipeline_jobs_created_at ON pipeline_jobs(created_at DESC);

-- ============================================
-- NLP PIPELINE TABLES
-- ============================================

-- Segment Summaries (AI-generated summaries + key events)
CREATE TABLE segment_summaries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  summary TEXT NOT NULL,
  summary_short TEXT,
  events JSONB NOT NULL DEFAULT '[]',
  model_version TEXT NOT NULL DEFAULT 'v0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(segment_id)
);
CREATE INDEX idx_segment_summaries_segment ON segment_summaries(segment_id);

-- Segment Entities (extracted characters, locations, keywords, time context)
CREATE TABLE segment_entities (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  characters JSONB NOT NULL DEFAULT '[]',
  locations JSONB NOT NULL DEFAULT '[]',
  keywords JSONB NOT NULL DEFAULT '[]',
  time_context TEXT NOT NULL DEFAULT 'unknown',
  model_version TEXT NOT NULL DEFAULT 'v0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(segment_id)
);
CREATE INDEX idx_segment_entities_segment ON segment_entities(segment_id);

-- Segment Embeddings (vector embeddings for similarity search)
CREATE TABLE segment_embeddings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  embedding_summary VECTOR(1536),
  embedding_events VECTOR(1536),
  model_version TEXT NOT NULL DEFAULT 'v0',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(segment_id)
);
CREATE INDEX idx_segment_embeddings_segment ON segment_embeddings(segment_id);
CREATE INDEX idx_embedding_summary_ivff ON segment_embeddings 
  USING ivfflat (embedding_summary vector_l2_ops) WITH (lists = 100);

-- Segment Mappings (cross-edition alignment)
CREATE TABLE segment_mappings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  from_segment_id UUID NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
  to_edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
  to_segment_start NUMERIC NOT NULL,
  to_segment_end NUMERIC NOT NULL,
  confidence FLOAT NOT NULL,
  evidence JSONB NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'likely', 'verified', 'disputed')),
  created_by UUID REFERENCES users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(from_segment_id, to_edition_id)
);
CREATE INDEX idx_segment_mappings_from ON segment_mappings(from_segment_id);
CREATE INDEX idx_segment_mappings_to_edition ON segment_mappings(to_edition_id);
CREATE INDEX idx_segment_mappings_status ON segment_mappings(status);

-- ============================================
-- TRIGGERS (auto-update updated_at)
-- ============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_segment_summaries_updated_at
  BEFORE UPDATE ON segment_summaries
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_segment_entities_updated_at
  BEFORE UPDATE ON segment_entities
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_segment_embeddings_updated_at
  BEFORE UPDATE ON segment_embeddings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_segment_mappings_updated_at
  BEFORE UPDATE ON segment_mappings
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_works_updated_at
  BEFORE UPDATE ON works
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_characters_updated_at
  BEFORE UPDATE ON characters
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
works.alt_titles:
[
  "Solo Leveling",
  "나 혼자만 레벨업",
  "Only I Level Up"
]

works.genres:
[
  "Action",
  "Fantasy",
  "Adventure"
]

works.tags:
[
  "System",
  "Overpowered MC",
  "Dungeon",
  "Regression"
]

works.authors:
[
  {"name": "Chugong", "role": "author"},
  {"name": "DUBU", "role": "artist"}
]

characters.aliases:
[
  "Sung Jin-Woo",
  "성진우",
  "Jinwoo",
  "Shadow Monarch"
]

characters.character_facts:
[
  {
    "chapter": 1,
    "fact": "E-rank hunter, weakest of the weak",
    "source": "novel_chapter_1"
  },
  {
    "chapter": 2,
    "fact": "Survived double dungeon and gained the System",
    "source": "novel_chapter_2"
  },
  {
    "chapter": 50,
    "fact": "Became S-rank hunter",
    "source": "novel_chapter_50"
  }
]

-- JSONB STRUCTURES REFERENCE
-- ============================================

/*
scraper_templates.config:
{
  "selectors": {
    "title": "h1.entry-title",
    "content": "div.reading-content",
 

segment_summaries.events:
[
  "Sung Jinwoo enters the double dungeon",
  "The statue soldiers attack the hunters",
  "Jinwoo sacrifices himself to save others"
]


segment_entities.characters:
[
  {"name": "Sung Jinwoo", "role": "protagonist", "mentions": 45},
  {"name": "Yoo Jinho", "role": "supporting", "mentions": 12}
]

segment_entities.locations:
[
  {"name": "Seoul", "type": "city", "mentions": 8}
]

segment_entities.keywords:
[
  {"term": "leveling", "relevance": 0.98, "frequency": 15},
  {"term": "dungeon", "relevance": 0.92, "frequency": 25}
]

segment_entities.time_context:
"present" | "flashback" | "future" | "unknown"

segment_mappings.evidence:
[
  {"type": "entity_match", "score": 0.95, "details": "Character names match"},
  {"type": "event_match", "score": 0.88, "details": "Key plot points align"}
]

pipeline_jobs.input:
{
  "url": "https://example.com/chapter-1",
  "template_id": "uuid-here"
}

pipeline_jobs.output:
{
  "asset_ids": ["uuid1", "uuid2"],
  "text_length": 5000
}
*/
