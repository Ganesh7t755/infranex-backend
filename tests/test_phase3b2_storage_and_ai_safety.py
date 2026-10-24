import os
import io
import pytest
from unittest.mock import MagicMock, patch
from fastapi import UploadFile, HTTPException
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.storage.file_storage import LocalFileStorage, S3CompatibleStorage, get_storage
from app.services.incident_assessment_provider import (
    IncidentAssessmentInput,
    DeterministicMockAssessmentProvider,
    ExternalInferenceProvider,
    build_unavailable_assessment_result,
    get_default_assessment_provider,
)


# ===========================================================================
# 1. Local & S3 Storage Unit Tests
# ===========================================================================

def test_local_storage_save_and_resolve(tmp_path):
    storage = LocalFileStorage(upload_dir=str(tmp_path))
    content = b"fake image bytes content"
    upload = UploadFile(filename="pothole.jpg", file=io.BytesIO(content), headers={"content-type": "image/jpeg"})

    target_path, size = storage.save_upload_sync(upload)
    assert os.path.exists(target_path)
    assert size == len(content)

    resolved = storage.resolve_path(target_path)
    assert resolved == target_path

    # Legacy relative path resolution
    base_name = os.path.basename(target_path)
    assert storage.resolve_path(f"uploads/{base_name}") == target_path
    assert storage.resolve_path(base_name) == target_path


def test_local_storage_rejects_unsupported_mime(tmp_path):
    storage = LocalFileStorage(upload_dir=str(tmp_path))
    upload = UploadFile(filename="script.sh", file=io.BytesIO(b"echo evil"), headers={"content-type": "application/x-sh"})

    with pytest.raises(HTTPException) as exc_info:
        storage.save_upload_sync(upload)
    assert exc_info.value.status_code == 415


def test_s3_storage_stores_clean_keys_and_private_object(tmp_path):
    """S3 adapter stores POSIX clean keys ('evidence/...') and enforces private visibility."""
    mock_boto_client = MagicMock()

    storage = S3CompatibleStorage(
        endpoint_url="https://fake-account.r2.cloudflarestorage.com",
        bucket_name="infranex-test-bucket",
        access_key="fake-key",
        secret_key="fake-secret",
        upload_dir=str(tmp_path)
    )
    storage._client = mock_boto_client

    content = b"pothole photo binary"
    upload = UploadFile(filename="crater.png", file=io.BytesIO(content), headers={"content-type": "image/png"})

    key, size = storage.save_upload_sync(upload)

    assert key.startswith("evidence/")
    assert key.endswith(".png")
    assert "\\" not in key  # Must be POSIX key, never Windows path
    assert size == len(content)

    mock_boto_client.put_object.assert_called_once()
    call_kwargs = mock_boto_client.put_object.call_args[1]
    assert call_kwargs["Bucket"] == "infranex-test-bucket"
    assert call_kwargs["Key"] == key
    assert call_kwargs["ContentType"] == "image/png"
    assert "ACL" not in call_kwargs or call_kwargs["ACL"] != "public-read"  # Never public by default


def test_s3_storage_resolves_legacy_local_disk_paths(tmp_path):
    """Legacy SQLite records containing local Windows/relative paths resolve safely from disk."""
    legacy_file = tmp_path / "legacy_evidence_123.jpg"
    legacy_file.write_bytes(b"legacy local data")

    storage = S3CompatibleStorage(
        bucket_name="test-bucket",
        upload_dir=str(tmp_path)
    )

    # 1. Direct absolute path resolution
    resolved = storage.resolve_path(str(legacy_file))
    assert resolved == str(legacy_file)

    # 2. Relative/basename fallback
    resolved_rel = storage.resolve_path(f"uploads\\legacy_evidence_123.jpg")
    assert resolved_rel == str(legacy_file)


def test_s3_storage_handles_upload_failures_safely(tmp_path):
    """Network/auth errors during S3 upload raise a clean 500 without leaking credentials."""
    mock_boto_client = MagicMock()
    mock_boto_client.put_object.side_effect = RuntimeError("AWS Error with secret-key-xyz-secret")

    storage = S3CompatibleStorage(
        bucket_name="test-bucket",
        upload_dir=str(tmp_path)
    )
    storage._client = mock_boto_client

    upload = UploadFile(filename="street.jpg", file=io.BytesIO(b"data"), headers={"content-type": "image/jpeg"})

    with pytest.raises(HTTPException) as exc:
        storage.save_upload_sync(upload)
    assert exc.value.status_code == 500
    assert "secret" not in exc.value.detail.lower()
    assert "failed to store evidence object" in exc.value.detail.lower()


def test_production_storage_validation_fails_closed_without_bucket(monkeypatch):
    """In production, configuring S3/R2 storage without a bucket name fails closed."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "strong-random-production-jwt-key-2026-xyz!")
    monkeypatch.setenv("STORAGE_BACKEND", "r2")
    monkeypatch.setenv("STORAGE_BUCKET", "")

    with pytest.raises(ValueError, match="STORAGE_BUCKET is required"):
        Settings()


# ===========================================================================
# 2. Truthful AI Inference Tests
# ===========================================================================

def test_mock_provider_refuses_simulated_scores_in_production(monkeypatch):
    """In production, mock provider returns explicit unavailable result with confidence=None."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")

    provider = DeterministicMockAssessmentProvider()
    input_data = IncidentAssessmentInput(
        complaint_id="c-001",
        category="POTHOLE",
        title="Deep pothole",
        description="Hazard on street"
    )

    result = provider.assess_incident(input_data)
    assert result.confidence_score is None
    assert result.is_simulation is True
    assert result.review_required is True
    assert result.assessment_metadata.get("status") == "UNAVAILABLE"
    assert "SIMULATED_SCORES_DISABLED_IN_PRODUCTION" in result.assessment_metadata.get("reason", "")


def test_mock_provider_allows_calibrated_simulation_in_dev(monkeypatch, tmp_path):
    """In development/test, mock provider returns calibrated scores for local testing."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "development")

    test_img = tmp_path / "valid.jpg"
    test_img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 200)

    provider = DeterministicMockAssessmentProvider()
    input_data = IncidentAssessmentInput(
        complaint_id="c-001",
        category="POTHOLE",
        title="Deep pothole",
        description="Hazard on street",
        evidence_path=str(test_img)
    )

    # In dev, test keywords or defaults execute without production block
    result = provider.assess_incident(input_data)
    assert result.is_simulation is True


def test_external_inference_unconfigured_returns_truthful_unavailable(monkeypatch):
    """External inference with empty URL returns explicit unconfigured/unavailable result."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.AI_INFERENCE_URL", "")

    provider = ExternalInferenceProvider(endpoint_url="")
    input_data = IncidentAssessmentInput(
        complaint_id="c-001",
        category="POTHOLE",
        title="Road hole",
        description="Pothole description"
    )

    result = provider.assess_incident(input_data)
    assert result.confidence_score is None
    assert result.review_required is True
    assert result.is_simulation is True
    assert result.assessment_metadata.get("status") == "UNAVAILABLE"
    assert result.assessment_metadata.get("reason") == "ENDPOINT_NOT_CONFIGURED"


def test_external_inference_timeout_handling(monkeypatch):
    """External inference handles network timeouts safely and routes to human review."""
    import httpx

    provider = ExternalInferenceProvider(
        endpoint_url="https://ai.example.com/api/assess",
        timeout_seconds=2.0
    )
    input_data = IncidentAssessmentInput(
        complaint_id="c-002",
        category="DAMAGED_ROAD",
        title="Cracked road",
        description="Pavement failure"
    )

    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Connection timed out")):
        result = provider.assess_incident(input_data)
        assert result.confidence_score is None
        assert result.review_required is True
        assert result.assessment_metadata.get("status") == "UNAVAILABLE"
        assert result.assessment_metadata.get("reason") == "TIMEOUT"


def test_external_inference_http_error_handling():
    """External inference handles HTTP 500 errors safely."""
    mock_resp = MagicMock()
    mock_resp.status_code = 502

    provider = ExternalInferenceProvider(
        endpoint_url="https://ai.example.com/api/assess"
    )
    input_data = IncidentAssessmentInput(
        complaint_id="c-003",
        category="GARBAGE",
        title="Waste pile",
        description="Illegal dump"
    )

    with patch("httpx.Client.post", return_value=mock_resp):
        result = provider.assess_incident(input_data)
        assert result.confidence_score is None
        assert result.review_required is True
        assert result.assessment_metadata.get("reason") == "EXTERNAL_HTTP_ERROR"


def test_external_inference_successful_response():
    """External inference successfully parses genuine remote AI analysis."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "confidence_score": 0.945,
        "detected_category": "POTHOLE",
        "category_match": True,
        "evidence_suitable": True,
        "explanation": "Remote vision transformer verified pothole defect with 94.5% confidence.",
        "limitations": "Model evaluated on fine-tuned civic vision dataset.",
        "review_required": False,
        "model_name": "vit-civic-v2",
        "metadata": {"latency_ms": 142}
    }

    provider = ExternalInferenceProvider(
        endpoint_url="https://ai.example.com/api/assess"
    )
    input_data = IncidentAssessmentInput(
        complaint_id="c-004",
        category="POTHOLE",
        title="Road crater",
        description="Deep pothole"
    )

    with patch("httpx.Client.post", return_value=mock_resp):
        result = provider.assess_incident(input_data)
        assert result.confidence_score == 0.945
        assert result.detected_category == "POTHOLE"
        assert result.category_match is True
        assert result.is_simulation is False
        assert result.review_required is False
        assert result.model_name == "vit-civic-v2"
        assert result.assessment_metadata.get("latency_ms") == 142


def test_get_default_assessment_provider_truthful_in_production(monkeypatch):
    """In production without local weights or external URL, default provider is truthful and does not use mock."""
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
    monkeypatch.setattr("app.core.config.settings.AI_INFERENCE_URL", "")

    # Simulate cloud deployment where 350MB local weights file is not bundled
    real_exists = os.path.exists
    with patch("os.path.exists", side_effect=lambda p: False if "vit_b_32_laion2b.pt" in str(p) else real_exists(p)):
        with patch.dict(os.environ, {"TESTING": ""}, clear=False):
            provider = get_default_assessment_provider()
            # Must not be DeterministicMockAssessmentProvider claiming to do genuine AI
            assert not isinstance(provider, DeterministicMockAssessmentProvider)
            assert isinstance(provider, ExternalInferenceProvider)
