"""Create/update local verified-GitHub settings without printing credentials."""

import argparse
import os
import secrets
from pathlib import Path
from urllib.parse import quote

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--db-port", type=int, default=5433)
parser.add_argument("--api-port", type=int, default=8000)
parser.add_argument("--ui-port", type=int, default=8501)
args = parser.parse_args()
if not all(1024 <= port <= 65535 for port in [args.db_port, args.api_port, args.ui_port]):
    parser.error("Choose ports between 1024 and 65535")
root = Path(__file__).resolve().parents[1]
target = root / ".env"
source = target if target.exists() else root / ".env.example"
lines = source.read_text().splitlines()
values = {
    line.split("=", 1)[0].strip(): line.split("=", 1)[1]
    for line in lines
    if "=" in line and not line.lstrip().startswith("#")
}
key = values.get("AUTH_ENCRYPTION_KEY", "")
if len(key) < 32:
    key = secrets.token_urlsafe(48)
changes = {
    "MODE": "real",
    "AUTH_MODE": "github",
    "READ_ONLY": "false",
    "AUTH_ENCRYPTION_KEY": key,
    "ALLOW_TOKEN_LOGIN": "true",
    "DB_PORT": str(args.db_port),
    "API_PORT": str(args.api_port),
    "UI_PORT": str(args.ui_port),
    "API_URL": f"http://localhost:{args.api_port}",
}
if not target.exists() or values.get("DATABASE_URL", "").endswith("@localhost:5433/triagedesk"):
    user = quote(values.get("POSTGRES_USER", "triagedesk"), safe="")
    password = quote(values.get("POSTGRES_PASSWORD", "triagedesk"), safe="")
    name = quote(values.get("POSTGRES_DB", "triagedesk"), safe="")
    changes["DATABASE_URL"] = f"postgresql+psycopg://{user}:{password}@localhost:{args.db_port}/{name}"
seen = set()
output = []
for line in lines:
    name = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
    if name in changes:
        output.append(f"{name}={changes[name]}")
        seen.add(name)
    else:
        output.append(line)
output += [f"{name}={value}" for name, value in changes.items() if name not in seen]
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as file:
    file.write("\n".join(output) + "\n")
target.chmod(0o600)
print("Configured verified GitHub mode; encryption key retained/generated without displaying it.")
print(f"After starting Docker Compose, open http://localhost:{args.ui_port}")
print("Fine-grained token sign-in is available. Browser sign-in additionally needs GITHUB_CLIENT_ID.")
