"""Static deployment contract tests for the local-only service boundary."""

from pathlib import Path


def test_compose_publishes_all_host_ports_on_loopback() -> None:
    compose_lines = Path("docker-compose.yml").read_text().splitlines()
    published_ports = [
        line.strip().removeprefix("- ").strip('"')
        for line in compose_lines
        if line.strip().startswith('- "') and line.strip().endswith('"')
    ]

    assert "127.0.0.1:5432:5432" in published_ports
    assert "127.0.0.1:6379:6379" in published_ports
    assert "127.0.0.1:8000:8000" in published_ports
    assert all(port.startswith("127.0.0.1:") for port in published_ports)
