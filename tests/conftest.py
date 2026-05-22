import pytest
import pytest_asyncio
import asyncio
from datetime import datetime, timezone

# pytest-asyncio 0.21+ 需要此配置，否则 async fixture 不被识别
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture
def utc_now():
    return datetime.now(tz=timezone.utc)
