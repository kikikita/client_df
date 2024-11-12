# ClientDF

## Обзор

**Скрипт для сбора метрик производительности дисков и серверов** — это комплексный инструмент, предназначенный для сбора и метрик производительности жестких дисков в режиме реального времени и записи в .csv файл. Этот скрипт собирает ключевые показатели производительности на уровне жесткого диска и сервера, а также SMART (Self-Monitoring, Analysis, and Reporting Technology), предоставляя ценные сведения о состоянии дисков.

Метрики классифицируются на три основных уровня:
1. **Атрибуты S.M.A.R.T.**: Сбор атрибутов SMART для мониторинга состояния диска.
2. **Метрики производительности на уровне диска**: Ориентированы на операции отдельных дисков, такие как I/O активность, размеры очередей, пропускная способность и рабочие статусы.
3. **Метрики производительности на уровне сервера**: Фиксируют показатели производительности всей системы, включая использование процессора, памяти, сетевого трафика и загрузки дисков.

## Атрибуты S.M.A.R.T.

Скрипт собирает следующие атрибуты SMART, которые важны для оценки состояния дисков:

| SMART ID | Наименование атрибута               |
|----------|-------------------------------------|
| 1        | Read_Error_Rate                     |
| 3        | Spin-Up_Time                        |
| 4        | Start/Stop_Count                    |
| 5        | Reallocated_Sectors_Count           |
| 7        | Seek_Error_Rate                     |
| 9        | Power-On_Hours                      |
| 10       | Spin_Retry_Count                    |
| 12       | Power_Cycle_Count                   |
| 187      | Reported_UNC_Errors                 |
| 188      | Command_Timeout                     |
| 191      | G-sense_error_rate                  |
| 192      | Power-off_Retract_Count             |
| 193      | Load/Unload_Cycle_Count             |
| 194      | Temperature_Celsius                 |
| 198      | Uncorrectable_Sector_Count          |
| 199      | UltraDMA_CRC_Error_Count            |

Эти атрибуты предоставляют важные данные о возможных отказах дисков, снижении производительности и общей надежности. Мониторинг этих значений помогает заранее выявлять проблемы до того, как они приведут к потере данных или выходу диска из строя.

## Метрики на уровне диска

Метрики на уровне диска дают представление о состоянии, нагрузке и пропускной способности каждого диска в сервере. Ключевые собираемые метрики включают:

- **DiskStatus**: Отражает текущий статус диска (например, исправен, занят, ошибка).
- **IOQueueSize**: Количество запросов ввода/вывода в очереди.
- **ReadSuccess_Throughput**: Пропускная способность чтения (КБ/с).
- **ReadWorkItem_QueueTime**: Время ожидания запросов на чтение (мс).
- **ReadWorkItem_SuccessQps**: Число успешных операций чтения в секунду (запросов/сек).
- **NormalFile_WriteWorkItem_SuccessQps**: Число успешных операций записи обычных файлов в секунду (запросов/сек).
- **NormalFile_WriteWorkItem_QueueTime**: Время ожидания запросов на запись обычных файлов (мс).
- **NormalFile_WriteSuccess_Throughput**: Пропускная способность записи обычных файлов (КБ/с).

## Метрики на уровне сервера

Эти метрики предоставляют более высокоуровневый обзор производительности всего сервера, выявляя системные воздействия на долговечность и стабильность дисков:

- **disk_util**: Максимальный и средний процент загрузки диска, указывающий на нагрузку и потенциальный износ.
- **tcp_segs_stat (tcp_outsegs)**: Количество отправленных сегментов TCP, указывающее на сетевые операции, влияющие на диск.
- **page_activity (page_in/page_out)**: Активность страниц, указывающая на использование свопа памяти, влияющего на диск.
- **disk_summary (total_disk_read/total_disk_write)**: Общий объем данных, прочитанных и записанных на диски, помогает отслеживать уровни износа.
- **memory_summary (mem_res)**: Использование зарезервированной памяти, при высокой зависимости от свопа указывает на повышенную активность диска.
- **cpu_summary (cpu_kernel)**: Нагрузка на процессор в режиме ядра, которая может указывать на потребности ввода/вывода на процессор.
- **udp_stat (udp_outdatagrams/udp_indatagrams)**: Отправленные/полученные дейтаграммы UDP, которые могут коррелировать с операциями записи/чтения на диск.
- **net_pps_summary (net_pps_receive/net_pps_transmit)**: Пакеты, полученные/отправленные в секунду, указывающие на сетевую нагрузку на диск.
- **net_summary (receive_speed)**: Скорость приема данных по сети, указывающая на возможные большие объемы записи на диск.
- **tcp_currestab**: Активные TCP-соединения, при высоком числе которых часто указывается высокий спрос на доступ к диску.

## Использование

### Для запуска скрипта на Linux:

1. Клонируйте или загрузите этот репозиторий:
   ```bash
   git clone https://ai-gitlab.npobaum.ru/aib-projects/aib-products/baum-ai-diskfailure-predict/baum-ai-diskfailure-predict-ds.git
2. Перейдите в созданную директорию:
   ```bash
   cd baum-ai-diskfailure-predict-ds
3. Установите необходимые зависимости:
   ```bash
   pip install requirements.txt
4. Установите системные утилиты (smartctl, iostat, netstat, vmstat, mpstat, ifstat, free), если они не установлены:
   ```bash
   sudo apt-get install smartmontools sysstat net-tools ifstat
5. Запустите скрипт с помощью:
   ```bash
   python3 collect_disk_metrics_linux.py

#### Запуск скрипта на регулярной основе с помощью crontab:

1. Сделайте Python-скрипт исполняемым, добавив права на исполнение:
   ```bash
   chmod +x collect_disk_metrics_linux.py
2. Откройте файл crontab для редактирования:
   ```bash
   sudo crontab -e
3. Скопируйте и вставьте следующие строки в файл crontab (проверьте ваш путь до скрипта):
   ```bash
   SHELL=/bin/bash
   PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

   # Запуск collect_disk_metrics.py каждый час
   0 * * * * /usr/bin/python3/home/user/baum-ai-diskfailure-predict-ds/scripts/collect_disk_metrics_linux.py
4. Чтобы проверить состояние cron и убедиться в его запуске, выполните:
   ```bash
   sudo systemctl status cron

Примечание:

```0 * * * *``` — скрипт запускается каждую нулевую минуту каждого часа.

```/usr/bin/python3``` — полный путь к интерпретатору Python 3 (узнать путь можно командой which python3).

```/home/user/baum-ai-diskfailure-predict-ds/scripts/collect_disk_metrics_linux.py``` — путь к скрипту, который может быть изменен в зависимости от его расположения на сервере.