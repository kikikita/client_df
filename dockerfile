# Используем базовый образ с Python
FROM python:3.10

# Устанавливаем необходимые утилиты для сбора метрик
RUN apt-get update && \
    apt-get install -y smartmontools sysstat net-tools procps ifstat && \
    rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости Python
COPY ./requirements.txt /requirements.txt
RUN python -m pip install --upgrade pip && \
    pip install -r /requirements.txt

# Устанавливаем рабочую директорию
WORKDIR /src

# Копируем все файлы проекта
COPY . /src

# Устанавливаем права на исполнение для скрипта
RUN chmod +x /src/scripts/collect_disk_metrics.py

# Устанавливаем cron
RUN apt-get update && apt-get install -y cron

# Копируем crontab-файл в контейнер
COPY crontab /etc/cron.d/collect_metrics_cron

# Даем права на запуск crontab
RUN chmod 0644 /etc/cron.d/collect_metrics_cron

# Добавляем задания из crontab в cron
RUN crontab /etc/cron.d/collect_metrics_cron

# Запускаем cron (чтобы контейнер не завершался)
CMD ["cron", "-f"]

