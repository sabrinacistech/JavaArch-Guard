"""CLI: python -m javaarch_guard <ruta_proyecto> [--max-iter N] [--out reporte.md]"""
from __future__ import annotations

import argparse
import sys

from .config import SETTINGS
from .graph import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="javaarch_guard")
    parser.add_argument("project_path", help="Ruta al proyecto Java")
    parser.add_argument("--max-iter", type=int, default=SETTINGS.max_iterations)
    parser.add_argument("--out", default="archguard-report.md")
    parser.add_argument("--gate", type=int, default=SETTINGS.debt_score_gate,
                        help="Falla si debt_score supera este umbral")
    args = parser.parse_args(argv)

    state = run(args.project_path, args.max_iter)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(state["report_md"])

    print(f"debt_score={state['debt_score']:.0f} criticos={state['critical_count']}")
    print(f"reporte -> {args.out}")

    if state["critical_count"] > 0 or state["debt_score"] > args.gate:
        print("QUALITY GATE: FAIL", file=sys.stderr)
        return 1
    print("QUALITY GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
