import os

from pydantic import BaseModel

_DEFAULT_DATABASE_URL = "postgresql://app:app@localhost:5432/molecules"


def _sqlalchemy_url(url: str) -> str:
    """Use the psycopg 3 driver for plain ``postgresql://`` URLs.

    The scripts and ``psql`` use plain URLs; SQLAlchemy would otherwise pick
    psycopg2, which is not installed.
    """
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Settings(BaseModel):
    database_url: str = _sqlalchemy_url(os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL))


settings = Settings()
