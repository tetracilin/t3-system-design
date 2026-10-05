"""Shared fixtures. Other test modules can use these directly.

    fake_teable    a running FakeTeable (fresh per test)
    make_client    factory: make_client(token="alice", **kwargs) -> TeableClient on the fake
    client         make_client("tester")
    schema         parsed schema.yaml
    base_id        a base id string (the fake accepts any)
    bootstrapped   dict(settings, report, client): the fake after a full bootstrap
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from fake_teable import FakeTeable
from t3desk import schema as schema_mod
from t3desk.bootstrap import BootstrapReport, run_bootstrap
from t3desk.teable_client import TeableClient

BASE_ID = "bseTEST0001"


@pytest.fixture
def fake_teable() -> Iterator[FakeTeable]:
    server = FakeTeable().start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def make_client(fake_teable: FakeTeable) -> Iterator[Callable[..., TeableClient]]:
    created: list[TeableClient] = []

    def factory(token: str = "tester", **kwargs: Any) -> TeableClient:
        kwargs.setdefault("backoff", 0.0)
        kwargs.setdefault("timeout", 10.0)
        client = TeableClient(fake_teable.url, token, **kwargs)
        created.append(client)
        return client

    yield factory
    for client in created:
        client.close()


@pytest.fixture
def client(make_client: Callable[..., TeableClient]) -> TeableClient:
    return make_client("tester")


@pytest.fixture(scope="session")
def schema() -> schema_mod.Schema:
    return schema_mod.load_schema()


@pytest.fixture
def base_id() -> str:
    return BASE_ID


@pytest.fixture
def bootstrapped(client: TeableClient, base_id: str, schema: schema_mod.Schema) -> dict[str, Any]:
    """Fake server with all tables created. Returns settings (incl. table_ids) and the report."""
    settings: dict[str, Any] = {}
    report: BootstrapReport = run_bootstrap(
        client, base_id=base_id, project_name="Test project", schema=schema, settings=settings
    )
    return {"settings": settings, "report": report, "client": client, "table_ids": settings["table_ids"]}
