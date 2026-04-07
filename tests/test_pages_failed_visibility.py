from types import SimpleNamespace

import pytest

from app.routers import pages as pages_router


class _FakeScalars:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        if isinstance(self.value, list):
            return _FakeScalars(self.value)
        if self.value is None:
            return _FakeScalars([])
        return _FakeScalars([self.value])


class _CaptureDB:
    def __init__(self, execute_values, scalar_values=None):
        self.execute_values = list(execute_values)
        self.scalar_values = list(scalar_values or [])
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        value = self.execute_values.pop(0) if self.execute_values else []
        return _FakeResult(value)

    async def scalar(self, statement):
        if self.scalar_values:
            return self.scalar_values.pop(0)
        return 0


class _DummyTemplates:
    def TemplateResponse(self, template_name, context, status_code=200):
        return {
            "template": template_name,
            "context": context,
            "status_code": status_code,
        }


def _dummy_request(hx: bool = False):
    headers = {"HX-Request": "true"} if hx else {}
    return SimpleNamespace(
        headers=headers,
        app=SimpleNamespace(state=SimpleNamespace(templates=_DummyTemplates())),
    )


@pytest.mark.asyncio
async def test_dashboard_failed_jobs_query_excludes_hidden_superseded():
    db = _CaptureDB(
        execute_values=[[], [], [], [], [], []],
        scalar_values=[0, 0, 0],
    )

    await pages_router.dashboard(_dummy_request(), db)

    failed_query_sql = str(db.statements[4])
    assert "jobs.status = :status_1" in failed_query_sql
    assert "jobs.hidden_from_queue IS false" in failed_query_sql


@pytest.mark.asyncio
async def test_queue_failed_jobs_query_excludes_hidden_superseded():
    db = _CaptureDB(execute_values=[[], [], [], [], []])

    await pages_router.queue_page(_dummy_request(), db)

    failed_query_sql = str(db.statements[3])
    assert "jobs.status = :status_1" in failed_query_sql
    assert "jobs.hidden_from_queue IS false" in failed_query_sql
