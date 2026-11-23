import pytest

from app.channels import registry
from tests.assistant.fakes import FakeAdapter


@pytest.fixture
def adapter(monkeypatch) -> FakeAdapter:
    fake = FakeAdapter()
    monkeypatch.setitem(registry._adapters, "telegram", fake)
    return fake
