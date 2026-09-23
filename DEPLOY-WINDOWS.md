# HTML_MeetingProtokol — Развертывание на Windows

## 🚀 Быстрый старт (1 команда)

### PowerShell (рекомендуется)

1. **Скачайте проект** в `C:\Users\YourName\HTML_MeetingProtokol\`
2. **Откройте PowerShell от Администратора**
3. **Запустите**:

```powershell
cd C:\Users\YourName\HTML_MeetingProtokol
powershell -ExecutionPolicy Bypass -File .\deploy-windows.ps1
```

Скрипт автоматически:
- ✅ Проверит Docker, Python, Git
- ✅ Создаст `.env` с новым `ENCRYPTION_MASTER_KEY`
- ✅ Запустит PostgreSQL в Docker
- ✅ Скачает Whisper Large-v3 (~3 ГБ)
- ✅ Скачает pyannote (если задан `PYANNOTE_TOKEN`)
- ✅ Установит Python зависимости
- ✅ Применит Alembic миграции
- ✅ Создаст ярлык `start.bat` на рабочем столе

### CMD (.bat)

```cmd
deploy-windows.bat
```

---

## 📋 Что нужно установить ДО запуска скрипта

| Компонент | Где скачать | Зачем |
|---|---|---|
| **Docker Desktop** | https://www.docker.com/products/docker-desktop/ | PostgreSQL |
| **Python 3.10+** | https://www.python.org/downloads/ | Backend |
| **Git** (опц.) | https://git-scm.com/ | Обновление проекта |
| **NVIDIA драйвер + CUDA** (опц.) | https://developer.nvidia.com/cuda-downloads | GPU-ускорение Whisper |

WSL2 — **не обязателен** (Docker Desktop работает на Hyper-V).

---

## ⚠️ После установки Docker — обязательная ПЕРЕЗАГРУЗКА

Docker Desktop требует перезагрузки для активации Hyper-V/WSL2.

1. **Закройте все программы** (Docker установщик попросит перезагрузку)
2. **Перезагрузите Windows**
3. **Откройте Docker Desktop** из Start Menu (дождитесь "Engine running" в трее)
4. **Снова запустите** `deploy-windows.ps1`

Если `docker` не находится после перезагрузки, скрипт автоматически ищет его в стандартных путях:
- `C:\Program Files\Docker\Docker\resources\bin\docker.exe`
- `C:\Program Files\Docker\Docker\bin\docker.exe`
- `C:\Users\...\AppData\Local\Programs\Docker\Docker\resources\bin\docker.exe`

---

## ⚙️ Заполните секреты ДО первого запуска

Откройте `.env` (`notepad .env`):

```ini
# HuggingFace токен для pyannote (https://huggingface.co/settings/tokens)
PYANNOTE_TOKEN=hf_xxxxxxxxxxxxxx

# AI-провайдер (опционально, для саммари/AI-фич)
LLM_PROVIDER=hermes
HERMES_API_KEY=sk-xxxxx

# Telegram бот (опционально)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_ALLOWED_IDS=8277855452
```

**Без токенов** приложение всё равно работает — просто AI-фичи будут недоступны.

---

## ⚠️ Известные проблемы с кириллическими путями

Если ваш проект лежит в папке с кириллицей (например `C:\Проекты\...`), возможны проблемы с pip/CMD. Решения:

1. **Переименовать папку в латиницу (рекомендуется)**: `C:\HTML_Protokol\`
2. **requirements-minimal.txt** уже сконвертирован в cp1251 для pip
3. **`start.bat`** использует полные пути к `uvicorn.exe`/`python.exe` (обход PATH-проблем)

**Рекомендуемая структура:**
```
C:\HTML_Protokol\                              <- простой путь без кириллицы
├── start.bat                                  <- запуск
├── stop.bat                                   <- остановка
├── fix-install.bat / .ps1                     <- переустановка backend
├── code\
│   ├── hmp-backend\                           <- FastAPI + PostgreSQL
│   └── hmp-frontend\                          <- Vanilla JS UI
└── scripts\                                   <- утилиты
```

---

## 🏃 Ежедневный запуск

После установки запускайте **одним кликом**:

```cmd
start.bat
```

Откроются:
- 🟦 Backend на http://127.0.0.1:8000 (Swagger UI: /docs)
- 🟩 Frontend на http://127.0.0.1:5173

**Остановка**: `stop.bat` или `Ctrl+C` в терминалах.

---

## 📁 Структура после установки

```
C:\Users\YourName\HTML_MeetingProtokol\
├── .env                        ← секреты (создаётся скриптом)
├── start.bat                   ← запуск
├── stop.bat                    ← остановка
├── deploy-windows.ps1          ← установщик
├── models\
│   ├── whisper\                ← Whisper Large-v3
│   └── pyannote\               ← pyannote (если токен задан)
└── code\
    ├── hmp-backend\
    │   ├── .venv\              ← Python venv
    │   └── app\                ← Backend код
    └── hmp-frontend\
        └── public\             ← Frontend
```

---

## 🛠 Ручные команды

### Backend
```cmd
cd %USERPROFILE%\HTML_MeetingProtokol\code\hmp-backend
.venv\Scripts\activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend
```cmd
cd %USERPROFILE%\HTML_MeetingProtokol\code\hmp-frontend\public
python -m http.server 5173
```

### PostgreSQL
```cmd
docker ps                    # статус
docker logs hmp-postgres     # логи
docker exec -it hmp-postgres psql -U hmp -d html_mp   # подключение к БД
docker stop hmp-postgres     # остановить
docker start hmp-postgres    # запустить
```

### Миграции
```cmd
cd %USERPROFILE%\HTML_MeetingProtokol\code\hmp-backend
.venv\Scripts\activate
alembic upgrade head         # применить
alembic downgrade -1         # откатить
```

---

## 🔧 Troubleshooting

### "Docker не найден"
→ Установите Docker Desktop, перезагрузитесь.

### "PostgreSQL не подключается"
```cmd
docker logs hmp-postgres
docker restart hmp-postgres
```

### "Port 8000 already in use"
→ Закройте другие приложения или смените порт в `.env` (SERVER_PORT).

### "PyTorch не использует GPU"
```cmd
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
```
Должно быть `True`. Если `False` — установите NVIDIA драйвер.

### "Backend не запускается"
Смотрите логи:
```cmd
cd %USERPROFILE%\HTML_MeetingProtokol\code\hmp-backend
.venv\Scripts\activate
alembic upgrade head
uvicorn app.main:app --reload
```

---

## 📊 Что внутри

- **Backend**: FastAPI 0.115+ / SQLAlchemy 2.x async / PostgreSQL 15
- **ML**: faster-whisper (Large-v3) + pyannote.audio 3.x
- **Frontend**: Vanilla JS + CSS (без фреймворков)
- **Хранение**: PostgreSQL + файлы на диске
- **Безопасность**: 152-ФЗ compliant, локальная обработка

---

## ✅ Готово!

Если всё работает — открывайте:
- 📊 **API**: http://127.0.0.1:8000/docs
- 🎨 **Frontend**: http://127.0.0.1:5173/

Загружайте первый аудиофайл через frontend и проверяйте транскрипцию.
