"""Only the loader of the shared world reads its truth (lumen-world README, "The truth guard"): the check runs from the
copy vendored in world/, so this desk needs neither lumen-world nor the network to check itself."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_only_the_world_loader_reads_the_truth():
    spec = importlib.util.spec_from_file_location("world_guard", ROOT / "world" / "guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    assert guard.violations(ROOT, ["src/market/sim/lumen.py"]) == []
