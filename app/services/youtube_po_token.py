"""Proof gate for optional authenticated YouTube PO-token providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.config import settings


class AuthenticatedYouTubeAccessUnavailable(RuntimeError):
    """Authenticated extraction is not safe under the current runtime."""


@dataclass(slots=True)
class PoTokenReadiness:
    public_mode_ready: bool
    authenticated_access_enabled: bool
    authentication_ready: bool
    configured_provider: str | None
    discovered_providers: list[str]
    client: str
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _discovered_provider_names() -> list[str]:
    try:
        import yt_dlp.plugins
        from yt_dlp.extractor.youtube.pot import provider

        yt_dlp.plugins.load_all_plugins()
        registry = getattr(provider._pot_providers, "value", {})
        return sorted(str(name) for name in registry)
    except Exception:
        return []


def inspect_po_token_readiness() -> PoTokenReadiness:
    enabled = settings.ytdlp_authenticated_access_enabled
    configured = settings.ytdlp_po_token_provider_name.strip() or None
    client = settings.ytdlp_po_token_client.strip().lower() or "mweb"
    discovered = _discovered_provider_names()
    if not enabled:
        return PoTokenReadiness(
            public_mode_ready=True,
            authenticated_access_enabled=False,
            authentication_ready=False,
            configured_provider=configured,
            discovered_providers=discovered,
            client=client,
            reason="authenticated_access_disabled",
        )
    if not configured:
        reason = "po_token_provider_not_configured"
        ready = False
    elif not any(configured.lower() in name.lower() for name in discovered):
        reason = "configured_po_token_provider_not_discovered"
        ready = False
    elif client != "mweb":
        reason = "unsupported_authenticated_player_client"
        ready = False
    else:
        reason = "ready"
        ready = True
    return PoTokenReadiness(
        public_mode_ready=True,
        authenticated_access_enabled=True,
        authentication_ready=ready,
        configured_provider=configured,
        discovered_providers=discovered,
        client=client,
        reason=reason,
    )


def require_authenticated_access_ready() -> PoTokenReadiness:
    readiness = inspect_po_token_readiness()
    if not readiness.authentication_ready:
        raise AuthenticatedYouTubeAccessUnavailable(
            "Authenticated YouTube extraction is unavailable: "
            f"{readiness.reason}"
        )
    return readiness
