# Holographic Memory Provider

Local SQLite fact store with FTS5 search, trust scoring, entity resolution, and HRR-based compositional retrieval.

## Requirements

None — uses SQLite (always available). NumPy optional for HRR algebra.

## Setup

```bash
hermes memory setup    # select "holographic"
```

Or manually:
```bash
hermes config set memory.provider holographic
```

## Config

Config in `config.yaml` under `plugins.hermes-memory-store`:

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | `$HERMES_HOME/memory_store.db` | SQLite database path |
| `auto_extract` | `false` | Auto-extract facts at session end |
| `default_trust` | `0.5` | Default trust score for new facts |
| `hrr_dim` | `1024` | HRR vector dimensions |

## Tools

| Tool | Description |
|------|-------------|
| `fact_store` | 10 actions: add, retain, search, probe, related, reason, contradict, update, remove, list |
| `fact_feedback` | Rate facts as helpful/unhelpful (trains trust scores) |

### `fact_store(action='retain')`

Store a raw document/article and extract atomic facts from it.

- `content` — the raw document text (required).
- `source` — optional source label, e.g. URL or filename.
- `category` — one of `user_pref`, `project`, `tool`, `general`.

The original text is persisted in the `documents` table and deduplicated by
SHA256 hash. Extracted facts are linked back to the source document via
`source_doc_id`. When no LLM extractor is configured, a local fallback
extractor is used; fallback facts receive a lower initial trust score.

## Development / Evaluation

The repository includes standalone evaluation scripts under the project root
(e.g. `batch_retain_eval.py`, `corpus_audit.py`). They are **not** part of the
hermes runtime and require an OpenAI-compatible LLM endpoint only when run
with `--llm deepseek`.

Copy `.env.example` to `.env` and set your key once:

```bash
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Then load it before running eval scripts:

```bash
source .env
python batch_retain_eval.py --llm deepseek
# or
python corpus_audit.py --llm deepseek
```

`.env` is already ignored by Git; **never commit API keys** to the repository.
