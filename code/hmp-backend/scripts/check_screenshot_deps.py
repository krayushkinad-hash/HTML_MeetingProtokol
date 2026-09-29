"""
E265: Проверка зависимостей для US-019/US-092 (авто-скриншоты).
Запускать перед использованием change_detection стратегии.
"""
import sys


def check_imports() -> int:
    """Проверяет что все нужные модули установлены."""
    errors = []

    try:
        import fastapi
        print(f"✅ fastapi {fastapi.__version__}")
    except ImportError:
        errors.append("fastapi missing — pip install fastapi")

    try:
        from PIL import Image
        import PIL
        print(f"✅ Pillow {PIL.__version__}")
    except ImportError:
        errors.append("Pillow missing — pip install pillow")

    try:
        import imagehash
        print(f"✅ imagehash {imagehash.__version__}")
    except ImportError:
        errors.append("imagehash missing — pip install imagehash")

    try:
        import subprocess as sp
        # Проверяем что ffmpeg доступен в PATH
        r = sp.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            version_line = r.stdout.split("\n")[0] if r.stdout else "?"
            print(f"✅ ffmpeg available: {version_line}")
        else:
            errors.append("ffmpeg not found in PATH")
    except FileNotFoundError:
        errors.append("ffmpeg not installed")
    except Exception as e:
        errors.append(f"ffmpeg check failed: {e}")

    print()
    if errors:
        print("❌ Missing dependencies:")
        for err in errors:
            print(f"   - {err}")
        print("\nFix:")
        print("   cd code/hmp-backend")
        print("   .venv\\Scripts\\pip.exe install pillow imagehash")
        print("   # или для Linux:")
        print("   pip install pillow imagehash")
        return 1
    else:
        print("✅ All screenshot dependencies installed")
        return 0


if __name__ == "__main__":
    sys.exit(check_imports())
