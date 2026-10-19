from dataguard.common.config import Settings


def test_database_url_built_from_settings():
    s = Settings(postgres_user="u", postgres_password="p", postgres_host="h", postgres_db="d")
    assert s.database_url == "postgresql+psycopg2://u:p@h:5432/d"
