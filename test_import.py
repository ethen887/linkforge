"""Verify that the LinkForge package structure can be imported correctly."""

import importlib
import sys
from pathlib import Path


def verify_imports() -> bool:
    """Verify that core LinkForge modules and public objects can be imported.

    Returns:
        bool: True if all imports succeed, otherwise False.
    """
    project_root = Path(__file__).resolve().parent
    src_path = project_root / "src"

    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    try:
        importlib.import_module("linkforge")
        print("✓ Main package imported successfully")

        importlib.import_module("linkforge.config")
        print("✓ Config module imported successfully")

        importlib.import_module("linkforge.agent")
        print("✓ Agent module imported successfully")

        importlib.import_module("linkforge.llm")
        print("✓ LLM module imported successfully")

        importlib.import_module("linkforge.tools")
        print("✓ Tools module imported successfully")

        config_module = importlib.import_module("linkforge.config")
        getattr(config_module, "ModelConfig")
        print("✓ ModelConfig imported successfully")

        agent_module = importlib.import_module("linkforge.agent")
        getattr(agent_module, "RecAgent")
        print("✓ RecAgent imported successfully")

        llm_module = importlib.import_module("linkforge.llm")
        getattr(llm_module, "LLM")
        print("✓ LLM imported successfully")

        tools_module = importlib.import_module("linkforge.tools")
        getattr(tools_module, "weather_tool")
        print("✓ Weather tool imported successfully")

    except Exception as exc:
        print(f"✗ Import verification failed: {exc}")
        return False

    print("\nAll imports successful! Migration is structurally sound.")
    return True


def main() -> int:
    """Run LinkForge import verification.

    Returns:
        int: Process exit code, where 0 means success and 1 means failure.
    """
    return 0 if verify_imports() else 1


if __name__ == "__main__":
    raise SystemExit(main())
