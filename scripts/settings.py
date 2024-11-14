import os
from environs import Env
from dataclasses import dataclass


@dataclass
class Client:
    api_url: str
    user_id: int


def get_settings(path: str):
    if not os.path.exists(path):
        raise FileNotFoundError(f".env файл не найден по пути: {path}")
    env = Env()
    env.read_env(path, override=True)

    return Client(
            api_url=env.str("API_URL"),
            user_id=env.int("USER_ID"),
        )


settings = get_settings("/src/.env")
print(settings)
