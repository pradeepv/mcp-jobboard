from dataclasses import dataclass, field
import os

@dataclass
class Features:
    jobs: bool = True
    company: bool = False
    funding: bool = False
    other: bool = False

def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default).lower()).strip().lower() in {"1", "true", "yes", "y", "on"}

@dataclass
class Settings:
    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    # Use default_factory to avoid mutable default error
    features: Features = field(default_factory=lambda: Features(
        jobs=_env_bool("FEATURE_JOBS", True),
        company=_env_bool("FEATURE_COMPANY", False),
        funding=_env_bool("FEATURE_FUNDING", False),
        other=_env_bool("FEATURE_OTHER", False),
    ))

def get_settings() -> Settings:
    return Settings()