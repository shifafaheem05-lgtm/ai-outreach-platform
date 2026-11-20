"""Create backend/.env for LOCAL development with fresh random secrets.

Usage (from the backend folder):   python scripts/make_env.py [--force]

Copies .env.example to .env and fills SECRET_KEY and ENCRYPTION_KEY with newly generated values.
An existing .env is never overwritten unless you pass --force (its keys would be lost: mailbox
passwords already stored with the old ENCRYPTION_KEY could no longer be decrypted).
"""
import argparse
import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

BACKEND = Path(__file__).resolve().parents[1]


def build_env(template: str) -> str:
    values = {"SECRET_KEY": secrets.token_urlsafe(48), "ENCRYPTION_KEY": Fernet.generate_key().decode()}
    out = []
    for line in template.splitlines():
        key = line.split("=", 1)[0]
        out.append(f"{key}={values[key]}" if key in values and "=" in line and not line.lstrip().startswith("#") else line)
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite an existing .env (generates NEW keys)")
    ap.add_argument("--template", type=Path, default=BACKEND / ".env.example")
    ap.add_argument("--out", type=Path, default=BACKEND / ".env")
    args = ap.parse_args(argv)

    if args.out.exists() and not args.force:
        print(f"{args.out} already exists, leaving it untouched. Use --force to replace it (new keys!).")
        return 0
    args.out.write_text(build_env(args.template.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Created {args.out} with newly generated SECRET_KEY and ENCRYPTION_KEY.")
    print("Next: alembic upgrade head   then   uvicorn app.main:app --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
