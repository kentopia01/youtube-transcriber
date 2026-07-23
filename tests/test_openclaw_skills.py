from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "openclaw" / "skills"


def test_youtube_openclaw_skills_are_version_controlled_and_ytctl_only():
    expected = {"yt-transcribe", "yt-chat", "yt-status"}
    assert {path.name for path in SKILLS.iterdir() if path.is_dir()} == expected

    combined = "\n".join((SKILLS / name / "SKILL.md").read_text() for name in expected)
    assert "/Users/sentryclaw/Projects/youtube-transcriber/.venv/bin/ytctl" in combined
    for forbidden in (
        "docker exec",
        "psql ",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "api.openai.com",
        "api.anthropic.com",
    ):
        assert forbidden not in combined


def test_mutating_skill_keeps_confirmation_and_status_skill_is_read_only():
    transcribe = (SKILLS / "yt-transcribe" / "SKILL.md").read_text()
    status = (SKILLS / "yt-status" / "SKILL.md").read_text()
    assert "--confirm" in transcribe
    assert "This skill is read-only" in " ".join(status.split())
