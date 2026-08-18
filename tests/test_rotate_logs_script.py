from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rotate_logs.sh"


def test_rotates_each_split_worker_log_and_preserves_unrelated_files(tmp_path):
    sources = {
        "yt-worker-audio.log": "audio-line\n",
        "yt-worker-post.log": "post-line\n",
        "yt-worker-diarize.log": "diarize-line\n",
    }
    for name, content in sources.items():
        (tmp_path / name).write_text(content)
    unrelated = tmp_path / "unrelated.log"
    unrelated.write_text("keep\n")

    env = os.environ.copy()
    env["YT_WORKER_LOG_DIR"] = str(tmp_path)
    env["YT_WORKER_LOG_KEEP_DAYS"] = "30"
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    today = datetime.now().strftime("%Y-%m-%d")
    assert "Rotated 3 split worker log(s)" in result.stdout
    for name, content in sources.items():
        current = tmp_path / name
        backup = tmp_path / f"{name[:-4]}.{today}.log"
        assert current.read_text() == ""
        assert backup.read_text() == content
    assert unrelated.read_text() == "keep\n"


def test_second_rotation_appends_before_truncating(tmp_path):
    current = tmp_path / "yt-worker-audio.log"
    current.write_text("first\n")
    env = os.environ.copy()
    env["YT_WORKER_LOG_DIR"] = str(tmp_path)
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)
    current.write_text("second\n")
    subprocess.run(["bash", str(SCRIPT)], env=env, check=True, capture_output=True)

    today = datetime.now().strftime("%Y-%m-%d")
    backup = tmp_path / f"yt-worker-audio.{today}.log"
    assert backup.read_text() == "first\nsecond\n"
    assert current.read_text() == ""
