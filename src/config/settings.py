import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()  # Explicitly loads the .env file

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_ECHO: bool = False

settings = Settings()
