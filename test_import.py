import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), "src"))

try:
    import linkforge

    print("✓ Main package imported successfully")

    import linkforge.config

    print("✓ Config module imported successfully")

    import linkforge.agent

    print("✓ Agent module imported successfully")

    import linkforge.llm

    print("✓ LLM module imported successfully")

    import linkforge.tools

    print("✓ Tools module imported successfully")

    from linkforge.config import ModelConfig

    print("✓ ModelConfig imported successfully")

    from linkforge.agent import RecAgent

    print("✓ RecAgent imported successfully")

    from linkforge.llm import LLM

    print("✓ LLM imported successfully")

    from linkforge.tools import weather_tool

    print("✓ Weather tool imported successfully")

    print("\nAll imports successful! Migration is structurally sound.")

except ImportError as e:
    print(f"✗ Import error: {e}")

except Exception as e:
    print(f"✗ Other error: {e}")
