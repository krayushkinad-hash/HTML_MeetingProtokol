"""Check for UnboundLocalError patterns - local imports of names used elsewhere in function.

E051/E042: Python treats any assignment in a function as local. If you have:
  def init_db():
      ...  # line 100: use(UserSetting)  -- here UserSetting is from outer scope
      ...
      from app.db.models import UserSetting  # line 200: now UserSetting is LOCAL
      ...
      UserSetting()  # works (local)

  But:
  def init_db():
      from app.db.models import UserSetting  # line 50: local import
      ...
      UserSetting()  # works (local)

      if condition:
          pass  # UserSetting is still local here too

Run from project root:
    python code/hmp-backend/scripts/check_unbound_local.py
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # scripts/ -> project root
APP_DIR = PROJECT_ROOT / "code" / "hmp-backend" / "app"


def find_local_imports_in_functions(file_path):
    """Find all local imports inside functions."""
    text = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [(file_path.name, f"SyntaxError: {e}")]

    issues = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_name = node.name

            # Find all imports in this function
            local_imports = {}  # name -> line
            for n in ast.walk(node):
                if isinstance(n, ast.ImportFrom):
                    if n.module and "models" in str(n.module):
                        for alias in n.names:
                            local_imports[alias.name] = n.lineno

            if not local_imports:
                continue

            # Find all Name usages in this function (before the local import)
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    name = n.id
                    if name in local_imports and n.lineno < local_imports[name]:
                        issues.append((
                            file_path.name,
                            func_name,
                            n.lineno,
                            f"uses '{name}' at line {n.lineno} but local import at line {local_imports[name]}"
                        ))

    return issues


def main():
    print("=" * 70)
    print("Check UnboundLocalError patterns (E042, E051)")
    print("=" * 70)

    py_files = list(APP_DIR.rglob("*.py"))

    all_issues = []
    for f in py_files:
        all_issues.extend(find_local_imports_in_functions(f))

    if all_issues:
        print(f"\n❌ {len(all_issues)} potential UnboundLocalError issues:\n")
        for fname, func, line, msg in all_issues:
            print(f"  {fname}::{func} - {msg}")
        sys.exit(1)
    else:
        print(f"\n✅ {len(py_files)} Python files checked, no UnboundLocalError patterns")
        sys.exit(0)


if __name__ == "__main__":
    main()
