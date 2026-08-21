from app.tasks.download import should_retry_download_task


def test_retry_policy_allows_one_first_episode_transport_retry(monkeypatch):
    monkeypatch.setattr(
        "app.tasks.download.settings.pipeline_manual_review_after_failures",
        2,
    )
    assert should_retry_download_task(
        TimeoutError("connection timed out"),
        task_retry_count=0,
        task_retry_limit=1,
        prior_failed_jobs=0,
    )


def test_retry_policy_rejects_deterministic_player_error(monkeypatch):
    monkeypatch.setattr(
        "app.tasks.download.settings.pipeline_manual_review_after_failures",
        2,
    )
    assert not should_retry_download_task(
        RuntimeError("Video unavailable"),
        task_retry_count=0,
        task_retry_limit=1,
        prior_failed_jobs=0,
    )


def test_retry_policy_caps_across_prior_pipeline_attempts(monkeypatch):
    monkeypatch.setattr(
        "app.tasks.download.settings.pipeline_manual_review_after_failures",
        2,
    )
    assert not should_retry_download_task(
        TimeoutError("connection timed out"),
        task_retry_count=0,
        task_retry_limit=1,
        prior_failed_jobs=1,
    )
