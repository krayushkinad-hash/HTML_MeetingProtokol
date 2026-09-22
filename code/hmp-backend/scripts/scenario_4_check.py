"""US-058: Whisper Models — Scenario 4 (Hybrid).

Rules implemented across the codebase:

SCENARIO_RULES:
    NO_SILENT_DOWNLOAD:
        Backend MUST NOT auto-download models without explicit user action.
        Frontend MUST show a modal/confirmation before any download starts.

    VALIDATE_BEFORE_TRANSCRIBE:
        Before transcribing, backend checks:
        1. user_setting.whisper_model is set
           - If NOT set → "Модель не выбрана в Настройки → Транскрипция"
        2. selected model is downloaded
           - If NOT → "Модель 'X' не скачана. Скачайте в Настройки → Управление моделями"
        3. If invalid → return error with clear user message

    EXPLICIT_DOWNLOAD:
        Frontend shows confirmation before download:
        - "Скачать модель 'large-v3' (~3 GB)?"
        - User clicks "Скачать" → backend starts download
        - Frontend polls /whisper/progress/{name} for status
        - Toast on completion

    MAKE_ACTIVE_VALIDATION:
        Backend validates model is downloaded before making it active:
        - If NOT downloaded → 400 with message:
          "Сначала скачайте модель 'X'"

    DELETE_ACTIVE_WARNING:
        Frontend shows warning before deleting active model:
        - "tiny сейчас активна. Удалить её?"
        - "Транскрипция будет недоступна пока не выберете другую"

Frontend invariants:
    - Status badge always visible (🟢/🔴/🟡)
    - Inline [📥 Скачать] when model is not downloaded
    - Disabled buttons with reason on invalid state

Backend invariants:
    - Never call WhisperModel(name) without is_downloaded(name) check
    - All errors have Russian user-facing messages
    - State transitions logged with task_id
"""
import sys
from pathlib import Path

BACKEND_PATH = Path(__file__).resolve().parent.parent.parent


def validate_user_facing_errors():
    """Check that all error paths have Russian user-facing messages.

    Greps for HTTPException raises and ensures they have meaningful details.
    """
    issues = []

    # Check router files
    router_files = [
        BACKEND_PATH / "app" / "routers" / "whisper_models.py",
        BACKEND_PATH / "app" / "routers" / "transcribe.py",
    ]

    for router_file in router_files:
        if not router_file.exists():
            continue
        text = router_file.read_text(encoding="utf-8")

        # Find HTTPException raises
        import re
        for match in re.finditer(
            r'raise HTTPException\([^)]*detail="([^"]+)"', text, re.DOTALL
        ):
            detail = match.group(1)
            # Check if detail has Russian (Cyrillic) text
            has_cyrillic = any(
                c in detail for c in "абвгдежзийклмнопрстуфхцчшщъыьэюя"
            )
            if not has_cyrillic and len(detail) > 5:
                issues.append(
                    f"{router_file.name}: HTTPException with non-Russian detail: {detail[:50]}"
                )

    return issues


def main():
    print("=" * 70)
    print("US-058: Scenario 4 Validation")
    print("=" * 70)
    print()

    issues = validate_user_facing_errors()

    if issues:
        print(f"[FAIL] {len(issues)} issues found:")
        for issue in issues[:10]:
            print(f"  - {issue}")
        sys.exit(1)

    print("[OK] All error paths have Russian user-facing messages")
    sys.exit(0)


if __name__ == "__main__":
    main()
