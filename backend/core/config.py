from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PARQUET_URL: str = (
        "https://stopendataprod.blob.core.windows.net/datasets/"
        "medicaid-provider-spending/2026-02-09/medicaid-provider-spending.parquet"
    )
    # Optional: override the local Parquet file path.
    # Set this in .env if you downloaded the file somewhere other than
    # backend/data/medicaid-provider-spending.parquet
    # Example: LOCAL_PARQUET_PATH=G:/users/daveq/downloads/medicaid-provider-spending.parquet
    LOCAL_PARQUET_PATH: str = ""

    CACHE_TTL: int = 3600          # 1 hour for heavy aggregates
    NPPES_CACHE_TTL: int = 86400   # 24 hours for provider registry data
    NPPES_BASE_URL: str = "https://npiregistry.cms.hhs.gov/api/"
    RISK_THRESHOLD: float = 10.0   # score must be GREATER THAN this to enter review queue (not a "high risk" label)
    ANOMALY_PRESCAN_LIMIT: int = 1000  # top providers scanned at startup
    SCAN_BATCH_SIZE: int = 100         # providers per manual scan batch

    class Config:
        env_file = ".env"


settings = Settings()
