from dataclasses import dataclass

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError, PyJWKClient

from .config import Settings


@dataclass
class AuthContext:
    user_id: str
    claims: dict


def extract_bearer_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(" ", 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


class ClerkTokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.jwks_client = PyJWKClient(settings.clerk_jwks_url) if settings.clerk_jwks_url else None

    def verify(self, token: str) -> AuthContext:
        if not self.jwks_client:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Clerk JWKS is not configured",
            )

        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            audience = self.settings.clerk_audience.strip() or None
            issuer = self.settings.clerk_issuer.strip() or None
            options = {"verify_aud": bool(audience), "verify_iss": bool(issuer)}
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options=options,
            )
        except InvalidTokenError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Failed to verify auth token",
            ) from exc

        user_id = str(claims.get("sub", "")).strip()
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject")
        return AuthContext(user_id=user_id, claims=claims)

