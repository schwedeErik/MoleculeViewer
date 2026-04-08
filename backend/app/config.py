from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/molecules"


settings = Settings()

