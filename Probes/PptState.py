"""只读连接探测：python probes/PptState.py [powerpoint|wps]。"""

import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Backend"))

from PptControl import PptError, create_controller


def main() -> int:
    selected = sys.argv[1] if len(sys.argv) > 1 else "powerpoint"
    if selected not in ("powerpoint", "wps"):
        print("用法：python probes/PptState.py [powerpoint|wps]")
        return 2
    controller = create_controller(selected)
    try:
        print(json.dumps(asdict(controller.get_state()), ensure_ascii=False, indent=2))
        return 0
    except PptError as exc:
        print(json.dumps({"code": exc.code, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        controller.close()


if __name__ == "__main__":
    raise SystemExit(main())
