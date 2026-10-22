import os

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
    
    # File Storage
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", os.path.join(BACKEND_DIR, "uploads"))
    MAX_UPLOAD_SIZE_BYTES: int = int(os.getenv("MAX_UPLOAD_SIZE_BYTES", str(10 * 1024 * 1024))) # 10MB
    
    # AI Provider configuration
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "clip")
    AUTO_ASSESS_ON_UPLOAD: bool = os.getenv("AUTO_ASSESS_ON_UPLOAD", "True").lower() in ("true", "1")
    
    # JWT Secret Key
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "infranex-cryptographic-jwt-secret-stage7-2026")
    
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

settings = Settings()
