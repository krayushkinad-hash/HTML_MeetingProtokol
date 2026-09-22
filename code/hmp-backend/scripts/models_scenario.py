"""US-058: Whisper Models - Scenario rules.

Scenario:
1. NO SILENT DOWNLOADS — explicit user action required
2. VALIDATE before every action with clear user messages
3. UI must show model status at all times

States:
- AVAILABLE: model file exists in HF cache, can be used for transcription
- NOT_DOWNLOADED: model file missing from cache
- DOWNLOADING: progress 0-100%
- ACTIVE: marked in user_setting.whisper_model

Validation rules:
1. Before transcription: active model MUST be in AVAILABLE state
2. Before "Скачать" button: just checks disk space + connectivity
3. Before "Сделать активной": model MUST be in AVAILABLE state
4. Before "Удалить": if model is active, warn user or block

User messages:
- "Модель не выбрана" → user must pick one in Settings
- "Модель не скачана" → user must download first
- "Идёт загрузка (45%)" → wait for completion
- "Модель удалена, выберите другую" → if active was deleted
"""

import sys
from pathlib import Path

# Добавляем backend в path
BACKEND_PATH = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_PATH))


# ====================================================================
# SCENARIO 1: User opens Settings → Transcription
# ====================================================================
SCENARIO_1_DESCRIPTION = """
User opens Settings → Transcription tab.

UI MUST show:
1. Current selected model in `<select>`
2. Status badge next to selected model:
   - 🟢 "Скачана" (model is downloaded)
   - 🔴 "Не скачана" (model selected but file missing)
   - 🟡 "Загружается 45%" (download in progress)
3. If status is 🔴, show inline button:
   - [📥 Скачать модель] → opens download confirmation
4. Always show link to [🎤 Управление моделями] → /whisper page
"""


# ====================================================================
# SCENARIO 2: User clicks [📥 Скачать модель] in Settings
# ====================================================================
SCENARIO_2_DESCRIPTION = """
User clicks Download button.

UI MUST:
1. Show modal: "Скачать модель 'large-v3' (~3 GB)?"
   - [Cancel]
   - [Download] (primary button)
2. NO silent download — explicit confirmation
3. After click → progress bar appears
4. On completion → toast "✅ Модель large-v3 скачана"

Backend MUST:
1. POST /whisper/download/{name} returns 202 Accepted
2. Background task downloads
3. Status: 0% → 100%
4. NO automatic next steps
"""


# ====================================================================
# SCENARIO 3: User opens /whisper page (Управление моделями)
# ====================================================================
SCENARIO_3_DESCRIPTION = """
User navigates to #/whisper page.

UI MUST show grid of model cards:
1. For each model:
   - Name (tiny, base, small, medium, large-v2, large-v3)
   - Size (75 MB, 140 MB, etc.)
   - Status:
     - 🟢 Скачана (path + size_on_disk)
     - 🔴 Не скачана
     - 🟡 Загружается X%
   - Action buttons based on status:
     - 🔴 Not downloaded: [📥 Скачать]
     - 🟢 Downloaded + NOT active: [✓ Сделать активной] + [🗑 Удалить]
     - 🟢 Downloaded + IS active: [ACTIVE] badge (no buttons)
     - 🟡 Downloading: [Отменить загрузку]
"""


# ====================================================================
# SCENARIO 4: User clicks [📥 Скачать] in /whisper
# ====================================================================
SCENARIO_4_DESCRIPTION = """
User clicks Download in model card.

UI MUST:
1. Show inline progress bar on the card
2. Update every 1 second via /progress endpoint
3. Don't navigate away
4. On success → toast "✅ tiny скачана"
5. On failure → toast "❌ Ошибка: <reason>"
"""


# ====================================================================
# SCENARIO 5: User clicks [✓ Сделать активной]
# ====================================================================
SCENARIO_5_DESCRIPTION = """
User clicks "Make Active" on a model.

Backend MUST validate:
1. Model IS downloaded (is_downloaded(name) == True)
2. If NOT → 400 with message: "Сначала скачайте модель"

UI MUST:
1. POST /whisper/active/{name}
2. On success → update user_setting.whisper_model
3. Reload /whisper/models to update ACTIVE badges
4. Toast "✅ tiny теперь активна"

Backend MUST:
1. Set user_setting.whisper_model = name
2. Don't reload WhisperModel (lazy-loaded on next transcribe)
"""


# ====================================================================
# SCENARIO 6: User clicks [🗑 Удалить] on a model that IS active
# ====================================================================
SCENARIO_6_DESCRIPTION = """
User clicks Delete on active model.

UI MUST show modal:
1. "⚠️ tiny сейчас активна. Удалить её?"
   - "Транскрипция будет недоступна пока не выберете другую модель"
   - [Cancel]
   - [Delete anyway]
2. On confirm → DELETE /whisper/models/{name}
3. UI: redirect to Settings (model selection required)
4. Toast "⚠️ Модель удалена. Выберите другую для транскрипции"
"""


# ====================================================================
# SCENARIO 7: User clicks [▶ Транскрибировать] on protocol
# ====================================================================
SCENARIO_7_DESCRIPTION = """
User clicks Transcribe on a protocol.

Backend MUST validate (E070):
1. user_setting.whisper_model is set
   - If NOT → return error: "Модель не выбрана в Настройки → Транскрипция"
2. selected model IS downloaded (is_downloaded(name))
   - If NOT → check downloaded alternatives:
     - If has fallback → use it, log warning
     - If NO fallback → return error:
       "Модель '{name}' не скачана. Скачайте в Настройки → Управление моделями"
3. If valid → run transcription

UI MUST:
1. Show toast: "🔄 Транскрипция запущена"
2. Poll /progress endpoint every 1-2s
3. On error → toast "❌ Ошибка: <reason>"
4. NO silent failures — user must see ALL errors
"""


# ====================================================================
# Implementation rules
# ====================================================================
IMPLEMENTATION_RULES = """
1. NEVER call WhisperModel(name) without first checking is_downloaded(name)
   - WhisperModel() will SILENTLY download the model (E070)

2. Every error path MUST have a user-friendly Russian message
   - "Не удалось скачать модель" + reason
   - "Модель не найдена в кэше"
   - "Сначала скачайте модель в Настройки → Управление моделями"

3. UI buttons MUST validate state before action:
   - [Скачать] always available (no precondition)
   - [Сделать активной] enabled only if downloaded
   - [Удалить] enabled only if downloaded
   - [Транскрибировать] enabled only if active model is downloaded

4. State transitions must be EXPLICIT:
   - downloaded: false → true ONLY after successful download
   - active: model_a → model_b ONLY after successful API call
   - progress: 0 → 100 ONLY when actually downloading

5. NO automatic model selection:
   - User must explicitly choose model
   - If user selects large-v3 but it's not downloaded,
     show banner: "Модель не скачана" + [📥 Скачать] button
   - Don't fallback to tiny without telling user
"""


if __name__ == "__main__":
    print("=" * 70)
    print("US-058: Whisper Models Scenario Rules")
    print("=" * 70)
    print()
    print(SCENARIO_1_DESCRIPTION)
    print(SCENARIO_2_DESCRIPTION)
    print(SCENARIO_3_DESCRIPTION)
    print(SCENARIO_4_DESCRIPTION)
    print(SCENARIO_5_DESCRIPTION)
    print(SCENARIO_6_DESCRIPTION)
    print(SCENARIO_7_DESCRIPTION)
    print(IMPLEMENTATION_RULES)
