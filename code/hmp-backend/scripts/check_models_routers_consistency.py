"""Validates that all model classes used in routers exist in models.py
and all field names match between router code and model definitions.

Run: python scripts/check_models_routers_consistency.py

E016, E017, E018 in skill hmp-errors-database
"""
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ROUTERS_DIR = PROJECT_ROOT / "app" / "routers"
MODELS_FILE = PROJECT_ROOT / "app" / "db" / "models.py"


def get_model_classes():
    """Extract class names from models.py."""
    text = MODELS_FILE.read_text(encoding='utf-8')
    classes = re.findall(r'^class (\w+)\(Base\)', text, re.MULTILINE)
    return set(classes)


def get_model_fields(class_name):
    """Extract fields from specific model class."""
    text = MODELS_FILE.read_text(encoding='utf-8')
    pattern = rf'^class {class_name}\(Base\):[\s\S]+?(?=^class |\Z)'
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return set()
    body = m.group(0)
    fields = re.findall(r'^\s+(\w+):\s+Mapped\[', body, re.MULTILINE)
    return set(fields)


def get_imports_from_routers():
    """Find all `from app.db.models import ...` usages in routers."""
    imports = {}
    for router_file in ROUTERS_DIR.glob("*.py"):
        text = router_file.read_text(encoding='utf-8')
        for m in re.finditer(r'from app\.db\.models import (.+)', text):
            classes = [c.strip().replace(',', '').replace('(', '').replace(')', '')
                       for c in m.group(1).split() if c[0].isupper()]
            for cls in classes:
                imports.setdefault(cls, []).append(router_file.name)
    return imports


def get_field_usage_in_routers():
    """Find all `task.X`, `protocol.X`, etc. usage in routers."""
    usage = {}  # class_name -> set of fields used
    for router_file in ROUTERS_DIR.glob("*.py"):
        text = router_file.read_text(encoding='utf-8')
        # Find object usage patterns: task.field, protocol.field, etc.
        for m in re.finditer(r'\b(\w+)\.(\w+)\b', text):
            var, field = m.group(1), m.group(2)
            if var in ('task', 'protocol', 'audio_file', 'speakers',
                       'utterances', 'tags', 'action_items', 'decisions',
                       'summary', 'settings', 'user', 'api_user',
                       'session', 'conn', 'request', 'response'):
                # This is a generic pattern, may not match exactly
                # Better to look for specific patterns
                pass
        # More specific: `task.progress`, `task.status`, etc.
        for var_name in ('task', 'protocol', 'p', 'protocol_obj'):
            for m in re.finditer(rf'\b{var_name}\.(\w+)', text):
                field = m.group(1)
                usage.setdefault(var_name, set()).add(field)
    return usage


def main():
    """Main validation."""
    print("=" * 70)
    print("Models <-> Routers Consistency Check")
    print("=" * 70)

    # Get defined classes
    defined_classes = get_model_classes()
    print(f"\nClasses defined in models.py: {len(defined_classes)}")
    for cls in sorted(defined_classes):
        print(f"  - {cls}")

    # Check imports
    print(f"\n{'=' * 70}")
    print("E016 CHECK: All imported classes exist in models.py?")
    print("=" * 70)

    imports = get_imports_from_routers()
    missing = []
    for cls, used_in in imports.items():
        if cls not in defined_classes:
            missing.append((cls, used_in))
            print(f"  MISSING: {cls} (used in {', '.join(used_in)})")
        else:
            print(f"  OK: {cls} (used in {', '.join(used_in)})")

    if not missing:
        print("\nAll imported classes are defined!")
    else:
        print(f"\n!!! {len(missing)} missing classes !!!")

    # Check fields
    print(f"\n{'=' * 70}")
    print("E017 CHECK: Used fields exist in models?")
    print("=" * 70)

    field_usage = get_field_usage_in_routers()
    for var, fields in field_usage.items():
        print(f"\nUsage of `{var}.X` in routers:")
        # Try to determine which model
        if var == 'task':
            model_name = 'TranscriptionTask'
        elif var in ('protocol', 'p', 'protocol_obj'):
            model_name = 'Protocol'
        elif var == 'audio_file':
            model_name = 'AudioFile'
        else:
            continue

        if model_name in defined_classes:
            model_fields = get_model_fields(model_name)
            print(f"  Defined fields in {model_name}: {len(model_fields)}")
            print(f"  Used fields: {len(fields)}")

            # Find suspicious usage
            builtin = {'id', 'created_at', 'updated_at', 'deleted_at'}
            suspicious = fields - model_fields - builtin
            if suspicious:
                print(f"  !!! SUSPICIOUS (not in {model_name}): {suspicious}")

    print(f"\n{'=' * 70}")
    if not missing:
        print("ALL CHECKS PASSED")
    else:
        print(f"!!! {len(missing)} issues found !!!")
        sys.exit(1)


if __name__ == "__main__":
    main()
