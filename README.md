# AI Breeding Scientist

This repository is being adapted into a grain-breeding-focused AI breeding scientist: a multi-agent system that takes a natural-language crop-improvement goal and produces evidence-grounded, pairwise-calibrated, breeding-actionable hypotheses.

The current workflow is specialized for crop breeding, quantitative genetics, genomic selection, field-trial design, genotype-by-environment effects, local germplasm constraints, and practical breeding-cycle decisions.

Example goals:

```bash
co-scientist run "Identify breeding hypotheses to improve wheat drought tolerance without reducing grain yield" \
  --n 3 --budget-usd 2.0 --wall-clock 600

co-scientist run "Design selection-actionable hypotheses for improving maize nitrogen-use efficiency across rainfed environments"
```

The system uses its own six-agent architecture and breeding-specific
prioritization mechanism, with local evidence graph, RAG, germplasm, marker,
QTL, and validation-planning layers designed around crop-improvement work.

The six breeding-scientist agents:

- **Goal Interpreter** — turns a natural-language breeding request into crop, trait, environment, material constraints, hypothesis-count limits, and success criteria.
- **Evidence Curator** — builds a traceable Breeding Evidence Graph from local knowledge bases, KG/RAG evidence, germplasm records, field records, and external literature.
- **Breeding Designer** — designs and revises breeding hypotheses as structured design cards.
- **Validation Planner** — converts hypotheses into marker, phenotype, field-trial, and crossing-plan validation routes.
- **Risk Reviewer** — reviews evidence strength, contradictions, deployment risk, GxE uncertainty, feasibility, and missing local validation.
- **Iteration Orchestrator** — schedules follow-up evidence collection, hypothesis repair, expansion, pruning, and final prioritization.

A **Supervisor** schedules these agents through a durable SQLite-backed queue with bounded concurrency. The six agents are not a fixed one-pass chain: after the first pass, the Iteration Orchestrator can reopen evidence collection, repair weak hypotheses, ask for validation detail, prune low-quality routes, or request new hypotheses when the evidence graph supports expansion.

This is an independent Python implementation on top of pluggable LLM provider SDKs.

> [`docs/BENCH_RESULTS.md`](docs/BENCH_RESULTS.md) — historical cross-model bench results from the original benchmark harness. It is auto-generated from the bench DB and may contain earlier benchmark terminology.

## Contents

- [Architecture](#architecture)
- [Install](#install)
- [Initialize](#initialize)
- [Run a research session](#run-a-research-session)
- [LLM provider](#llm-provider)
- [Configuration](#configuration)
- [Bench: compare models head-to-head](#bench-compare-models-head-to-head)
- [Repository layout](#repository-layout)

## Architecture

```
                       co-scientist run "<breeding goal>"
                                  │
                                  ▼
            ┌──────────────────────────────────────┐
            │            Supervisor                │  durable task queue (SQLite)
            │  • parse_goal → breeding objective   │  bounded concurrency
            │  • enqueue six-agent task batches    │  lease + dead-letter + resume
            │  • main loop: claim → run → follow-up│  termination: BUDGET / WALL_CLOCK
            │  • decide_next_steps when idle       │              / CALIBRATION_STABLE / IDLE
            │  • finalize: prioritized hypotheses  │              / EXTERNAL
            └──────────────────────────────────────┘
                                  │  tasks
            ┌─────────────────────┼─────────────────────────────┐
            ▼                     ▼                             ▼
   ┌──────────────┐      ┌──────────────┐              ┌──────────────┐
   │    Goal      │ goal │   Evidence   │ graph        │   Breeding   │
   │ Interpreter  │─────►│   Curator    │─────────────►│   Designer   │
   │ crop/trait/  │      │ KG + RAG +   │              │ hypotheses  │
   │ constraints  │      │ literature   │              │ as cards     │
   └──────────────┘      └──────────────┘              └──────────────┘
            ▲                     ▲                             │
            │                     │ evidence gaps               ▼
   ┌──────────────┐      ┌──────────────┐              ┌──────────────┐
   │  Iteration   │◄─────│    Risk      │              │ Validation   │
   │ Orchestrator │ feed │  Reviewer    │              │  Planner     │
   │ repair / add │ back │ gaps + risk  │              │ marker/field │
   │ / prune      │      │ + decision   │              │ trial routes │
   └──────────────┘
            │
            ▼
       repaired or new hypotheses re-enter the cycle


  Shared infrastructure
  ─────────────────────
  • LLMProvider  ─ anthropic / openai / openrouter / gemini / groq /
                   together / mistral / ollama / openai_compatible
  • ToolRegistry ─ web_fetch + pubmed_search / arxiv_search / europe_pmc_search;
                   web_search auto-registered iff TAVILY/BRAVE key set;
                   science-skills discovered via SKILL.md frontmatter
  • TokenBudget  ─ per-agent shares + global cap; reservation released on retry
  • EventBus     ─ in-memory fan-out to SSE for the live web UI
  • FaissStore   ─ IndexFlatIP per session, asyncio-locked, atomic save/load;
                   Voyage → OpenAI → hash-fallback embedder chain
  • SQLite       ─ sessions / hypotheses / reviews / pairwise calibration
                   persistence / tasks / transcripts / system_feedback /
                   embeddings_meta / spans / events / bench_* (15 tables;
                   WAL, busy_timeout, idempotent migration runner)
```

## Install

```bash
# Recommended: Python 3.11–3.13 (FAISS wheel availability)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# fill in the API key for whichever LLM provider you'll use (see below).
```

## Initialize

```bash
co-scientist init
co-scientist list
```

`init` creates `data/` (artifacts, vectors, logs) and applies migrations to `data/co_scientist.db`. The output prints which LLM provider it sees configured and whether its API key is set.

## Run a research session

```bash
co-scientist run "Identify breeding hypotheses to improve rice heat tolerance during grain filling" \
  --n 3 --budget-usd 2.0 --wall-clock 600
```

This kicks off Goal Interpreter -> Evidence Curator -> Breeding Designer -> Validation Planner / Risk Reviewer -> Iteration Orchestrator under the configured LLM provider. The Supervisor schedules tasks, pairwise calibration and breeding-score aggregation refine the prioritized route list, and the final breeding overview is written to `data/artifacts/<session_id>/final/overview.md`.

```bash
co-scientist serve            # FastAPI + htmx + SSE dashboard at localhost:7878
co-scientist report <id>      # print the final overview
co-scientist status <id>      # session metadata + counts
co-scientist pause <id> | resume <id> | abort <id>
co-scientist feedback <id> --kind directive --text "focus on metabolic pathways"
co-scientist estimate         # pre-flight cost estimate; warns if > 1.2× budget
co-scientist eval [agent]     # run the rubric eval bundle (offline mode optional)
co-scientist tools list       # show every registered tool the agents can call
```

## LLM provider

The agents are provider-agnostic — every agent talks to one LLM provider per session, picked in [`config/default.toml`](config/default.toml) (override with your own `co-scientist.toml`). Any of the providers below works; pick whichever you have a key for.

Config is **deep-merged** over [`config/default.toml`](config/default.toml), whose `[models]` defaults are Claude model ids. So if you switch `provider` away from `anthropic`, override **every** key in `[models]` — any key you leave out keeps its Claude default and will be sent to your new provider, which will reject it. Fill in model ids your chosen provider exposes (see the provider table below for examples per vendor):

```toml
[llm]
# Pick one. See the provider table below.
provider = "openai"   # anthropic | openai | openrouter | gemini | google | groq | together | mistral | ollama | openai_compatible

[models]
# Override ALL of these with model ids from your chosen provider.
goal_interpreter           = "<cheap-model>"
breeding_designer          = "<strong-model>"
breeding_designer_revision = "<strong-model>"
risk_reviewer_evidence          = "<strong-model>"
validation_planner         = "<strong-model>"
risk_reviewer              = "<strong-model>"
pairwise_calibration       = "<cheap-model>"
calibration_debate         = "<strong-model>"
composite_prioritization   = "<strong-model>"
iteration_feedback         = "<cheap-model>"
final_synthesis            = "<strong-model>"
classifier                 = "<cheap-model>"
judge                      = "<cheap-model>"
```

Providers are listed alphabetically — none is preferred; pick whichever you have a key for.

| provider              | Endpoint                                                | API-key env var         | Example models                                            |
| --------------------- | ------------------------------------------------------- | ----------------------- | --------------------------------------------------------- |
| `anthropic`           | api.anthropic.com                                       | `ANTHROPIC_API_KEY`     | `claude-opus-4-7`, `claude-sonnet-4-6`                    |
| `gemini` / `google`   | generativelanguage.googleapis.com (OpenAI-compat)       | `GEMINI_API_KEY`        | `gemini-2.5-pro`, `gemini-2.5-flash`                      |
| `groq`                | api.groq.com                                            | `GROQ_API_KEY`          | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768`           |
| `mistral`             | api.mistral.ai                                          | `MISTRAL_API_KEY`       | `mistral-large-latest`, `codestral-latest`                |
| `ollama`              | localhost:11434 — local models                          | *(none)*                | `llama3.3:70b`, `qwen2.5:32b`                             |
| `openai`              | api.openai.com                                          | `OPENAI_API_KEY`        | `gpt-5`, `gpt-4o`, `o3-mini`                              |
| `openai_compatible`   | Anything else; set `[llm.openai] base_url` explicitly   | `OPENAI_API_KEY`        | depends                                                   |
| `openrouter`          | openrouter.ai — 200+ models from every major vendor     | `OPENROUTER_API_KEY`    | `openai/gpt-5`, `google/gemini-2.5-pro`, `anthropic/claude-3.5-sonnet`, `meta-llama/llama-3.3-70b-instruct` |
| `together`            | api.together.xyz                                        | `TOGETHER_API_KEY`      | `meta-llama/Llama-3.3-70B-Instruct-Turbo`                 |

> Key precedence: for every OpenAI-compatible preset (`openrouter`, `gemini`, `groq`, `together`, `mistral`, `ollama`), `OPENAI_API_KEY` is used **first** if it's set, and the provider-specific var above is only the fallback. So if you have a stray `OPENAI_API_KEY` in your environment it will be sent to the preset's endpoint (and rejected) — unset it, or set only the provider's own key, when using a preset.

Mixing vendors per session requires picking the provider once; for multi-vendor routing in a single session, use `provider = "openrouter"` and let OpenRouter dispatch upstream per model:

```toml
[llm]
provider = "openrouter"
[llm.openrouter]
referer = "https://your-app.example.com"   # optional, for catalog attribution
title   = "My AI Breeding Scientist"

[models]
# Breeding Designer design pass
breeding_designer = "openai/gpt-5"
# Risk Reviewer evidence review / Validation Planner / Risk Reviewer pass
risk_reviewer_evidence = "anthropic/claude-3.5-sonnet"
# Iteration Orchestrator pairwise calibration pass
pairwise_calibration = "google/gemini-2.5-flash"
# Iteration Orchestrator final synthesis step
final_synthesis = "meta-llama/llama-3.3-70b-instruct"
```

Any per-agent model can point at any vendor — the example above just mixes four. Use whatever combination you prefer.

Cost is estimated via `co_scientist/llm/routing.py`'s `PRICE_TABLE`; unknown models match a family-hint (flash / mini / opus / sonnet / gemini / llama / mistral) so brand-new previews price sensibly. Tighten `[run] budget_usd` if running on a new model you haven't sanity-checked.

**Provider feature support.** Tool / function calling is **required** — the agent pipeline is built on it, so a provider (or `openai_compatible` endpoint) that can't do function calling won't work. The other three rows are optional vendor-specific accelerators: when a provider doesn't support one, it's transparently skipped, never an error.

| Feature                     | `anthropic` | everything else (OpenAI + all OpenAI-compatible providers) |
| --------------------------- | ----------- | ---------------------------------------------------------- |
| Tool / function call *(required)* | ✅    | ✅ native OpenAI; on other endpoints it must be supported or the run fails |
| Extended reasoning          | ✅ via `thinking` budgets | ✅ via `reasoning_effort`, **only for reasoning models** — the model id must start with `o1`/`o3`/`o4` or contain `reasoning`; for any other model (e.g. `gpt-4o`) the thinking budget is dropped |
| Prompt-cache breakpoints    | ✅          | ❌ (stripped before sending)                               |
| Batch API (50%-off pairwise calibration) | ✅          | ❌ (Anthropic-only; other providers run all pairwise checks synchronously) |

> Note: the reasoning-model check is a name heuristic ([`openai_client.py`](co_scientist/llm/openai_client.py) `_is_reasoning_model`). Newer reasoning-capable models whose ids don't match the pattern (e.g. `gpt-5`) won't get `reasoning_effort` until the heuristic is updated — they still work, just without an explicit reasoning budget.

## Configuration

Layered: [`config/default.toml`](config/default.toml) → `~/.co-scientist/config.toml` → `./co-scientist.toml` → `--config <path>`. Secrets come from environment only (see [`.env.example`](.env.example)).

## Bench: compare models head-to-head

`co-scientist bench` runs the same goal under N different `(provider, model)` configurations and compares them through a single shared pairwise-calibration pool. Each candidate independently designs breeding hypotheses; then every candidate-pair plays `--matches` pairwise checks, judged by ONE fixed judge model (picked separately so no candidate scores its own work).

> **For live numbers** — per-candidate calibration scores, the actual hypotheses each model proposed, gold-set hits, and what the data showed — see [`docs/BENCH_RESULTS.md`](docs/BENCH_RESULTS.md). It includes a headline-findings section at the top so you don't have to scroll through every bench.

### Presets

| `--preset`               | What it does |
| ---                      | --- |
| `baseline`               | Provider-agnostic model panel via OpenRouter, head-to-head pairwise calibration only |
| `minor-grain`                 | Minor-grain drought-tolerance demo goal + gold-set recall scoring. Current seed crop pack uses foxtail millet marker, mechanism, and validation-route clues |
| `minor-grain-vs-direct`       | `minor-grain` but each model runs **both** in the full six-agent pipeline AND as a direct single-call design |
| `frontier-minor-grain-vs-direct` | Same pipeline-vs-direct setup but with stronger frontier models |

```bash
# Run the baseline model panel on your own breeding goal:
co-scientist bench --preset baseline "Improve lodging resistance in a target minor grain"

# Run the bundled minor-grain drought demo benchmark:
co-scientist bench --preset minor-grain --n 3 --matches 2

# Compare six-agent pipeline vs direct model call on the same goal
# (--budget-per-candidate defaults to 3.0; frontier models need it):
co-scientist bench --preset minor-grain-vs-direct --n 1

# Current frontier models, pipeline vs direct:
co-scientist bench --preset frontier-minor-grain-vs-direct --n 1
```

### Pipeline vs direct design

The `--preset *-vs-direct` presets pit each model's **full six-agent pipeline** (tools + tool loop + dedup + `record_hypothesis`) against a **direct single-call design** with the same model + a forced `record_hypothesis` function call (no tools). Lets you measure how much of the system's output quality comes from the six-agent harness vs the underlying model. → live numbers in [`docs/BENCH_RESULTS.md`](docs/BENCH_RESULTS.md#headline-findings).

### Gold-set scoring (minor grains)

`minor-grain*` presets score **recall** against curated minor-grain breeding clue sets. The current seed crop pack uses foxtail millet examples; later crop packs can add sorghum, proso millet, broomcorn millet, buckwheat, oat, adlay, and other minor grains.

| label                                                   | size | what it is |
| ---                                                     | --- | --- |
| `minor-grain-drought-demo` *(default for `minor-grain*`)* | 3 | Demo drought-route clues from the foxtail millet crop pack: **Seita.5G404900 / qPH5.1**, **SiDREB2-like**, and **CAPS marker validation** |
| `minor-grain-resource-demo`                              | 5 | Demo resource-route clues from the foxtail millet crop pack: **Jingu 21**, **Zhangza 13**, **263A**, **BC1F1 validation**, and **managed drought phenotyping** |

Swap with `--goldset`:

```bash
co-scientist bench --preset minor-grain --goldset minor-grain-resource-demo
co-scientist bench --preset minor-grain --goldset none
```

The matcher is whole-token, case-insensitive, and looks at every searched field of every hypothesis (title / summary / full_text / `entities` / citation excerpts). Drug **class** mentions (e.g. "DHODH inhibitor") do **not** count — the candidate has to name the actual compound (or one of its registered aliases).

### Custom candidates

`label=provider:model[@mode]`. `mode` is `pipeline` (default) or `direct`. Pipeline goes through the full multi-agent stack; direct is a single forced-tool LM call with no literature tools.

```bash
co-scientist bench "Identify hypotheses about X" \
  -c flash3=openrouter:google/gemini-3-flash-preview \
  -c flash3-direct=openrouter:google/gemini-3-flash-preview@direct \
  -c gpt5=openai:gpt-5 \
  -c opus=anthropic:claude-opus-4.7 \
  --judge anthropic:claude-sonnet-4-6
```

### Where results live

Every bench writes to SQLite + JSON on disk:

```
data/co_scientist.db                          -> SQLite, all metadata
  bench_runs                                  one row per bench
  bench_candidates                            one row per (bench × candidate × mode)
  bench_matches                               one row per pairwise check

data/artifacts/<session_id>/                  -> JSON on disk
  bench/<bench_id>.json                       run summary + per-entity gold_hit_detail
  hypotheses/<hyp_id>.json                    every hypothesis the bench produced
  transcripts/<agent_step>/<trn_id>.json      every LLM call
```

The auto-generated [`docs/BENCH_RESULTS.md`](docs/BENCH_RESULTS.md) (rebuild with `python scripts/build_bench_report.py`) walks every recorded bench and renders the per-candidate result table, every hypothesis attributed to the model that produced it, and a post-hoc rescore against every registered gold set.

### Mechanics

- **Pipeline runs in parallel** per candidate under a deep-copied Config (`cfg.llm.provider`, `cfg.models.*`, thinking budgets zeroed for non-Anthropic).
- **Round-robin pairings**: every pair plays `--matches` pairwise checks (one random hypothesis from each side per check).
- **Structured verdict** via a forced `record_verdict` function call — no fragile `better idea: <N>` text parsing across providers.
- Bench runs are **isolated from regular sessions**: they don't write to the regular-session pairwise calibration persistence layer or affect any session's prioritized route list.

## Repository layout

```
co_scientist/
  agents/       # supervisor + six breeding-scientist agents
  bench/        # cross-model pairwise calibration + gold-set scoring
  llm/          # provider abstraction (anthropic/openai/openrouter/gemini/...),
                # tool loop, token budgets, model routing, retry, batch, estimator
  storage/      # SQLite schema + migrations, db connection, 10 repos
  tools/        # tool registry; web_fetch, web_search, pubmed/arxiv/europe_pmc,
                # science-skills bridge
  vectors/      # embeddings (Voyage/OpenAI/hash-fallback) + FAISS IndexFlatIP
  orchestrator/ # task scheduling, pairwise calibration, termination, event bus
  safety/       # injection quoting, classifier, citation verifier
  obs/          # metrics (tokens, cost, cache hit ratio, latency)
  web/          # FastAPI + htmx + SSE UI + sanitized markdown renderer
  evals/        # per-agent + e2e + regression evals
  tests/        # 213 unit tests + fixtures + smoke
config/
  default.toml
  prompts/      # Jinja2 templates addressed by canonical six-agent prompt names
docs/
  BENCH_RESULTS.md   # every bench ever run (auto-generated)
scripts/
  build_bench_report.py
reference/      # archived implementation-history notes
data/           # gitignored; runtime artifacts (SQLite, FAISS, transcripts)
vendor/         # gitignored; pinned clone of google-deepmind/science-skills
```

## License

Apache-2.0.
