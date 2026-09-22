# 🚀 HTML_MeetingProtokol — Quick Start

## Самый простой путь (5 минут)

### Шаг 1: Скопируйте проект

1. Скачайте `HTML_MeetingProtokol-v1.0.0.zip`
2. Создайте папку `C:\HTML_Protokol\`
3. **Распакуйте архив** так, чтобы в `C:\HTML_Protokol\` оказались файлы:
   ```
   C:\HTML_Protokol\
   ├── start.bat
   ├── stop.bat
   ├── fix-install.bat
   ├── fix-install.ps1
   ├── code\
   ├── scripts\
   └── ... (другие файлы)
   ```

**Путь должен быть БЕЗ КИРИЛЛИЦЫ** — это важно!

### Шаг 2: Установите зависимости backend (5-10 минут)

Откройте **PowerShell от Администратора**:
```powershell
cd C:\HTML_Protokol
powershell -ExecutionPolicy Bypass -File .\fix-install.ps1
```

Это создаст `.venv` в `code\hmp-backend\` и установит все пакеты (fastapi, uvicorn, pydantic, etc).

Или CMD:
```cmd
cd C:\HTML_Protokol
fix-install.bat
```

### Шаг 3: Запуск

Двойной клик на `start.bat` — откроются:
- Backend на http://127.0.0.1:8000
- API docs на http://127.0.0.1:8000/docs
- Frontend на http://127.0.0.1:5173

### Шаг 4: Проверка

Откройте http://127.0.0.1:8000/health — должно вернуть:
```json
{"status":"ok","version":"1.0.0","env":"development"}
```

---

## 📋 Структура после установки

```
C:\HTML_Protokol\
├── start.bat                      ← запустить backend+frontend
├── stop.bat                       ← остановить
├── fix-install.bat / .ps1         ← переустановить backend
├── deploy-windows.ps1             ← полная установка (Docker, WSL2, etc)
├── cleanup-docker.bat / .ps1      ← удалить Docker
├── fix-wsl.bat / .ps1             ← обновить WSL2
├── install-docker-only.bat / .ps1 ← только Docker Desktop
├── code\
│   ├── hmp-backend\
│   │   ├── .venv\                 ← создаётся fix-install.ps1
│   │   ├── app\                   ← FastAPI код
│   │   ├── requirements-minimal.txt
│   │   └── ...
│   └── hmp-frontend\
│       └── public\index.html
├── scripts\
│   └── ... (дополнительные утилиты)
└── README.md
```

---

## 🔧 Что делает каждый скрипт

| Скрипт | Назначение |
|---|---|
| **`start.bat`** | Главный скрипт. Запускает backend + frontend |
| `stop.bat` | Закрывает backend + frontend окна |
| **`fix-install.bat` / `.ps1`** | Устанавливает Python зависимости в `.venv` |
| `deploy-windows.ps1` | Полная установка (Docker, WSL, backend, ML модели) |
| `cleanup-docker.bat / .ps1` | Удаляет Docker Desktop |
| `fix-wsl.bat / .ps1` | Обновление WSL2 |
| `install-docker-only.bat / .ps1` | Только Docker Desktop |

---

## ⚠️ Частые проблемы

### "Python не найден"
Установите Python 3.10+ с https://www.python.org/downloads/
При установке включите **"Add to PATH"**.

### "Docker не найден"  
Docker Desktop устанавливается через `deploy-windows.ps1` или вручную с https://www.docker.com/products/docker-desktop/

### Кириллица в путях
**Не используйте** папки с кириллицей. Только латиница:
- ✅ `C:\HTML_Protokol\`  
- ❌ `C:\Проекты\IT Архитектор\AI\HTML_Protokol\`

### uvicorn не найден
Запустите `fix-install.bat` — он пересоздаст `.venv` с правильными пакетами.

---

## 📊 URL после запуска

| URL | Что |
|---|---|
| http://127.0.0.1:8000 | Backend |
| http://127.0.0.1:8000/docs | Swagger UI (API документация) |
| http://127.0.0.1:8000/health | Health check |
| http://127.0.0.1:5173 | Frontend (UI) |
| http://127.0.0.1:5173/upload | Загрузить протокол |
| http://127.0.0.1:5173/calendar | Календарь |

---

## 🎯 Следующие шаги после запуска

1. Загрузите аудио через `/upload`
2. Дождитесь транскрипции (5-15 минут для 1 часа аудио)
3. Просмотрите результат в `/protocols/{id}`
4. Экспортируйте в DOCX кнопкой "Export"
