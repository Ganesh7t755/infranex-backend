import os

INSECURE_DEV_JWT_SECRET = "infranex-cryptographic-jwt-secret-stage7-2026"

class Settings:
    PROJECT_NAME: str = "InfraNex AI Backend"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api"
    
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1")
    
    # Anchor paths to canonical backend directory regardless of invocation cwd
    BACKEND_DIR: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # SQLite default, easily overridable via DATABASE_URL env var
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{os.path.join(BACKEND_DIR, 'infranex_dev.db').replace(os.sep, '/')}"
    )
    
    # File Storage & Cloud Object Storage (S3 / Cloudflare R2)
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(BACKEND_DIR, "uploads"))
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024))) # 10MB
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local") # "local", "r2", or "s3"
    STORAGE_BUCKET: str = os.getenv("STORAGE_BUCKET", os.getenv("S3_BUCKET_NAME", ""))
    STORAGE_ENDPOINT: str = os.getenv("STORAGE_ENDPOINT", os.getenv("S3_ENDPOINT_URL", ""))
    STORAGE_ACCESS_KEY: str = os.getenv("STORAGE_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID", ""))
    STORAGE_SECRET_KEY: str = os.getenv("STORAGE_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", ""))
    STORAGE_REGION: str = os.getenv("STORAGE_REGION", os.getenv("AWS_DEFAULT_REGION", "auto"))
    
    # AI Provider & External Inference configuration
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "clip")
    AUTO_ASSESS_ON_UPLOAD: bool = os.getenv("AUTO_ASSESS_ON_UPLOAD", "True").lower() in ("true", "1")
    AI_INFERENCE_URL: str = os.getenv("AI_INFERENCE_URL", "")
    AI_INFERENCE_API_KEY: str = os.getenv("AI_INFERENCE_API_KEY", "")
    AI_INFERENCE_TIMEOUT_SECONDS: float = float(os.getenv("AI_INFERENCE_TIMEOUT_SECONDS", "10.0"))
    
    # JWT Secret Key
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", INSECURE_DEV_JWT_SECRET)
    
    # Reviewer Simulation Security (Stage 5)
    DEV_REVIEWER_TOKEN: str = os.getenv("DEV_REVIEWER_TOKEN", "infranex-dev-reviewer-secret-key-stage5")
    
    # Authority Simulation Security (Stage 3)
    DEV_AUTHORITY_TOKEN: str = os.getenv("DEV_AUTHORITY_TOKEN", "infranex-dev-authority-secret-key-stage3")
    
    # CORS
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000,http://10.0.2.2:8000"
        ).split(",")
        if origin.strip()
    ]

    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    def is_development_or_test(self) -> bool:
        return self.ENVIRONMENT.lower() in ("development", "test", "testing")

    def validate_jwt_secret_for_production(self) -> None:
        """Fails closed in production if JWT_SECRET_KEY is missing, blank, or insecure default."""
        if self.is_production():
            secret = (self.JWT_SECRET_KEY or "").strip()
            if not secret:
                raise ValueError("Production configuration error: JWT_SECRET_KEY is missing or blank.")
            if secret == INSECURE_DEV_JWT_SECRET:
                raise ValueError(
                    "Production configuration error: Insecure development default JWT_SECRET_KEY "
                    "cannot be used in production. Please set a secure random key."
                )

    def validate_storage_for_production(self) -> None:
        """Fails closed if cloud storage is configured in production without a valid bucket name."""
        if self.is_production() and self.STORAGE_BACKEND.lower() in ("s3", "r2", "cloudflare"):
            if not (self.STORAGE_BUCKET or "").strip():
                raise ValueError("Production configuration error: STORAGE_BUCKET is required when using S3/R2 storage.")

    def __init__(self):
        self.ENVIRONMENT = os.getenv("ENVIRONMENT", self.ENVIRONMENT)
        self.JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", self.JWT_SECRET_KEY)
        self.STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", self.STORAGE_BACKEND)
        self.STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", os.getenv("S3_BUCKET_NAME", self.STORAGE_BUCKET))
        self.STORAGE_ENDPOINT = os.getenv("STORAGE_ENDPOINT", os.getenv("S3_ENDPOINT_URL", self.STORAGE_ENDPOINT))
        self.STORAGE_ACCESS_KEY = os.getenv("STORAGE_ACCESS_KEY", os.getenv("AWS_ACCESS_KEY_ID", self.STORAGE_ACCESS_KEY))
        self.STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY", os.getenv("AWS_SECRET_ACCESS_KEY", self.STORAGE_SECRET_KEY))
        self.STORAGE_REGION = os.getenv("STORAGE_REGION", os.getenv("AWS_DEFAULT_REGION", self.STORAGE_REGION))
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", self.AI_PROVIDER)
        self.AI_INFERENCE_URL = os.getenv("AI_INFERENCE_URL", self.AI_INFERENCE_URL)
        self.AI_INFERENCE_API_KEY = os.getenv("AI_INFERENCE_API_KEY", self.AI_INFERENCE_API_KEY)
        self.AI_INFERENCE_TIMEOUT_SECONDS = float(os.getenv("AI_INFERENCE_TIMEOUT_SECONDS", str(self.AI_INFERENCE_TIMEOUT_SECONDS)))
        self.validate_jwt_secret_for_production()
        self.validate_storage_for_production()

settings = Settings()

