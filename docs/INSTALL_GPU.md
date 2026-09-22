# 🚀 Установка CUDA + cuDNN для GPU-ускорения Whisper

Это даст **5-10× ускорение** транскрипции.

## 📋 Что нужно

| Компонент | Версия | Ссылка |
|---|---|---|
| NVIDIA Driver | ≥ 525 | https://www.nvidia.com/Download/index.aspx |
| CUDA Toolkit | 12.x (для Python 3.10) | https://developer.nvidia.com/cuda-downloads |
| cuDNN | 9.x | https://developer.nvidia.com/cudnn |

## 🪜 Шаг 1: Проверить текущее состояние

```powershell
# Открыть PowerShell

# 1. Есть ли NVIDIA GPU?
nvidia-smi

# Если команда не найдена — обновить драйвер с https://www.nvidia.com/Download/index.aspx
# Должна показать вашу видеокарту и CUDA Version (driver)
```

**Если `nvidia-smi` работает** — у вас уже есть драйвер. Запишите:
- **CUDA Version** (например, 12.6) — это максимальная версия CUDA для вашего драйвера
- **Driver Version** — не ниже 525 для CUDA 12.x

## 🪜 Шаг 2: Установить CUDA Toolkit

⚠️ **Важно:** Версия CUDA должна совпадать с тем, что использует `faster-whisper` (= cuDNN 9.x).

```powershell
# 1. Скачать CUDA 12.x для Windows:
# https://developer.nvidia.com/cuda-12-6-0-download-archive?target_os=Windows
# Выбрать: Windows → x86_64 → 11 (или 10) → exe (local)

# 2. Запустить инсталлятор, выбрать Custom Installation:
#    ☑ CUDA Toolkit 12.6
#    ☐ Driver (если уже установлен свежий)
#    ☑ Other components (по желанию)

# 3. После установки проверить:
nvcc --version
# Должно показать: Cuda compilation tools, release 12.6
```

## 🪜 Шаг 3: Установить cuDNN

⚠️ **Это критическая часть для Whisper!**

```powershell
# 1. Скачать cuDNN 9.x для Windows:
# https://developer.nvidia.com/cudnn
# (требует бесплатный аккаунт NVIDIA Developer)

# 2. Распаковать архив (zip файл)

# 3. Скопировать DLL в CUDA bin:
$cuDNNPath = "C:\Users\$env:USERNAME\Downloads\cudnn-windows-x86_64-9.x.x.x_cuda12-archive"
Copy-Item "$cuDNNPath\bin\*.dll" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\"

# 4. Скопировать include:
Copy-Item "$cuDNNPath\include\*.h" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\include\" -Recurse

# 5. Скопировать lib:
Copy-Item "$cuDNNPath\lib\*.lib" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64\" -Recurse

# 6. Добавить CUDA в PATH (если не добавлен):
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin", "User")

# 7. Проверить что cudnn доступен:
where.exe cudnn64_9.dll
# Должно показать: C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\cudnn64_9.dll
```

## 🪜 Шаг 4: Переустановить faster-whisper

```powershell
cd C:\HTML_Protokol
.\.venv\Scripts\pip.exe uninstall faster-whisper ctranslate2 tokenizers -y
.\.venv\Scripts\pip.exe install faster-whisper==1.0.3
# ctranslate2 переустановится автоматически с CUDA поддержкой
```

## 🪜 Шаг 5: Проверить CUDA в Python

```powershell
.\.venv\Scripts\python.exe -c "
import ctranslate2
print('ctranslate2 version:', ctranslate2.__version__)
print('CUDA available:', ctranslate2.get_cuda_device_count())
"
```

**Если CUDA available: 0** — cuDNN не найден, проверьте шаг 3.
**Если CUDA available: 1+** — готово!

## 🪜 Шаг 6: Включить CUDA в HMP

Создать или отредактировать `.env` в `C:\HTML_Protokol\code\hmp-backend\`:

```ini
# Whisper на GPU
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# VAD настройки (опционально)
WHISPER_VAD_FILTER=false
```

## 🪜 Шаг 7: Тест

```powershell
# Запустить backend
.\restart.bat

# В логах должно быть:
# {"model": "tiny", "device": "cuda", "event": "loading_whisper_model"}
# А НЕ:
# {"model": "tiny", "device": "cpu", ...}
```

Запустить транскрипцию — должно быть **в 5-10× быстрее** чем CPU.

## 🐛 Troubleshooting

### "Could not locate cudnn_ops64_9.dll"
```powershell
# Проверить что DLL в PATH:
where.exe cudnn64_9.dll

# Если не найдена — скопировать в C:\Windows\System32
Copy-Item "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\cudnn64_9.dll" "C:\Windows\System32\"
```

### "No CUDA-capable device is detected"
```powershell
# Обновить драйвер NVIDIA:
# https://www.nvidia.com/Download/index.aspx

# Перезагрузить Windows
```

### "cuDNN version mismatch"
- cuDNN 9.x → CUDA 12.x
- cuDNN 8.x → CUDA 11.x

### ffmpeg не найден (нужен для Whisper)
```powershell
# Установить ffmpeg:
# https://www.gyan.dev/ffmpeg/builds/
# Скачать ffmpeg-release-essentials.zip
# Распаковать в C:\ffmpeg
# Добавить C:\ffmpeg\bin в PATH
```

## ⚡ Ожидаемое ускорение

| Модель | CPU (1 час аудио) | GPU (RTX 3060) | Ускорение |
|---|---|---|---|
| tiny | ~15 мин | ~1.5 мин | 10× |
| base | ~25 мин | ~3 мин | 8× |
| small | ~60 мин | ~8 мин | 7× |
| medium | ~180 мин | ~25 мин | 7× |
| large-v3 | ~480 мин | ~70 мин | 7× |

## 📋 Checklist

- [ ] `nvidia-smi` работает и показывает GPU
- [ ] CUDA Toolkit установлен (`nvcc --version`)
- [ ] cuDNN DLL в `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\`
- [ ] `ctranslate2.get_cuda_device_count()` возвращает > 0
- [ ] `WHISPER_DEVICE=cuda` в `.env`
- [ ] Backend загружает модель на GPU
- [ ] Транскрипция быстрее CPU

Если что-то не работает — создайте issue или спросите!
