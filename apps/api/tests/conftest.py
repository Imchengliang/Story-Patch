import os

os.environ.setdefault("CANONGUARD_DATABASE_URL", "sqlite:///./test_canonguard.db")
os.environ.setdefault("CANONGUARD_AUTO_CREATE_TABLES", "true")

import pytest

from canonguard.db import models  # noqa: F401
from canonguard.db.base import Base
from canonguard.db.session import engine


@pytest.fixture(autouse=True)
def reset_database() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
