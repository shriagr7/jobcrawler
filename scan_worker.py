from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RoleRadar detached background scan worker"
    )
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    state_path = Path(args.state).resolve()
    log_path = Path(args.log).resolve()

    state = read_json(state_path)
    state["worker_pid"] = os.getpid()
    state["status"] = "running"
    state["worker_started_at"] = now()
    write_json(state_path, state)

    env = os.environ.copy()
    env["ROLERADAR_CONFIG_PATH"] = str(config_path)
    env["PYTHONUNBUFFERED"] = "1"

    exit_code = 1

    try:
        with log_path.open(
            "a", encoding="utf-8", errors="replace"
        ) as log:
            log.write(
                f"\nBackground worker accepted scan "
                f"{args.scan_id} at {now()}\n"
            )
            log.flush()

            proc = subprocess.run(
                [
                    sys.executable,
                    "-u",
                    str(Path(__file__).with_name("agent.py")),
                ],
                cwd=str(Path(__file__).resolve().parent),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
            exit_code = int(proc.returncode)

    except Exception as exc:
        with log_path.open(
            "a", encoding="utf-8", errors="replace"
        ) as log:
            log.write(
                f"\nWORKER ERROR: {type(exc).__name__}: {exc}\n"
            )
        exit_code = 1

    latest = read_json(state_path)
    latest["status"] = (
        "completed" if exit_code == 0 else "failed"
    )
    latest["exit_code"] = exit_code
    latest["finished_at"] = now()
    latest["message"] = (
        "Scan completed successfully."
        if exit_code == 0
        else (
            f"Crawler exited with code {exit_code}. "
            "Open the live scan log for details."
        )
    )
    write_json(state_path, latest)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
