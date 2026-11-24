from fastapi import APIRouter
from pydantic import BaseModel

from app.services.privacy_policy import PRIVACY_POLICY_VERSION, privacy_policy_content


router = APIRouter(
    prefix="/legal",
    tags=["Legal"],
)


class PrivacyPolicyResponse(BaseModel):
    version: str
    # Treść w Markdown (app/legal/privacy_policy.md).
    content: str


@router.get("/privacy-policy", response_model=PrivacyPolicyResponse)
def get_privacy_policy() -> PrivacyPolicyResponse:
    """Polityka prywatności, dostępna bez logowania (art. 13 RODO)."""
    return PrivacyPolicyResponse(version=PRIVACY_POLICY_VERSION, content=privacy_policy_content())
