import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, validator
import structlog

logger = structlog.get_logger()


class VectorStoreConfig(BaseModel):
    type: str = "chromadb"
    persist_directory: str = "./data/vector_store"
    collection_name: str = "factrade_knowledge"
    distance_metric: str = "cosine"


class EmbeddingsConfig(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    dimension: int = 1536
    batch_size: int = 100
    cache_enabled: bool = True
    cache_directory: str = "./data/embeddings"


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4-turbo-preview"
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0


class DocumentProcessingConfig(BaseModel):
    chunk_size: int = 1000
    chunk_overlap: int = 200
    separators: list = Field(default_factory=lambda: ["\n\n", "\n", ". ", " ", ""])
    supported_formats: list = Field(default_factory=lambda: ["pdf", "docx", "txt", "md", "html"])
    max_file_size_mb: int = 50


class RetrievalConfig(BaseModel):
    top_k: int = 5
    similarity_threshold: float = 0.7
    reranking_enabled: bool = True
    hybrid_search: bool = True
    semantic_weight: float = 0.7
    keyword_weight: float = 0.3


class IntegrityCheckConfig(BaseModel):
    validate_embeddings: bool = True
    check_duplicates: bool = True
    verify_metadata: bool = True
    check_orphaned_documents: bool = True


class RetrievalQualityConfig(BaseModel):
    test_queries_enabled: bool = True
    min_similarity_score: float = 0.6
    max_retrieval_time_ms: int = 500
    relevance_threshold: float = 0.7


class ResponseQualityConfig(BaseModel):
    check_hallucination: bool = True
    verify_sources: bool = True
    check_coherence: bool = True
    min_response_length: int = 50
    max_response_length: int = 4000
    toxicity_check: bool = True


class PerformanceConfig(BaseModel):
    max_query_time_ms: int = 2000
    max_embedding_time_ms: int = 1000
    max_memory_usage_mb: int = 2048
    target_uptime_percent: float = 99.9


class QualityChecksConfig(BaseModel):
    enabled: bool = True
    integrity: IntegrityCheckConfig = Field(default_factory=IntegrityCheckConfig)
    retrieval: RetrievalQualityConfig = Field(default_factory=RetrievalQualityConfig)
    response: ResponseQualityConfig = Field(default_factory=ResponseQualityConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)


class ErrorHandlingConfig(BaseModel):
    auto_recovery: bool = True
    max_retry_attempts: int = 3
    retry_backoff_factor: int = 2
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout_seconds: int = 60


class MonitoringConfig(BaseModel):
    health_check_interval_seconds: int = 60
    performance_profiling: bool = True
    memory_leak_detection: bool = True
    track_query_patterns: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    log_directory: str = "./logs"
    max_log_size_mb: int = 100
    backup_count: int = 10
    structured_logging: bool = True


class SelfHealingConfig(BaseModel):
    enabled: bool = True
    auto_restart_on_failure: bool = True
    cleanup_orphaned_processes: bool = True
    auto_optimize_indices: bool = True
    cache_invalidation: bool = True


class AutoDebuggerConfig(BaseModel):
    enabled: bool = True
    error_handling: ErrorHandlingConfig = Field(default_factory=ErrorHandlingConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    self_healing: SelfHealingConfig = Field(default_factory=SelfHealingConfig)


class SourceMonitoringConfig(BaseModel):
    watch_directories: list = Field(default_factory=lambda: ["./data/documents"])
    watch_interval_seconds: int = 300
    detect_modifications: bool = True
    detect_deletions: bool = True


class UpdateStrategyConfig(BaseModel):
    incremental_updates: bool = True
    batch_updates: bool = True
    batch_size: int = 50
    update_schedule: str = "0 2 * * *"


class VersioningConfig(BaseModel):
    enabled: bool = True
    max_versions: int = 10
    version_directory: str = "./data/versions"


class AutoUpdateConfig(BaseModel):
    enabled: bool = True
    monitoring: SourceMonitoringConfig = Field(default_factory=SourceMonitoringConfig)
    strategy: UpdateStrategyConfig = Field(default_factory=UpdateStrategyConfig)
    versioning: VersioningConfig = Field(default_factory=VersioningConfig)


class SystemConfig(BaseModel):
    name: str = "FACTRADE RAG System"
    version: str = "1.0.0"
    environment: str = "development"


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_enabled: bool = True
    rate_limit_per_minute: int = 60
    authentication_required: bool = False


class CacheConfig(BaseModel):
    enabled: bool = True
    type: str = "redis"
    ttl_seconds: int = 3600
    max_size_mb: int = 512


class MetricsConfig(BaseModel):
    enabled: bool = True
    port: int = 9090
    export_prometheus: bool = True
    export_interval_seconds: int = 15


class Config(BaseModel):
    system: SystemConfig = Field(default_factory=SystemConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    document_processing: DocumentProcessingConfig = Field(default_factory=DocumentProcessingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    quality_checks: QualityChecksConfig = Field(default_factory=QualityChecksConfig)
    auto_debugger: AutoDebuggerConfig = Field(default_factory=AutoDebuggerConfig)
    auto_update: AutoUpdateConfig = Field(default_factory=AutoUpdateConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)


class ConfigManager:
    _instance: Optional['ConfigManager'] = None
    _config: Optional[Config] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self.load_config()

    def load_config(self, config_path: Optional[str] = None) -> Config:
        if config_path is None:
            config_path = os.getenv('CONFIG_PATH', 'config.yaml')
        
        config_file = Path(config_path)
        
        if config_file.exists():
            logger.info("loading_config", path=str(config_file))
            with open(config_file, 'r') as f:
                config_dict = yaml.safe_load(f)
            
            self._config = Config(**config_dict)
        else:
            logger.warning("config_not_found", path=str(config_file), action="using_defaults")
            self._config = Config()
        
        self._setup_environment()
        logger.info("config_loaded", environment=self._config.system.environment)
        return self._config

    def _setup_environment(self):
        required_dirs = [
            self._config.vector_store.persist_directory,
            self._config.embeddings.cache_directory,
            self._config.auto_debugger.logging.log_directory,
            self._config.auto_update.versioning.version_directory,
        ]
        
        for directory in self._config.auto_update.monitoring.watch_directories:
            required_dirs.append(directory)
        
        for dir_path in required_dirs:
            Path(dir_path).mkdir(parents=True, exist_ok=True)
            logger.debug("directory_created", path=dir_path)

    @property
    def config(self) -> Config:
        if self._config is None:
            self.load_config()
        return self._config

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split('.')
        value = self._config
        
        try:
            for key in keys:
                if hasattr(value, key):
                    value = getattr(value, key)
                else:
                    return default
            return value
        except (AttributeError, KeyError):
            return default

    def reload(self):
        logger.info("reloading_config")
        self._config = None
        self.load_config()


def get_config() -> Config:
    return ConfigManager().config
