"""Create local demo configuration without committing shared passwords."""
from pathlib import Path
import os
import secrets


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    target = root / ".env"
    values = {
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
        "APP_DB_PASSWORD": secrets.token_urlsafe(24),
        "DEMO_PASSWORD": secrets.token_urlsafe(18),
    }
    lines = []
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        key = line.partition("=")[0]
        lines.append(f"{key}={values[key]}" if key in values else line)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(".env уже существует; файл сохранён без изменений.")
        return
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    print("Создан .env. Логин: demo. Пароль находится в DEMO_PASSWORD внутри .env.")
    print("Запуск: docker compose up -d --build")


if __name__ == "__main__":
    main()
