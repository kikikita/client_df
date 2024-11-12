from environs import Env
from dataclasses import dataclass


@dataclass
class Client:
    api_url: str


def get_settings(path: str):
    env = Env()
    env.read_env(path, override=True)

    return Client(
            api_url=env.str("API_URL"),
        )


settings = get_settings(".env")
print(settings)
