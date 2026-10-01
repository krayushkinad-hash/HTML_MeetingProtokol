"""E284: общие helpers для тестов."""
from typing import Any, Iterable


def assert_response_shape(response_dict: dict, required_keys: Iterable[str]) -> None:
    """Проверяет что response_dict содержит все required_keys."""
    for key in required_keys:
        assert key in response_dict, f"Key {key!r} отсутствует в {list(response_dict.keys())}"


def extract_json(response) -> Any:
    """Извлекает JSON из httpx Response или dict."""
    if hasattr(response, 'json'):
        return response.json()
    return response


def mock_subprocess_result(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Создаёт mock результат subprocess.run."""
    class R:
        pass
    r = R()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r
