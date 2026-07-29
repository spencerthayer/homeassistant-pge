class PGEError(Exception):
    pass


class PGEAuthenticationError(PGEError):
    pass


class PGEAuthorizationError(PGEError):
    pass


class PGERateLimitError(PGEError):
    """GraphQL HTTP 429 or Cognito InitiateAuth throttle / password-attempt lockout."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PGEConnectionError(PGEError):
    pass


class PGEGraphQLError(PGEError):
    def __init__(self, message: str, errors: list[dict] | None = None) -> None:
        super().__init__(message)
        self.graphql_errors = errors or []


class PGESchemaError(PGEError):
    pass


class PGENoDataError(PGEError):
    pass


class PGEAccountNotFoundError(PGEError):
    pass


class PGEMfaUnsupportedError(PGEAuthenticationError):
    """Account requires MFA — unsupported by this integration."""


class PGECaptchaUnsupportedError(PGEAuthenticationError):
    """Login requires CAPTCHA/device challenge — unsupported."""


class PGEDiscoveryIncompleteError(PGEError):
    """Credential HTTP chain not yet discovered / fixture-backed."""
