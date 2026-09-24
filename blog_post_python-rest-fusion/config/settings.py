from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # App
    DEBUG: bool = False

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "your_db_name"
    DB_USER: str = "your_db_user"
    DB_PASSWORD: str = ""

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_IMAGE_MODEL: str = "gpt-image-2"
    WORDPRESS_HTTP_TIMEOUT: int = 45
    WORDPRESS_MAX_READ_RETRIES: int = 3
    IMAGE_OUTPUT_DIR: str = "app/static/images"
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_TIMEZONE: str = "America/Bogota"
    SCHEDULER_BATCH_SIZE: int = 20
    LOCAL_MAX_CONCURRENCY: int = 3
    ORCHESTRATOR_ENABLED: bool = False
    ORCHESTRATOR_TOKEN: str = ""
    POST_BOT_WS_URL: str = "ws://localhost:8005/api/v1/post-bot/ws"
    POST_BOT_WS_TOKEN: str = ""
    POST_BOT_BOT_KEY: str = "post-bot-prod-01"
    POST_BOT_NAME: str = "AI WordPress Post Bot"
    POST_BOT_CALLBACK_URL: str = "http://127.0.0.1:8000/api/orchestrator/jobs"
    ORCHESTRATOR_MAX_CONCURRENCY: int = 2

    # Generar la URL de la base de datos
    @property
    def DATABASE_URL(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+psycopg",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
        ).render_as_string(hide_password=False)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Instancia global de configuración
settings = Settings()
