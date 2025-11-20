"""Global settings for AISmartSpider."""

from dataclasses import dataclass


@dataclass
class Settings:
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    timeout: int = 10
    max_retries: int = 3
    backoff_factor: float = 1.5
    max_pages: int = 3
    max_depth: int = 2


settings = Settings()
