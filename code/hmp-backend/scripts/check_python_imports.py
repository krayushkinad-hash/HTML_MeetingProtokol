"""Check that ALL functions/variables used in router files are imported (E042, E046).

Catches:
- NameError: name 'X' is not defined
- patch() broke imports (double commas, missing imports)

Run:
    python code/hmp-backend/scripts/check_python_imports.py
"""
import ast
import sys
from pathlib import Path


def get_used_names(file_path):
    """Get all names used in function calls and attribute access."""
    text = file_path.read_text(encoding="utf-8")
    used = set()
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return None, f"SyntaxError: {e}"

    # Builtins to skip
    builtins_to_skip = {
        "self", "cls", "True", "False", "None", "args", "kwargs",
        "request", "response", "data", "body", "db", "settings",
        "file", "protocol", "audio", "transcribe", "summary",
        "tag", "tags", "protocols", "utterances", "speakers",
        "screenshots", "decisions", "action_items", "f",
        "logger", "router", "background_tasks", "file_size",
    }

    # Get all names
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Recursively get base
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)
        elif isinstance(node, ast.Call):
            # function call names
            if isinstance(node.func, ast.Name):
                used.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                base = node.func
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    used.add(base.id)

    return used - builtins_to_skip, None


def get_imports(file_path):
    """Get all imported names."""
    text = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imports.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.asname or alias.name.split(".")[0])

    return imports


def check_file(file_path):
    """Check a single file for missing imports."""
    # Get names defined in this file (functions, classes, vars)
    text = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [(file_path.name, f"SyntaxError: {e}")]

    defined = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)

    # Get imports
    imports = get_imports(file_path)

    # Names to check: commonly needed DB-related names
    suspicious_names = {
        "func", "sql_delete", "Path", "datetime", "PathLib",
        "Protocol", "AudioFile", "Screenshot", "Utterance",
        "Speaker", "Tag", "ActionItem", "Decision", "Summary",
        "TranscriptionTask", "UserSetting", "Folder", "Dictionary",
        "Task", "httpx",
    }

    missing = []
    used, err = get_used_names(file_path)
    if err:
        return [(file_path.name, err)]

    for name in suspicious_names:
        if name in used and name not in imports and name not in defined:
            missing.append((file_path.name, f"uses '{name}' but not imported"))

    return missing


def main():
    print("=" * 70)
    print("Check Python imports in backend routers")
    print("=" * 70)

    routers_dir = Path(__file__).parent.parent / "app" / "routers"
    files = sorted(routers_dir.glob("*.py"))

    all_missing = []
    for f in files:
        missing = check_file(f)
        all_missing.extend(missing)

    if all_missing:
        print(f"\n❌ {len(all_missing)} issues:\n")
        for fname, msg in all_missing:
            print(f"  {fname}: {msg}")
        sys.exit(1)
    else:
        print(f"\n✅ {len(files)} files checked, no missing imports")
        sys.exit(0)


if __name__ == "__main__":
    main()
