from canonguard.core.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "CanonGuard"
    assert settings.api_host == "127.0.0.1"
    assert settings.llm_max_repairs == 2
    assert settings.minio_bucket_sources == "canonguard-sources"


def test_sqlite_detection() -> None:
    settings = Settings(_env_file=None, database_url="sqlite:///./test.db")

    assert settings.is_sqlite is True
