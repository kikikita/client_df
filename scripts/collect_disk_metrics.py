#!/usr/bin/env python3
import subprocess
import csv
import os
import json
from datetime import datetime
import logging
from typing import List, Tuple, Optional, Union, Dict, Any
import re
from client import send_metrics_to_server


# Директория на уровень выше текущей
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
data_dir = os.path.join(parent_dir, 'data')
logs_dir = os.path.join(parent_dir, 'logs')

# Проверка, существует ли директория, если нет - создание
os.makedirs(data_dir, exist_ok=True)
os.makedirs(logs_dir, exist_ok=True)

# Создание путей к файлам CSV и логов
csv_file = os.path.join(data_dir, "disk_metrics.csv")
log_file = os.path.join(logs_dir, "disk_metrics_py.log")

# Настройка логирования
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.getLogger().addHandler(logging.StreamHandler())


def get_disk_list() -> List[str]:
    """
    Получение списка дисков в системе.

    Возвращает:
        List[str]: Список дисков в формате '/dev/{имя_диска}'.
    """
    try:
        result = subprocess.run(
            ['lsblk', '-dn', '-o', 'NAME,TYPE'],
            capture_output=True, text=True, check=True
        )
        return [f"/dev/{line.split()[0]}" for line
                in result.stdout.splitlines() if "disk" in line]
    except subprocess.CalledProcessError as e:
        logging.error("Не удалось получить список дисков: %s", e)
        return []


def get_disk_info(disk: str) -> Tuple[str, str]:
    """
    Получение модели и серийного номера диска.

    Аргументы:
        disk (str): Путь к устройству диска (например, '/dev/sda').

    Возвращает:
        Tuple[str, str]: Кортеж с моделью диска и серийным номером.
                         Если информация недоступна,
                         возвращает ("Unknown", "Unknown").
    """
    try:
        result = subprocess.run(
            ['smartctl', '-i', disk],
            capture_output=True, text=True, check=True
        )
        model, serial_number = "Unknown", "Unknown"
        for line in result.stdout.splitlines():
            if "Device Model" in line:
                model = line.split(":")[1].strip()
            elif "Serial Number" in line:
                serial_number = line.split(":")[1].strip()
        return model, serial_number
    except subprocess.CalledProcessError as e:
        logging.error("Не удалось получить информацию о диске %s: %s", disk, e)
        return "Unknown", "Unknown"


def get_smart_data(disk: str) -> Optional[Dict[str, Any]]:
    """
    Получение SMART-информации о диске в формате JSON.

    Аргументы:
        disk (str): Путь к устройству диска (например, '/dev/sda').

    Возвращает:
        Optional[Dict[str, Any]]: Данные SMART в виде словаря
            или None при ошибке.
    """
    try:
        result = subprocess.run(
            ['smartctl', '-A', '-j', disk],
            capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logging.error("Ошибка выполнения smartctl для диска %s: %s",
                      disk, e.stderr or e.stdout)
        return None
    except json.JSONDecodeError:
        logging.error("Не удалось разобрать JSON-вывод для диска %s", disk)
        return None


def parse_smart_metrics(
    smart_data: Dict[str, Any], model: str, serial_number: str,
        required_ids: List[str]) -> Dict[str, Any]:
    """
    Парсинг SMART-метрик из JSON и формирование структуры данных.

    Аргументы:
        smart_data (Dict[str, Any]): JSON-данные SMART.
        model (str): Модель диска.
        serial_number (str): Серийный номер диска.
        required_ids (List[str]): Список требуемых SMART-атрибутов по их ID.

    Возвращает:
        Dict[str, Any]: Словарь с метриками SMART для записи в таблицу.
    """
    metrics = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "serial_number": serial_number,
        "model": model
    }

    if 'ata_smart_attributes' in smart_data:
        attributes = smart_data['ata_smart_attributes']['table']
        for attr in attributes:
            attr_id = str(attr.get("id", None))  # ID метрики как строка
            if attr_id in required_ids:
                normalized = attr.get("value", 0)  # Значение value
                raw_value = attr.get("raw", {}).get(
                    "string", attr.get("raw", {}).get("value", "0"))

                # Оставим только первое число, если в raw_value есть пробелы
                if isinstance(raw_value, str):
                    match = re.match(r"^\d+", raw_value)
                    raw_value = match.group(0) if match else "0"

                # Добавление значений в словарь метрик
                metrics[f"smart_{attr_id}_normalized"] = normalized
                metrics[f"smart_{attr_id}_raw"] = int(raw_value)\
                    if raw_value.isdigit() else "0"

    return metrics


def safe_float_conversion(value: str) -> float:
    """
    Безопасное преобразование строки в число с плавающей запятой.

    Аргументы:
        value (str): Значение для преобразования в float.

    Возвращает:
        float: Числовое значение float, если преобразование удалось, иначе 0.0.
    """
    try:
        return float(value)
    except ValueError:
        try:
            return float(value.replace(',', '.'))
        except ValueError:
            return 0.0


# #################### PERFRORMANCE METRICS (DISK LEVEL) #####################
# 1. DiskStatus
def get_disk_status(device: str) -> str:
    """
    Получение статуса диска (OK/Failed).

    Аргументы:
        device (str): Путь к устройству диска (например, '/dev/sda').

    Возвращает:
        str: Статус диска ('OK', 'FAILED', 'Unknown').
    """
    try:
        output = subprocess.check_output(['smartctl', '-H', device],
                                         stderr=subprocess.STDOUT).decode()
        for line in output.split('\n'):
            if 'SMART overall-health self-assessment test result' in line:
                status = line.split(':')[-1].strip()
                return status
    except Exception as e:
        logging.error("Ошибка при получении DiskStatus: %s", str(e))
        return 'Unknown'


# 2. IOQueueSize
def get_io_queue_size(devices: List[str]) -> Dict[str, Union[float, str]]:
    """
    Получение среднего размера очереди I/O для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, Union[float, str]]: Словарь со средним размером очереди I/O
            для каждого устройства. При ошибке значение будет '0'.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Поиск заголовков и начало данных
        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        aqu_sz_index = headers.index('aqu-sz')

        io_queue_sizes = {}
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                avgqu_sz = safe_float_conversion(parts[aqu_sz_index])
                io_queue_sizes[parts[0]] = avgqu_sz
        return io_queue_sizes
    except Exception as e:
        logging.error("Ошибка при получении очереди I/O: %s", e)
        return {device: '0' for device in devices}


# 3. ReadSuccess_Throughput
def get_read_success_throughput(devices: List[str], unit: str = 'KB/s')\
        -> Dict[str, float]:
    """
    Получение скорости успешного чтения с диска (в KB/с, MB/с или B/с).

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).
        unit (str): Единица измерения (KB/s, MB/s или B/s).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их скоростью чтения в
            выбранной единице. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Поиск заголовков и начало данных
        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        rkbs_index = headers.index('rkB/s')

        read_throughputs = {}
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                # Получаем скорость чтения в кБ/с
                read_kbs = safe_float_conversion(parts[rkbs_index])

                # Конвертируем в выбранную единицу
                if unit == 'MB/s':
                    read_value = read_kbs / 1024  # Конвертация в MB/s
                elif unit == 'B/s':
                    read_value = read_kbs * 1024  # Конвертация в байты/с
                else:
                    read_value = read_kbs  # Оставляем в kB/s

                read_throughputs[parts[0]] = read_value
        return read_throughputs
    except Exception as e:
        logging.error("Ошибка при получении ReadSuccess_Throughput: %s", e)
        return {device: 0.0 for device in devices}


# 4. ReadWorkItem_QueueTime
def get_read_work_item_queue_time(devices: List[str]) -> Dict[str, float]:
    """
    Получение среднего времени ожидания запросов на чтение (мс)
    для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их временем ожидания
            чтения в мс. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Находим строку заголовков таблицы устройств
        headers_line = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[headers_line].split()

        # Находим индекс столбца "r_await" (время ожидания запросов на чтение)
        r_await_index = headers.index('r_await')

        # Собираем данные о времени ожидания чтения для каждого устройства
        read_queue_times = {}
        for line in lines[headers_line + 1:]:
            parts = line.split()
            if len(parts) > r_await_index:
                device_name = parts[0]
                if device_name in devices:
                    try:
                        r_await = safe_float_conversion(parts[r_await_index])
                        read_queue_times[device_name] = r_await
                    except (IndexError, ValueError):
                        read_queue_times[device_name] = 0.0

        return read_queue_times
    except Exception as e:
        logging.error("Ошибка при получении ReadWorkItem_QueueTime: %s", e)
        return {device: 0.0 for device in devices}


# 5. ReadWorkItem_SuccessQps - Число успешных операций чтения (запросы/сек)
def get_read_work_item_success_qps(devices: List[str]) -> Dict[str, float]:
    """
    Получение числа успешных операций чтения в секунду для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их количеством успешных
            операций чтения в секунду.При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        headers_line = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[headers_line].split()
        r_s_index = headers.index('r/s')

        read_qps = {}
        for line in lines[headers_line + 1:]:
            parts = line.split()
            if len(parts) > r_s_index and parts[0] in devices:
                try:
                    read_qps_value = safe_float_conversion(parts[r_s_index])
                    read_qps[parts[0]] = read_qps_value
                except (IndexError, ValueError):
                    read_qps[parts[0]] = 0.0

        return read_qps
    except Exception as e:
        logging.error("Ошибка при получении ReadWorkItem_SuccessQps: %s", e)
        return {device: 0.0 for device in devices}


# 10. NormalFile_WriteWorkItem_SuccessQps
def get_write_work_item_success_qps(devices: List[str]) -> Dict[str, float]:
    """
    Получение числа успешных операций записи в секунду для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их количеством успешных
            операций записи в секунду. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        ws_index = headers.index('w/s')

        write_qps = {}
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                qps = safe_float_conversion(parts[ws_index])
                write_qps[parts[0]] = qps
        return write_qps
    except Exception as e:
        logging.error("Ошибка при получении WriteWorkItem_SuccessQps: %s", e)
        return {device: 0.0 for device in devices}


# 11. NormalFile_WriteWorkItem_QueueTime
def get_write_work_item_queue_time(devices: List[str]) -> Dict[str, float]:
    """
    Получение среднего времени ожидания запросов на запись (мс)
    для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их временем ожидания
            записи в мс. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        headers_line = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[headers_line].split()
        r_await_index = headers.index('w_await')

        read_queue_times = {}
        for line in lines[headers_line + 1:]:
            parts = line.split()
            if len(parts) > r_await_index and parts[0] in devices:
                try:
                    r_await = safe_float_conversion(parts[r_await_index])
                    read_queue_times[parts[0]] = r_await
                except (IndexError, ValueError):
                    read_queue_times[parts[0]] = 0.0

        return read_queue_times
    except Exception as e:
        logging.error("Ошибка при получении WriteWorkItem_QueueTime: %s", e)
        return {device: 0.0 for device in devices}


# 12. NormalFile_WriteSuccess_Throughput
def get_write_success_throughput(devices: List[str], unit: str = 'KB/s')\
        -> Dict[str, float]:
    """
    Получение пропускной способности записи для каждого устройства.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).
        unit (str): Единица измерения (KB/s, MB/s, B/s).

    Возвращает:
        Dict[str, float]: Словарь с устройствами и их пропускной
            способностью записи. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        wkbs_index = headers.index('wkB/s')

        write_throughputs = {}
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                write_kbs = safe_float_conversion(parts[wkbs_index])

                if unit == 'MB/s':
                    write_value = write_kbs / 1024
                elif unit == 'B/s':
                    write_value = write_kbs * 1024
                else:
                    write_value = write_kbs

                write_throughputs[parts[0]] = write_value
        return write_throughputs
    except Exception as e:
        logging.error("Ошибка при получении WriteSuccess_Throughput: %s", e)
        return {device: 0.0 for device in devices}


# ################## SERVER LEVEL PERFORMANCE #######################
# 1. disk_util: Максимальное и среднее значение утилизации дисков (в %).
def get_disk_utilization(devices: List[str])\
        -> Dict[str, Union[float, Dict[str, float]]]:
    """
    Получение максимального и среднего значения утилизации дисков.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, Union[float, Dict[str, float]]]:
            Словарь с максимальной и средней утилизацией дисков.
            При ошибке значения будут равны 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-x', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Поиск заголовков и начало данных
        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        util_index = headers.index('%util')

        disk_utils = {}
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                util_value = safe_float_conversion(parts[util_index])
                disk_utils[parts[0]] = util_value

        # Вычисление максимального и среднего значения
        if disk_utils:
            max_util = max(disk_utils.values())
            avg_util = sum(disk_utils.values()) / len(disk_utils)
        else:
            max_util = 0
            avg_util = 0

        return {"max_util": max_util, "avg_util": avg_util}
    except Exception as e:
        logging.error("Ошибка при получении get_disk_utilization: %s", e)
        return {"max_util": 0, "avg_util": 0}


# 2. tcp_segs_stat: tcp_outsegs
def get_tcp_outsegs_netstat() -> int:
    """
    Получение количества отправленных TCP-сегментов.

    Возвращает:
        int: Число отправленных TCP-сегментов. При ошибке значение будет 0.
    """
    try:
        output = subprocess.check_output(['netstat', '-s'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Поиск строки, содержащей информацию о TCP-сегментах
        for line in lines:
            if "segments sent out" in line:
                tcp_outsegs = int(line.strip().split()[0])
                return tcp_outsegs

        return 0
    except Exception as e:
        logging.error("Ошибка при получении tcp_segs_stat: %s", e)
        return 0


# 3. page_activity: page_in/page_out
def get_page_activity() -> Dict[str, int]:
    """
    Получение активности страниц памяти
    (входящих и исходящих страниц в секунду).

    Возвращает:
        Dict[str, int]: Словарь с количеством страниц, входящих и выходящих
            из памяти. При ошибке значения будут равны 0.
    """
    try:
        output = subprocess.check_output(['vmstat', '1', '2'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Ищем строку с заголовками
        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('procs'))
        headers = lines[header_index + 1].split()

        # Ищем индексы столбцов для page_in (si) и page_out (so)
        si_index = headers.index('si')
        so_index = headers.index('so')

        data_line = lines[header_index + 2].split()

        page_in = int(data_line[si_index])
        page_out = int(data_line[so_index])

        return {"page_in": page_in, "page_out": page_out}
    except Exception as e:
        logging.error("Ошибка при получении page_activity: %s", e)
        return {"page_in": 0, "page_out": 0}


# 4. disk_summary: total_disk_read/total_disk_write
def get_total_disk_read_write(devices: List[str]) -> Dict[str, float]:
    """
    Получение общего количества данных, считанных или записанных на диски.

    Аргументы:
        devices (List[str]): Список устройств (например, ['/dev/sda']).

    Возвращает:
        Dict[str, float]: Словарь с общим количеством данных чтения и
            записи в кБ. При ошибке значения будут равны 0.
    """
    try:
        output = subprocess.check_output(['iostat', '-k'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Поиск заголовков и начало данных
        header_index = next(i for i, line in enumerate(lines)
                            if line.startswith('Device'))
        headers = lines[header_index].split()
        kb_read_index = headers.index('kB_read')
        kb_wrtn_index = headers.index('kB_wrtn')

        total_read = 0
        total_write = 0

        # Парсинг строк с данными о дисках
        for line in lines[header_index + 1:]:
            parts = line.split()
            if parts and parts[0] in devices:
                total_read += safe_float_conversion(parts[kb_read_index])
                total_write += safe_float_conversion(parts[kb_wrtn_index])

        return {"total_disk_read_kb": total_read,
                "total_disk_write_kb": total_write}
    except Exception as e:
        logging.error("Ошибка при получении disk_summary: %s", e)
        return {"total_disk_read_kb": 0, "total_disk_write_kb": 0}


# 6. memory_summary: mem_res
def get_memory_summary() -> Dict[str, float]:
    """
    Получение сведений о памяти, включая общий объем, используемую,
    свободную и резервируемую память.

    Возвращает:
        Dict[str, float]: Словарь с общей, используемой, свободной и
            резервируемой памятью в кБ. При ошибке значения будут равны 0.
    """
    try:
        output = subprocess.check_output(['free', '-k'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Строка с общей информацией о памяти (м.б как "Mem:", так и "Память:")
        for line in lines:
            if line.startswith("Mem:") or line.startswith("Память:"):
                parts = line.split()
                total_mem = safe_float_conversion(parts[1])  # Всего памяти
                used_mem = safe_float_conversion(parts[2])   # Используемая
                free_mem = safe_float_conversion(parts[3])   # Свободная

                reserved_mem = total_mem - used_mem

                return {
                    "total_mem_kb": total_mem,
                    "used_mem_kb": used_mem,
                    "free_mem_kb": free_mem,
                    "reserved_mem_kb": reserved_mem
                }

    except Exception as e:
        logging.error("Ошибка при получении memory_summary: %s", e)
        return {
            "total_mem_kb": 0,
            "used_mem_kb": 0,
            "free_mem_kb": 0,
            "reserved_mem_kb": 0
        }


# 7. cpu_summary: cpu_kernel
def get_cpu_kernel_usage() -> float:
    """
    Получение загруженности CPU в режиме ядра.

    Возвращает:
        float: Загруженность CPU в режиме ядра в процентах.
               При ошибке возвращает 0.
    """
    try:
        output = subprocess.check_output(['mpstat', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        header_index = next(i for i, line in enumerate(lines)
                            if 'CPU' in line and '%idle' in line)
        headers = lines[header_index].split()
        idle_index = headers.index('%idle')

        for line in lines[header_index + 1:]:
            if "all" in line:
                parts = line.split()
                cpu_usage = 100 - safe_float_conversion(
                    parts[idle_index].replace(',', '.'))
                return cpu_usage
        return 0
    except Exception as e:
        logging.error("Ошибка при получении cpu_summary: %s", e)
        return 0


# 8. udp_stat: udp_outdatagrams/udp_indatagrams
def get_udp_stat_netstat() -> Tuple[int, int]:
    """
    Получение числа отправленных и полученных UDP датаграмм.

    Возвращает:
        Tuple[int, int]: Количество отправленных и полученных UDP датаграмм.
                         При ошибке возвращает (0, 0).
    """
    try:
        output = subprocess.check_output(['netstat', '-s'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        udp_outdatagrams = 0
        udp_indatagrams = 0

        # Ищем строки, которые содержат информацию об UDP-датаграммах
        for line in lines:
            if "datagrams sent" in line:
                udp_outdatagrams = int(line.strip().split()[0])
            elif "datagrams received" in line:
                udp_indatagrams = int(line.strip().split()[0])

        return udp_outdatagrams, udp_indatagrams
    except Exception as e:
        logging.error("Ошибка при получении udp_stat: %s", e)
        return 0, 0


# 9. net_pps_summary: net_pps_receive/net_pps_transmit
def get_net_pps() -> Tuple[int, int]:
    """
    Получение количества принятых и переданных сетевых пакетов в секунду.

    Возвращает:
        Tuple[int, int]: Количество принятых и переданных пакетов в секунду.
                         При ошибке возвращает (0, 0).
    """
    try:
        output = subprocess.check_output(['netstat', '-s'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # Инициализация переменных для хранения принятых и переданных пакетов
        net_pps_receive = 0
        net_pps_transmit = 0

        # Поиск строк с информацией о принятых и переданных пакетах
        for line in lines:
            if "packets received" in line:
                net_pps_receive = int(line.strip().split()[0])
            elif "packets sent" in line:
                net_pps_transmit = int(line.strip().split()[0])

        return net_pps_receive, net_pps_transmit
    except Exception as e:
        logging.error("Ошибка при получении net_pps_summary: %s", e)
        return 0, 0


# 10. net_summary: receive_speed
def get_receive_speed(interface: str) -> float:
    """
    Получение скорости приема данных по сети для указанного интерфейса.

    Аргументы:
        interface (str): Имя сетевого интерфейса (например, 'eth0').

    Возвращает:
        float: Скорость приема данных по сети в кБ/с.
               При ошибке возвращает 0.
    """
    try:
        output = subprocess.check_output(['ifstat', '1', '1'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        # 1 строка - интерфейсы, 2 строка - заголовки, 3 строка - данные
        interfaces = lines[0].split()
        data_line = lines[2].split()

        # Находим индекс интересующего интерфейса
        if interface in interfaces:
            interface_index = interfaces.index(interface)
            receive_speed_kbps = safe_float_conversion(
                data_line[interface_index * 2])  # KB/s in
            return receive_speed_kbps
        else:
            logging.warning("Интерфейс %s не найден в выводе ifstat.",
                            interface)
            return 0
    except Exception as e:
        logging.error("Ошибка при получении net_summary %s: %s", interface, e)
        return 0


# 11. tcp_currestab
def get_tcp_current_connections() -> int:
    """
    Получение числа активных TCP соединений.

    Возвращает:
        int: Число активных TCP соединений.
             При ошибке возвращает 0.
    """
    try:
        output = subprocess.check_output(['netstat', '-s'],
                                         stderr=subprocess.STDOUT).decode()
        lines = output.splitlines()

        for line in lines:
            if "connections established" in line:
                active_connections = int(line.strip().split()[0])
                return active_connections

        logging.warning("Активные TCP соединения не найдены.")
        return 0
    except Exception as e:
        logging.error("Ошибка при получении активных TCP соединений: %s", e)
        return 0


# Запись данных в CSV
def write_csv(metrics: Dict[str, float], fieldnames: List[str]) -> None:
    """
    Запись метрик в CSV файл.

    Аргументы:
        metrics (Dict[str, float]): Словарь с метриками для записи.
        fieldnames (List[str]): Список имен полей (столбцов) для CSV файла.

    Возвращает:
        None
    """
    try:
        file_exists = os.path.isfile(csv_file)
        with open(csv_file, 'a', newline='') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(metrics)
            logging.info("Метрики успешно записаны в CSV")
    except Exception as e:
        logging.error("Ошибка записи в CSV: %s", e)


if __name__ == "__main__":
    logging.info("########## НАЧАЛО СБОРА МЕТРИК ##########")

    # SMART атрибуты
    smart_attributes = {
        "1": "Read_Error_Rate",
        "3": "Spin-Up_Time",
        "4": "Start/Stop_Count",
        "5": "Reallocated_Sectors_Count",
        "7": "Seek_Error_Rate",
        "9": "Power-On_Hours",
        "10": "Spin_Retry_Count",
        "12": "Power_Cycle_Count",
        "187": "Reported_UNC_Errors",
        "188": "Command_Timeout",
        "191": "G-sense_error_rate",
        "192": "Power-off_Retract_Count",
        "193": "Load/Unload_Cycle_Count",
        "194": "Temperature_Celsius",
        "198": "Uncorrectable_Sector_Count",
        "199": "UltraDMA_CRC_Error_Count"
    }

    # Подготовка заголовков CSV
    fieldnames = ["date", "serial_number", "model", "disk_status",
                  "io_queue_size", "read_throughput", "read_queue_time",
                  "read_qps", "write_qps",
                  "write_queue_time", "write_throughput",
                  "disk_max_util", "disk_avg_util", "tcp_outsegs",
                  "page_in", "page_out", "total_disk_read_kb",
                  "total_disk_write_kb", "mem_res", "cpu_kernel",
                  "udp_outdatagrams", "udp_indatagrams",
                  "net_pps_receive", "net_pps_transmit",
                  "receive_speed", "tcp_currestab"]

    # Добавление SMART атрибутов
    for id in sorted(smart_attributes.keys(), key=int):
        fieldnames.append(f"smart_{id}_normalized")
        fieldnames.append(f"smart_{id}_raw")

    # Получение списка дисков и сбор данных
    disks = get_disk_list()
    for disk in disks:
        logging.info(f"Сбор метрик для диска: {disk}")

        # Получение модели и серийного номера диска
        model, serial_number = get_disk_info(disk)

        # Получение SMART-данных
        logging.info(f"Сбор показателей SMART ({disk})")
        smart_data = get_smart_data(disk)
        if smart_data:
            # Парсим метрики и готовим структуру для CSV
            metrics = parse_smart_metrics(smart_data, model, serial_number,
                                          required_ids=smart_attributes.keys())
            logging.info(f"Сбор метрик производительности диска ({disk})")
            # 1 Получение статуса диска
            disk_status = get_disk_status(disk)
            metrics["disk_status"] = disk_status

            # 2 Получение размера очереди I/O
            io_queue_sizes = get_io_queue_size([disk.replace("/dev/", "")])
            metrics["io_queue_size"] = io_queue_sizes.get(
                disk.replace("/dev/", ""), "NaN")

            # 3 Получение пропускной способности чтения
            read_throughput = get_read_success_throughput(
                [disk.replace("/dev/", "")], unit='KB/s')
            metrics["read_throughput"] = read_throughput.get(
                disk.replace("/dev/", ""), "NaN")

            # 4 Получение среднего времени ожидания запросов на чтение
            read_queue_times = get_read_work_item_queue_time(
                [disk.replace("/dev/", "")])
            metrics["read_queue_time"] = read_queue_times.get(
                disk.replace("/dev/", ""), "NaN")

            # 5 Получение числа успешных операций чтения в секунду
            read_qps = get_read_work_item_success_qps(
                [disk.replace("/dev/", "")])
            metrics["read_qps"] = read_qps.get(
                disk.replace("/dev/", ""), "NaN")

            # 10 Получение успешных операций записи файлов в секунду
            write_qps = get_write_work_item_success_qps(
                [disk.replace("/dev/", "")])
            metrics["write_qps"] = write_qps.get(disk.replace("/dev/", ""), 0)

            # 11 Получение среднего времени ожидания запросов на запись
            write_queue_times = get_write_work_item_queue_time(
                [disk.replace("/dev/", "")])
            metrics["write_queue_time"] = write_queue_times.get(
                disk.replace("/dev/", ""), "NaN")

            # 12 Получение пропускной способности записи
            write_throughput = get_write_success_throughput(
                [disk.replace("/dev/", "")], unit='KB/s')
            metrics["write_throughput"] = write_throughput.get(
                disk.replace("/dev/", ""), 0)

            logging.info(f"Сбор метрик производительности сервера ({disk})")
            # 1 Получение метрики утилизации дисков
            disk_util = get_disk_utilization([disk.replace("/dev/", "")])
            metrics["disk_max_util"] = disk_util["max_util"]
            metrics["disk_avg_util"] = disk_util["avg_util"]

            # 2 Получение статистики TCP сегментов через netstat
            tcp_outsegs = get_tcp_outsegs_netstat()
            metrics["tcp_outsegs"] = tcp_outsegs

            # 3 Получение активности страниц памяти (page_in/page_out)
            page_activity = get_page_activity()
            metrics["page_in"] = page_activity["page_in"]
            metrics["page_out"] = page_activity["page_out"]

            # 4 Получение общего объема данных, считанных/записанных на диски
            disk_summary = get_total_disk_read_write(
                [disk.replace("/dev/", "")])
            metrics["total_disk_read_kb"] = disk_summary["total_disk_read_kb"]
            metrics["total_disk_write_kb"] = \
                disk_summary["total_disk_write_kb"]

            # 6 Получение информации о зарезевированной памяти
            memory_summary = get_memory_summary()
            metrics["mem_res"] = memory_summary["reserved_mem_kb"]

            # 7 Получение загруженности CPU в режиме ядра
            cpu_kernel_usage = get_cpu_kernel_usage()
            metrics["cpu_kernel"] = cpu_kernel_usage

            # 8 Получение статистики UDP датаграмм
            udp_outdatagrams, udp_indatagrams = get_udp_stat_netstat()
            metrics["udp_outdatagrams"] = udp_outdatagrams
            metrics["udp_indatagrams"] = udp_indatagrams

            # 9 Получение статистики PPS
            net_pps_receive, net_pps_transmit = get_net_pps()
            metrics["net_pps_receive"] = net_pps_receive
            metrics["net_pps_transmit"] = net_pps_transmit

            # 10 Получение скорости приема данных для указанного интерфейса
            receive_speed_eno1 = get_receive_speed("eno1")  # Для eno1
            metrics["receive_speed"] = receive_speed_eno1

            # 11 Получение числа активных TCP соединений
            tcp_current_connections = get_tcp_current_connections()
            metrics["tcp_currestab"] = tcp_current_connections

            for field in fieldnames:
                if field not in metrics:
                    metrics[field] = 0

            # metrics = {key: float(value) if isinstance(value, (int, float))
            #            else value for key, value in metrics.items()}
            # print(json.dumps(metrics, indent=4))

            # Запись метрик в CSV
            write_csv(metrics, fieldnames)
            send_metrics_to_server(metrics)
    logging.info("########## СБОР МЕТРИК ЗАВЕРШЕН ##########")
