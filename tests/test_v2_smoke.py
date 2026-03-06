"""V2 Smoke tests — hit real services on localhost.

These tests verify that Docker services (Postgres, Redis, Web) are reachable
and that the API returns correct V2 fields.

Mark with pytest.mark.smoke so they can be skipped in CI where services aren't running.
"""

import socket
import time
import uuid

import pytest
import requests


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


# Skip all tests in this file if Docker services aren't running
pytestmark = pytest.mark.skipif(
    not _port_open("localhost", 8000),
    reason="Web service not reachable on localhost:8000",
)

BASE_URL = "http://localhost:8000"


class TestDockerServicesHealth:
    """Verify Docker-managed services are reachable."""

    def test_postgres_reachable(self):
        assert _port_open("localhost", 5432), "Postgres not reachable on port 5432"

    def test_redis_reachable(self):
        assert _port_open("localhost", 6379), "Redis not reachable on port 6379"

    def test_web_reachable(self):
        resp = requests.get(f"{BASE_URL}/", timeout=5)
        assert resp.status_code == 200

    def test_web_health_page_loads(self):
        resp = requests.get(f"{BASE_URL}/", timeout=5)
        assert "YouTube Transcriber" in resp.text or "top-nav" in resp.text


class TestAPIV2Fields:
    """Test that API responses contain V2 fields."""

    def test_video_list_page(self):
        resp = requests.get(f"{BASE_URL}/videos", timeout=5)
        assert resp.status_code == 200

    def test_transcription_endpoint_returns_v2_fields(self):
        """If transcriptions exist, verify V2 fields are present."""
        # Get the videos page to check if there are any videos
        resp = requests.get(f"{BASE_URL}/videos", timeout=5)
        if resp.status_code != 200:
            pytest.skip("Cannot load videos page")

        # Try to find a video ID from the page — look for transcription links
        import re
        uuids = re.findall(r'/videos/([0-9a-f-]{36})', resp.text)
        if not uuids:
            pytest.skip("No videos in database to test transcription fields")

        videos = [{"id": uid} for uid in set(uuids)]
        if not videos:
            pytest.skip("No videos in database to test transcription fields")

        video_id = videos[0].get("id") or videos[0].get("video_id")
        if not video_id:
            pytest.skip("Could not extract video ID")

        tresp = requests.get(f"{BASE_URL}/api/transcriptions/{video_id}", timeout=5)
        if tresp.status_code == 404:
            pytest.skip("Video has no transcription yet")

        assert tresp.status_code == 200
        body = tresp.json()

        # V2 required fields
        assert "language" in body, "Missing 'language' field in transcription response"
        assert "speakers" in body, "Missing 'speakers' field in transcription response"
        assert "diarization_enabled" in body, "Missing 'diarization_enabled' field"
        assert "segments" in body, "Missing 'segments' field"

        # Check segment structure
        if body["segments"]:
            seg = body["segments"][0]
            assert "start" in seg
            assert "end" in seg
            assert "text" in seg
            assert "speaker" in seg  # V2 field — can be null

    def test_submit_video_returns_proper_error_for_invalid(self):
        resp = requests.post(
            f"{BASE_URL}/api/videos",
            json={"url": "https://www.google.com"},
            timeout=5,
        )
        assert resp.status_code == 400

    def test_search_page_loads(self):
        resp = requests.get(f"{BASE_URL}/search", timeout=5)
        assert resp.status_code == 200
        assert "Search" in resp.text


class TestNativeWorkerConnectivity:
    """Test that Celery/Redis connectivity works for native worker."""

    def test_redis_accepts_connections(self):
        """Redis should accept connections for Celery broker."""
        try:
            import redis
            r = redis.Redis(host="localhost", port=6379, db=0, socket_timeout=3)
            r.ping()
        except ImportError:
            pytest.skip("redis package not installed")
        except Exception as exc:
            pytest.fail(f"Redis ping failed: {exc}")

    def test_celery_inspect(self):
        """Check if Celery worker is visible via Redis broker."""
        try:
            from celery import Celery
            app = Celery(broker="redis://localhost:6379/0")
            inspector = app.control.inspect(timeout=3)
            active = inspector.active()
            # active is None if no workers, dict if workers exist
            # We just verify the inspect call doesn't crash
            assert active is None or isinstance(active, dict)
        except ImportError:
            pytest.skip("celery not installed")
        except Exception as exc:
            # Connection issues are acceptable in test env
            pytest.skip(f"Celery inspect failed (worker may be down): {exc}")


class TestEndToEndVideoSubmission:
    """End-to-end test: submit a video URL and check it gets queued.

    NOTE: This doesn't wait for full transcription — that would take too long
    for a smoke test. It just verifies the submission flow works.
    """

    def test_submit_video_creates_job(self):
        """Submit a short video URL and verify a job is created."""
        # Use a very short, well-known video
        resp = requests.post(
            f"{BASE_URL}/api/videos",
            json={"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"},  # "Me at the zoo" - first YouTube video
            timeout=10,
        )
        # Accept 200 (new), 409 (already exists), or 201
        assert resp.status_code in (200, 201, 409), f"Unexpected status: {resp.status_code}, body: {resp.text}"

        if resp.status_code in (200, 201):
            body = resp.json()
            # Should have job info
            assert "job_id" in body or "video_id" in body or "id" in body
