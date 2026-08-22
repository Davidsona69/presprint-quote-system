"""
Central app configuration, loaded from environment variables (.env).
Keep all magic numbers / business constants that might change out of code
and in here or in the pricing_matrix.json file (see services/pricing.py).
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Presprint Quote Engine"
    environment: str = "development"

    # Postgres
    database_url: str = "postgresql+asyncpg://presprint:presprint@localhost:5432/presprint_quotes"

    # CORS
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:8080", "*"]

    # NLP confidence threshold below which we ask the user to confirm fields
    # manually in the frontend instead of trusting the extractor blindly.
    nlp_confidence_threshold: float = 0.55

    # Where the rate matrices live. Overridable so a deployment can mount the
    # matrix as a config volume and let staff edit rates without rebuilding
    # the image. Empty = the copy shipped next to the app.
    pricing_matrix_path: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
