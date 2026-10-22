import os
from dataclasses import dataclass, field
from typing import List, Optional, Protocol
from app.models.repair_verification import RepairVerificationOutcome

@dataclass
class VerificationInput:
    complaint_id: str
    category: str
    title: str
    description: str
    before_evidence_path: Optional[str] = None
    before_evidence_name: Optional[str] = None
    after_evidence_path: Optional[str] = None
    after_evidence_name: Optional[str] = None
    before_mime_type: Optional[str] = None
    after_mime_type: Optional[str] = None

@dataclass
class VerificationResult:
    outcome: RepairVerificationOutcome
    explanation: str
    observations: List[str] = field(default_factory=list)
    evidence_quality: str = "Acceptable"
    limitations: str = ""
    provider_id: str = "mock_deterministic_v1"
    model_name: str = "infranex-heuristic-simulator-v1"
    is_simulation: bool = True

class RepairVerificationProvider(Protocol):
    def verify_repair(self, input_data: VerificationInput) -> VerificationResult:
        """Analyze before-and-after evidence to produce a structured verification result."""
        ...

class MockRepairVerificationProvider:
    """
    Deterministic mock provider for civic repair verification.
    Clearly identified as a simulation that uses rule-based heuristic checks
    and does not claim to execute real vision neural network models.
    """

    def __init__(
        self,
        provider_id: str = "mock_deterministic_v1",
        model_name: str = "infranex-heuristic-simulator-v1"
    ):
        self.provider_id = provider_id
        self.model_name = model_name

    def verify_repair(self, input_data: VerificationInput) -> VerificationResult:
        # 1. Missing before or after evidence
        if not input_data.before_evidence_path or not input_data.after_evidence_path:
            missing_parts = []
            if not input_data.before_evidence_path:
                missing_parts.append("initial defect report photo")
            if not input_data.after_evidence_path:
                missing_parts.append("post-repair claimed photo")
            
            return VerificationResult(
                outcome=RepairVerificationOutcome.INCONCLUSIVE,
                explanation=f"Cannot verify repair: missing {' and '.join(missing_parts)}.",
                observations=[
                    "Comparative assessment requires both pre-repair and post-repair photographic records.",
                    f"Provided evidence lacks: {', '.join(missing_parts)}."
                ],
                evidence_quality="Insufficient - Missing Evidence",
                limitations="Analysis was aborted because matching before-and-after photos were not provided for this complaint.",
                provider_id=self.provider_id,
                model_name=self.model_name,
                is_simulation=True
            )

        # 2. File existence and basic readability checks
        before_exists = os.path.exists(input_data.before_evidence_path)
        after_exists = os.path.exists(input_data.after_evidence_path)

        if not before_exists or not after_exists:
            missing_files = []
            if not before_exists:
                missing_files.append("initial evidence file on storage")
            if not after_exists:
                missing_files.append("repair claim evidence file on storage")
            
            return VerificationResult(
                outcome=RepairVerificationOutcome.INCONCLUSIVE,
                explanation="Evidence image file could not be accessed from system storage.",
                observations=[
                    f"Storage verification failure: {', '.join(missing_files)} not accessible.",
                    "Unable to read binary image data for visual inspection."
                ],
                evidence_quality="Error - File Unreadable",
                limitations="Physical file missing or permission denied during analysis.",
                provider_id=self.provider_id,
                model_name=self.model_name,
                is_simulation=True
            )

        # Check file sizes
        try:
            before_size = os.path.getsize(input_data.before_evidence_path)
            after_size = os.path.getsize(input_data.after_evidence_path)
        except OSError:
            before_size, after_size = 0, 0

        if before_size < 100 or after_size < 100:
            return VerificationResult(
                outcome=RepairVerificationOutcome.INCONCLUSIVE,
                explanation="Evidence image file size is too small or truncated for comparative analysis.",
                observations=[
                    f"Before file size: {before_size} bytes; After file size: {after_size} bytes.",
                    "Images with fewer than 100 bytes cannot contain valid photographic image data."
                ],
                evidence_quality="Low - Truncated Payload",
                limitations="File corrupt or truncated during upload.",
                provider_id=self.provider_id,
                model_name=self.model_name,
                is_simulation=True
            )

        # 3. Rule-based assessment based on evidence metadata / hints
        after_name_lower = (input_data.after_evidence_name or "").lower()
        title_lower = input_data.title.lower()

        # Keyword-based simulation flags for automated test verification
        if any(kw in after_name_lower for kw in ["unresolved", "failed", "broken", "rework"]) or "unresolved" in title_lower:
            return VerificationResult(
                outcome=RepairVerificationOutcome.LIKELY_UNRESOLVED,
                explanation="Comparison of initial report and claimed repair photos indicates residual or incomplete remediation at the defect location.",
                observations=[
                    "Defect cavity or structural anomaly remains partially visible at the reported location.",
                    "Perimeter seam around repair area shows visible cracking and displacement.",
                    "Surface does not appear fully restored to municipal road safety standards."
                ],
                evidence_quality="Good - Clear Comparative Views",
                limitations="Simulation rule-based outcome. Contextual landmark verification requires human physical inspection.",
                provider_id=self.provider_id,
                model_name=self.model_name,
                is_simulation=True
            )

        if any(kw in after_name_lower for kw in ["inconclusive", "blurry", "dark", "distant"]) or "blurry" in title_lower:
            return VerificationResult(
                outcome=RepairVerificationOutcome.INCONCLUSIVE,
                explanation="Photographic evidence quality is inadequate for definitive automated comparison.",
                observations=[
                    "Severe motion blur, adverse lighting, or extreme focal distance inhibits landmark correlation.",
                    "Unable to reliably align camera perspective between before-and-after photographs."
                ],
                evidence_quality="Poor - Inconclusive Perspective",
                limitations="Camera angle and distance difference exceed automated alignment tolerances. On-site inspection recommended.",
                provider_id=self.provider_id,
                model_name=self.model_name,
                is_simulation=True
            )

        # 4. Standard default positive remediation assessment
        return VerificationResult(
            outcome=RepairVerificationOutcome.LIKELY_RESOLVED,
            explanation=f"Visual comparison indicates the reported {input_data.category.replace('_', ' ').lower()} defect has been remediated.",
            observations=[
                "Initial defect cavity is no longer apparent in the post-repair photograph.",
                "Remediation material appears contiguous with the adjacent road/sidewalk surface.",
                "Work site appears cleared of loose construction rubble and equipment."
            ],
            evidence_quality="Good - Standard Photographic Views",
            limitations="Simulated heuristic evaluation. Lighting differences and camera focal variance may mask subsurface defects. Official resolution requires human reviewer sign-off.",
            provider_id=self.provider_id,
            model_name=self.model_name,
            is_simulation=True
        )
