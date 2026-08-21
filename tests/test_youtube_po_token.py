import pytest

from app.services import youtube_po_token as mod


def test_public_mode_is_ready_while_authenticated_access_is_disabled(monkeypatch):
    monkeypatch.setattr(mod.settings, "ytdlp_authenticated_access_enabled", False)
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_provider_name", "")
    monkeypatch.setattr(mod, "_discovered_provider_names", lambda: [])

    status = mod.inspect_po_token_readiness()

    assert status.public_mode_ready is True
    assert status.authentication_ready is False
    assert status.reason == "authenticated_access_disabled"


def test_enabled_auth_fails_closed_without_provider(monkeypatch):
    monkeypatch.setattr(mod.settings, "ytdlp_authenticated_access_enabled", True)
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_provider_name", "bgutil")
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_client", "mweb")
    monkeypatch.setattr(mod, "_discovered_provider_names", lambda: [])

    with pytest.raises(mod.AuthenticatedYouTubeAccessUnavailable, match="not_discovered"):
        mod.require_authenticated_access_ready()


def test_enabled_auth_accepts_discovered_mweb_provider(monkeypatch):
    monkeypatch.setattr(mod.settings, "ytdlp_authenticated_access_enabled", True)
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_provider_name", "bgutil")
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_client", "mweb")
    monkeypatch.setattr(
        mod,
        "_discovered_provider_names",
        lambda: ["bgutil-http"],
    )

    status = mod.require_authenticated_access_ready()

    assert status.authentication_ready is True
    assert status.reason == "ready"


def test_non_mweb_authenticated_client_fails_closed(monkeypatch):
    monkeypatch.setattr(mod.settings, "ytdlp_authenticated_access_enabled", True)
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_provider_name", "bgutil")
    monkeypatch.setattr(mod.settings, "ytdlp_po_token_client", "web")
    monkeypatch.setattr(mod, "_discovered_provider_names", lambda: ["bgutil-http"])

    status = mod.inspect_po_token_readiness()

    assert status.authentication_ready is False
    assert status.reason == "unsupported_authenticated_player_client"
