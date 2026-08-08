"""Configuration loader.

Layered: config/default.toml → ~/.co-scientist/config.toml → ./co-scientist.toml → env.
Secrets come from environment variables only.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.toml"


class RunCfg(BaseModel):
    concurrency: int = 4
    max_ideas: int = 60
    max_pairwise_checks_per_hypothesis: int = 12
    wall_clock_seconds: int = 7200
    budget_tokens: int = 5_000_000
    budget_usd: float = 25.0

    @property
    def effective_max_pairwise_checks_per_hypothesis(self) -> int:
        return self.max_pairwise_checks_per_hypothesis


class StorageCfg(BaseModel):
    data_dir: str = "./data"


class ScienceSkillsCfg(BaseModel):
    path: str = "./vendor/science-skills"
    pinned_commit: str = ""


class EmbeddingsCfg(BaseModel):
    provider: str = "voyage"
    model: str = "voyage-3-large"
    dim: int = 1024


class VectorsCfg(BaseModel):
    backend: str = "faiss"
    dedup_cosine_threshold: float = 0.92


class KnowledgeCfg(BaseModel):
    active_catalog: str = "./data/knowledge/active/catalog.json"
    incoming_dir: str = "./data/knowledge/incoming"
    quarantine_dir: str = "./data/knowledge/quarantine"
    processed_dir: str = "./data/knowledge/processed"
    incoming_watch_enabled: bool = True
    incoming_watch_interval_seconds: float = 5.0
    incoming_stability_seconds: float = 3.0
    allow_direct_activation: bool = False
    germplasm_csv: str = "./docs/templates/germplasm_resources_public_seed.csv"
    crop_kg_json: str = "./docs/templates/foxtail_millet_kg_seed.json"
    crop_kg_packs: dict[str, str] = Field(default_factory=dict)
    rag_sources_dir: str = "./docs/rag_sources"
    rag_index_json: str = "./data/rag/evidence_index.json"
    marker_qtl_csv: str = "./docs/templates/marker_qtl_library_seed.csv"
    phenotype_protocol_csv: str = "./docs/templates/phenotype_protocol_library_seed.csv"
    field_trial_csv: str = "./docs/templates/field_trial_records_seed.csv"


class PairwiseCalibrationCfg(BaseModel):
    k_factor_new: int = 32
    k_factor_warm: int = 16
    pairwise_calibration_initial: int = 1200
    debate_when_pairwise_calibration_delta_lt: int = 50
    debate_when_pairwise_calibrations_lt: int = 2
    batch_below_decile: bool = True
    batch_submit_every_seconds: int = 1800
    p_new: float = 0.4
    p_close: float = 0.4
    p_random: float = 0.2

    @property
    def effective_pairwise_calibration_initial(self) -> int:
        return self.pairwise_calibration_initial

    @property
    def effective_debate_when_pairwise_calibration_delta_lt(self) -> int:
        return self.debate_when_pairwise_calibration_delta_lt

    @property
    def effective_debate_when_pairwise_calibrations_lt(self) -> int:
        return self.debate_when_pairwise_calibrations_lt


class TerminationCfg(BaseModel):
    pairwise_calibration_stability_k: int = 5
    pairwise_calibration_stability_n: int = 3
    pairwise_calibration_stability_eps: float = 25.0
    pairwise_calibration_snapshot_every: int = 5
    min_pairwise_calibrations_before_stable: int = 15
    min_pairwise_calibrations_per_hypothesis: int = 3
    # Guards that prevent pairwise_calibration_stable from firing on a small pool.
    # Defaults of 0 disable the guard.
    min_ideas_before_stable: int = 0

    @property
    def effective_pairwise_calibration_stability_k(self) -> int:
        return self.pairwise_calibration_stability_k

    @property
    def effective_pairwise_calibration_stability_n(self) -> int:
        return self.pairwise_calibration_stability_n

    @property
    def effective_pairwise_calibration_stability_eps(self) -> float:
        return self.pairwise_calibration_stability_eps

    @property
    def effective_pairwise_calibration_snapshot_every(self) -> int:
        return self.pairwise_calibration_snapshot_every

    @property
    def effective_min_pairwise_calibrations_before_stable(self) -> int:
        return self.min_pairwise_calibrations_before_stable

    @property
    def effective_min_pairwise_calibrations_per_hypothesis(self) -> int:
        return self.min_pairwise_calibrations_per_hypothesis


class RouteRevisionCfg(BaseModel):
    """Controls when the idle-refinement loop triggers route revision."""
    # Minimum number of *mature* hypotheses (>= 3 pairwise calibrations) required
    # before the supervisor schedules a ReviseOrExpandRoute task.
    # Default matches the original hardcoded value.
    min_mature: int = 20
    # How many top hypotheses to revise or expand per idle pass.
    top_k: int = 5


class BudgetSharesCfg(BaseModel):
    goal_interpreter: float = 0.05
    evidence_curator: float = 0.15
    breeding_designer: float = 0.35
    validation_planner: float = 0.10
    risk_reviewer: float = 0.10
    iteration_orchestrator: float = 0.17
    reserve: float = 0.06


class ModelsCfg(BaseModel):
    goal_interpreter: str = "claude-sonnet-4-6"
    breeding_designer: str = "claude-opus-4-7"
    breeding_designer_revision: str = "claude-opus-4-7"
    risk_reviewer_evidence: str = "claude-opus-4-7"
    validation_planner: str = "claude-opus-4-7"
    risk_reviewer: str = "claude-opus-4-7"
    pairwise_calibration: str = "claude-sonnet-4-6"
    calibration_debate: str = "claude-sonnet-4-6"
    composite_prioritization: str = "claude-opus-4-7"
    iteration_feedback: str = "claude-sonnet-4-6"
    final_synthesis: str = "claude-opus-4-7"
    classifier: str = "claude-haiku-4-5-20251001"
    judge: str = "claude-sonnet-4-6"


class ThinkingCfg(BaseModel):
    breeding_designer_literature: int = 4000
    breeding_designer_debate: int = 8000
    risk_reviewer_evidence: int = 0
    verification_review: int = 12000
    observation_review: int = 6000
    pairwise_calibration: int = 4000
    calibration_debate: int = 8000
    route_combine: int = 6000
    route_out_of_box: int = 6000
    route_feasibility: int = 0
    route_simplify: int = 0
    iteration_feedback: int = 8000
    final_synthesis: int = 16000


class ToolLoopCfg(BaseModel):
    breeding_designer_max_iters: int = 8
    risk_reviewer_evidence_max_iters: int = 8
    pairwise_calibration_max_iters: int = 3
    route_revision_max_iters: int = 6
    final_synthesis_max_iters: int = 12
    parallel_cap: int = 4
    tool_timeout_seconds: int = 30


class RetryCfg(BaseModel):
    max_attempts_429: int = 6
    max_attempts_529: int = 8
    max_attempts_5xx: int = 5
    max_attempts_timeout: int = 3
    base_ms: int = 1000
    cap_ms: int = 60_000
    per_call_timeout_seconds: int = 120
    per_call_timeout_thinking_seconds: int = 300


class LeaseCfg(BaseModel):
    default_seconds: int = 300
    risk_reviewer_evidence_seconds: int = 600
    final_synthesis_seconds: int = 1800
    heartbeat_seconds: int = 60
    max_attempts: int = 3


class WebSearchCfg(BaseModel):
    provider: str = "tavily"
    max_results: int = 8


class WebFetchCfg(BaseModel):
    max_bytes: int = 5_000_000
    timeout_seconds: int = 30
    user_agent: str = "co-scientist/0.1"


class CodeExecCfg(BaseModel):
    provider: str = "anthropic"
    local_cpu_seconds: int = 30
    local_mem_mb: int = 512


class SafetyCfg(BaseModel):
    enable_classifier: bool = True
    enable_citation_verifier: bool = True
    classifier_block_categories: list[str] = Field(
        default_factory=lambda: ["cbrn", "csam", "weapons", "illicit_synthesis"]
    )
    classifier_warn_categories: list[str] = Field(default_factory=lambda: ["dual_use_bio"])


class OpenAIProviderCfg(BaseModel):
    """OpenAI / OpenAI-compatible endpoint settings.

    `base_url` overrides the SDK default. Use it to point at any
    OpenAI-compatible provider (Groq, Together, OpenRouter, Mistral,
    Gemini OpenAI-compat, Ollama local, vLLM, ...). When a named preset
    such as `provider = "openrouter"` is used, this only needs to be set
    if you want to override the preset's base_url.
    """

    base_url: str | None = None


class AnthropicProviderCfg(BaseModel):
    """Anthropic provider settings. `base_url` is rarely used; honored if set."""

    base_url: str | None = None


class OpenRouterProviderCfg(BaseModel):
    """OpenRouter attribution headers.

    OpenRouter ranks apps in its catalog by `HTTP-Referer` + `X-Title`.
    Setting these is optional but recommended for production traffic;
    leave blank for ad-hoc use.
    """

    referer: str = ""
    title: str = ""


class LLMCfg(BaseModel):
    """Choose which LLM vendor backs the agents.

    Supported values:
    - "anthropic" — Claude via the official Anthropic SDK (default). Cache
      breakpoints, extended thinking, and the Batch API are only available
      under this provider.
    - "openai" — OpenAI Chat Completions. Extended reasoning is translated
      to `reasoning_effort` for the o-series models; cache breakpoints are
      stripped.
    - "openrouter" — OpenRouter (openrouter.ai). 200+ models from every
      major vendor in one place. Set OPENROUTER_API_KEY (or
      OPENAI_API_KEY). Optional attribution in [llm.openrouter].
    - "gemini" / "google" — Google Gemini via the official OpenAI-compat
      endpoint. Set GEMINI_API_KEY. Models: "gemini-2.5-pro",
      "gemini-2.5-flash", etc.
    - "groq", "together", "mistral", "ollama" — convenience presets for
      those endpoints; each reads its own API key env var
      (GROQ_API_KEY, TOGETHER_API_KEY, MISTRAL_API_KEY).
    - "openai_compatible" — same client as `openai` but allows
      `llm.openai.base_url` to point at any other OpenAI-compatible
      endpoint not yet covered by a preset.
    """

    provider: str = "anthropic"
    openai: OpenAIProviderCfg = Field(default_factory=OpenAIProviderCfg)
    anthropic: AnthropicProviderCfg = Field(default_factory=AnthropicProviderCfg)
    openrouter: OpenRouterProviderCfg = Field(default_factory=OpenRouterProviderCfg)


class WebUICfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7878


class Secrets(BaseSettings):
    """Secrets pulled from env only. Empty string means 'not configured'."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    TOGETHER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""
    OLLAMA_API_KEY: str = ""
    VOYAGE_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    BRAVE_API_KEY: str = ""
    NCBI_API_KEY: str = ""
    OPENALEX_API_KEY: str = ""


class Config(BaseModel):
    run: RunCfg = Field(default_factory=RunCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    science_skills: ScienceSkillsCfg = Field(default_factory=ScienceSkillsCfg)
    embeddings: EmbeddingsCfg = Field(default_factory=EmbeddingsCfg)
    vectors: VectorsCfg = Field(default_factory=VectorsCfg)
    knowledge: KnowledgeCfg = Field(default_factory=KnowledgeCfg)
    pairwise_calibration: PairwiseCalibrationCfg = Field(default_factory=PairwiseCalibrationCfg)
    termination: TerminationCfg = Field(default_factory=TerminationCfg)
    route_revision: RouteRevisionCfg = Field(default_factory=RouteRevisionCfg)
    budget_shares: BudgetSharesCfg = Field(default_factory=BudgetSharesCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    thinking: ThinkingCfg = Field(default_factory=ThinkingCfg)
    tool_loop: ToolLoopCfg = Field(default_factory=ToolLoopCfg)
    retry: RetryCfg = Field(default_factory=RetryCfg)
    lease: LeaseCfg = Field(default_factory=LeaseCfg)
    web_search: WebSearchCfg = Field(default_factory=WebSearchCfg)
    web_fetch: WebFetchCfg = Field(default_factory=WebFetchCfg)
    code_exec: CodeExecCfg = Field(default_factory=CodeExecCfg)
    safety: SafetyCfg = Field(default_factory=SafetyCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    web_ui: WebUICfg = Field(default_factory=WebUICfg)
    secrets: Secrets = Field(default_factory=Secrets)

    @property
    def data_dir(self) -> Path:
        p = Path(self.storage.data_dir)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "co_scientist.db"

    def session_artifact_dir(self, session_id: str) -> Path:
        return self.data_dir / "artifacts" / session_id

    def session_vector_dir(self, session_id: str) -> Path:
        return self.data_dir / "vectors" / session_id

    def session_log_path(self, session_id: str) -> Path:
        return self.data_dir / "logs" / f"session-{session_id}.jsonl"

    @property
    def germplasm_csv_path(self) -> Path:
        p = Path(self.knowledge.germplasm_csv)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("germplasm_csv", fallback)

    @property
    def crop_kg_path(self) -> Path:
        p = Path(self.knowledge.crop_kg_json)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        packs = self.active_crop_kg_packs
        default_path = packs.get("foxtail_millet")
        if isinstance(default_path, str) and default_path.strip():
            candidate = Path(default_path)
            resolved = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
            if resolved.exists():
                return resolved
        return fallback

    @property
    def rag_sources_dir(self) -> Path:
        p = Path(self.knowledge.rag_sources_dir)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("rag_sources_dir", fallback)

    @property
    def rag_index_path(self) -> Path:
        p = Path(self.knowledge.rag_index_json)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("rag_index_json", fallback)

    @property
    def marker_qtl_csv_path(self) -> Path:
        p = Path(self.knowledge.marker_qtl_csv)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("marker_qtl_csv", fallback)

    @property
    def phenotype_protocol_csv_path(self) -> Path:
        p = Path(self.knowledge.phenotype_protocol_csv)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("phenotype_protocol_csv", fallback)

    @property
    def field_trial_csv_path(self) -> Path:
        p = Path(self.knowledge.field_trial_csv)
        fallback = p if p.is_absolute() else (PROJECT_ROOT / p)
        return self._active_knowledge_file("field_trial_csv", fallback)

    @property
    def active_knowledge_catalog_path(self) -> Path:
        p = Path(self.knowledge.active_catalog)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def knowledge_incoming_path(self) -> Path:
        p = Path(self.knowledge.incoming_dir)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def knowledge_quarantine_path(self) -> Path:
        p = Path(self.knowledge.quarantine_dir)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def knowledge_processed_path(self) -> Path:
        p = Path(self.knowledge.processed_dir)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def active_knowledge_catalog(self) -> dict[str, Any]:
        path = self.active_knowledge_catalog_path
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _active_knowledge_file(self, key: str, fallback: Path) -> Path:
        raw_path = self.active_knowledge_catalog.get(key)
        if not isinstance(raw_path, str) or not raw_path.strip():
            return fallback
        path = Path(raw_path)
        resolved = path if path.is_absolute() else (PROJECT_ROOT / path)
        return resolved if resolved.exists() else fallback

    @property
    def active_crop_kg_packs(self) -> dict[str, str]:
        packs = self.active_knowledge_catalog.get("crop_kg_packs")
        return packs if isinstance(packs, dict) else {}


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(extra_path: Path | None = None) -> Config:
    """Layered load: default.toml → ~/.co-scientist/config.toml → ./co-scientist.toml → extra_path → env."""
    merged: dict[str, Any] = _read_toml(DEFAULT_CONFIG)

    for p in (
        Path.home() / ".co-scientist" / "config.toml",
        Path.cwd() / "co-scientist.toml",
        extra_path,
    ):
        if p is not None:
            merged = _deep_merge(merged, _read_toml(p))

    cfg = Config.model_validate(merged)
    # secrets pulled from env via Secrets() — already wired by default_factory above
    return cfg


def has_anthropic_key(cfg: Config) -> bool:
    return bool(cfg.secrets.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY"))


# Env var names per provider preset (see llm/provider.py KNOWN_PROVIDERS).
_PROVIDER_ENV_VARS: dict[str, str] = {
    "anthropic":          "ANTHROPIC_API_KEY",
    "openai":             "OPENAI_API_KEY",
    "openai_compatible":  "OPENAI_API_KEY",
    "openrouter":         "OPENROUTER_API_KEY",
    "gemini":             "GEMINI_API_KEY",
    "google":             "GEMINI_API_KEY",
    "groq":               "GROQ_API_KEY",
    "together":           "TOGETHER_API_KEY",
    "mistral":            "MISTRAL_API_KEY",
    "ollama":             "",   # keyless
}


def provider_key_env(cfg: Config) -> str:
    """Env-var name the configured LLM provider expects, or '' if keyless."""
    name = (getattr(cfg.llm, "provider", "anthropic") or "anthropic").strip().lower()
    return _PROVIDER_ENV_VARS.get(name, "ANTHROPIC_API_KEY")


def has_llm_key(cfg: Config) -> bool:
    """True if the configured provider's API key is available, OR the provider
    is keyless (Ollama)."""
    env_var = provider_key_env(cfg)
    if not env_var:
        return True   # keyless provider
    # Explicit OPENAI_API_KEY is always honored (lets users repurpose presets).
    openai_compat_envs = {
        "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
        "GROQ_API_KEY", "TOGETHER_API_KEY", "MISTRAL_API_KEY",
    }
    if env_var in openai_compat_envs and (
        cfg.secrets.OPENAI_API_KEY or os.environ.get("OPENAI_API_KEY")
    ):
        return True
    return bool(getattr(cfg.secrets, env_var, "") or os.environ.get(env_var))
