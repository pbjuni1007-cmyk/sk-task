"""DB 경로를 명시해 별도 Streamlit 프로세스를 실행한다."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8503)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    db = args.db.resolve()
    if not db.is_file():
        parser.exit(1, "DB 파일이 없습니다. seed_demo.py로 먼저 생성해 주세요.\n")
    load_dotenv(args.env_file)
    os.environ["PURCHASE_DB_PATH"] = str(db)
    print(f"사용 DB: {db}", flush=True)
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "app.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(args.port),
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=ROOT,
        )
    )
