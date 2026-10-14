import argparse
import json
import logging
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request


EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_PROBLEM = 2


def setup_logging():
    logging.basicConfig(
        filename="api_monitor.log",
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )


def load_config(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            return json.load(file)

    except FileNotFoundError:
        print(f"Помилка: файл конфігурації не знайдено: {config_path}")
        return None

    except json.JSONDecodeError as error:
        print(f"Помилка: неправильний JSON: {error}")
        return None


def make_result(
    name,
    url,
    status,
    response_time,
    failure_type,
    details
):
    return {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "target": name,
        "url": url,
        "status": status,
        "response_time": round(response_time, 3),
        "failure_type": failure_type,
        "details": details
    }


def check_endpoint(target):
    name = target["name"]
    url = target["url"]
    expected_status = target["expected_status"]
    timeout = target["timeout"]
    slow_threshold = target["slow_threshold"]

    start_time = time.perf_counter()

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "DevOps-API-Monitor/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:

            status_code = response.status
            elapsed = time.perf_counter() - start_time

            if status_code != expected_status:
                return make_result(
                    name,
                    url,
                    "PROBLEM",
                    elapsed,
                    "UNEXPECTED_STATUS",
                    (
                        f"HTTP {status_code}, "
                        f"очікувався HTTP {expected_status}"
                    )
                )

            if elapsed > slow_threshold:
                return make_result(
                    name,
                    url,
                    "PROBLEM",
                    elapsed,
                    "SLOW_RESPONSE",
                    (
                        f"Час відповіді {elapsed:.3f}s "
                        f"перевищив поріг {slow_threshold}s"
                    )
                )

            return make_result(
                name,
                url,
                "OK",
                elapsed,
                None,
                f"HTTP {status_code}"
            )

    except urllib.error.HTTPError as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "UNEXPECTED_STATUS",
            (
                f"HTTP {error.code}, "
                f"очікувався HTTP {expected_status}"
            )
        )

    except ssl.SSLCertVerificationError as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "CERTIFICATE_ERROR",
            str(error)
        )

    except ssl.CertificateError as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "CERTIFICATE_ERROR",
            str(error)
        )

    except socket.gaierror as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "DNS",
            str(error)
        )

    except ConnectionRefusedError as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "CONNECTION_REFUSED",
            str(error)
        )

    except TimeoutError as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "TIMEOUT",
            str(error)
        )

    except urllib.error.URLError as error:
        elapsed = time.perf_counter() - start_time
        reason = error.reason

        if isinstance(reason, socket.timeout):
            failure_type = "TIMEOUT"

        elif isinstance(reason, TimeoutError):
            failure_type = "TIMEOUT"

        elif isinstance(reason, ConnectionRefusedError):
            failure_type = "CONNECTION_REFUSED"

        elif isinstance(reason, socket.gaierror):
            failure_type = "DNS"

        elif isinstance(
            reason,
            (
                ssl.CertificateError,
                ssl.SSLCertVerificationError
            )
        ):
            failure_type = "CERTIFICATE_ERROR"

        else:
            failure_type = "NETWORK_ERROR"

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            failure_type,
            str(reason)
        )

    except Exception as error:
        elapsed = time.perf_counter() - start_time

        return make_result(
            name,
            url,
            "PROBLEM",
            elapsed,
            "UNKNOWN_ERROR",
            str(error)
        )


def is_network_failure(result):
    network_failures = {
        "DNS",
        "CONNECTION_REFUSED",
        "TIMEOUT",
        "CERTIFICATE_ERROR",
        "NETWORK_ERROR"
    }

    return result["failure_type"] in network_failures


def check_with_retry(target):
    result = check_endpoint(target)

    if result["status"] == "OK":
        return result

    if not is_network_failure(result):
        return result

    logging.warning(
        "Мережева помилка, буде одна повторна спроба: "
        "%s | %s | %s",
        result["target"],
        result["failure_type"],
        result["details"]
    )

    print(
        f"[RETRY] {result['target']} | "
        f"перша спроба: {result['failure_type']}"
    )

    return check_endpoint(target)


def save_results(results, output_path):
    data = {
        "check_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results
    }

    with open(
        output_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def send_webhook(result):
    webhook_url = os.getenv("MONITOR_WEBHOOK_URL")

    if not webhook_url:
        logging.info(
            "MONITOR_WEBHOOK_URL не задано, "
            "сповіщення не надсилається"
        )
        return

    message = {
        "content": (
            f"API Monitor: {result['failure_type']} | "
            f"{result['target']} | "
            f"{result['url']} | "
            f"{result['details']}"
        )
    }

    data = json.dumps(message).encode("utf-8")

    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "DevOps-API-Monitor/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=5
        ):
            pass

        logging.info(
            "Webhook успішно надіслано: %s",
            result["target"]
        )

    except Exception as error:
        logging.error(
            "Не вдалося надіслати webhook: %s",
            error
        )


def print_result(result):
    if result["status"] == "OK":
        print(
            f"[OK] {result['target']} | "
            f"{result['response_time']}s | "
            f"{result['details']}"
        )

    else:
        print(
            f"[PROBLEM] {result['target']} | "
            f"{result['failure_type']} | "
            f"{result['response_time']}s | "
            f"{result['details']}"
        )


def validate_target(target):
    required_fields = [
        "name",
        "url",
        "expected_status",
        "timeout",
        "slow_threshold"
    ]

    missing_fields = [
        field
        for field in required_fields
        if field not in target
    ]

    return missing_fields


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Перевіряє доступність HTTP/HTTPS endpoint'ів, "
            "розрізняє типи мережевих помилок, "
            "зберігає результати та надсилає сповіщення."
        )
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Шлях до JSON-файлу з endpoint'ами."
    )

    parser.add_argument(
        "--output",
        default="api_monitor_results.json",
        help="Файл для структурованих результатів."
    )

    args = parser.parse_args()

    setup_logging()

    logging.info("Запуск API monitor")

    config = load_config(args.config)

    if config is None:
        logging.error(
            "Не вдалося завантажити конфігурацію"
        )
        return EXIT_CONFIG_ERROR

    if (
        "targets" not in config
        or not isinstance(config["targets"], list)
    ):
        print(
            "Помилка: конфігурація повинна "
            "містити список 'targets'."
        )

        logging.error(
            "Некоректна структура конфігурації"
        )

        return EXIT_CONFIG_ERROR

    results = []
    has_problems = False

    for target in config["targets"]:
        missing_fields = validate_target(target)

        if missing_fields:
            target_name = target.get(
                "name",
                "unknown"
            )

            print(
                f"[ERROR] {target_name}: "
                f"відсутні параметри: "
                f"{', '.join(missing_fields)}"
            )

            logging.error(
                "Некоректна ціль %s: "
                "відсутні параметри %s",
                target_name,
                missing_fields
            )

            has_problems = True
            continue

        result = check_with_retry(target)

        results.append(result)

        print_result(result)

        if result["status"] != "OK":
            has_problems = True

            logging.error(
                "%s | %s | %s",
                result["target"],
                result["failure_type"],
                result["details"]
            )

            send_webhook(result)

        else:
            logging.info(
                "%s | OK | %s",
                result["target"],
                result["details"]
            )

    try:
        save_results(
            results,
            args.output
        )

    except OSError as error:
        print(
            f"Помилка запису результатів: {error}"
        )

        logging.error(
            "Помилка запису результатів: %s",
            error
        )

        return EXIT_CONFIG_ERROR

    logging.info("Завершення API monitor")

    if has_problems:
        return EXIT_PROBLEM

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
