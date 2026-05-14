import os
from fastapi import HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-Internal-Secret", auto_error=False)


async def verify_internal_secret(api_key: str = Security(_api_key_header)):
    """Validates requests originated from the trusted Vercel proxy. Apply as Depends()."""
    expected = os.getenv("INTERNAL_API_SECRET", "")
    if not expected:
        raise RuntimeError("INTERNAL_API_SECRET env var is not set.")
    if not api_key or api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unauthorized: Invalid or missing internal secret.",
        )
