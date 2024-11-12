import requests
import logging
from settings import settings
from typing import Dict


def send_metrics_to_server(metrics: Dict[str, float]) -> None:
    """
    Отправка метрик на сервер через API.

    Аргументы:
        metrics (Dict[str, float]): Словарь с метриками для отправки.

    Возвращает:
        None
    """
    try:
        url = settings.api_url + 'submit-metrics'
        response = requests.post(url, json=metrics)
        if response.status_code == 200:
            logging.info("Метрики успешно отправлены на сервер")
        else:
            logging.error("Ошибка при отправке метрик на сервер: %s",
                          response.text)
    except Exception as e:
        logging.error("Исключение при отправке метрик: %s", e)
        logging.info("Метрики не отправлены на сервер")
