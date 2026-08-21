"""One-time Gmail OAuth, run by you (not by any job).

  python scripts/authorize.py work

Reads credentials.json (a Desktop-app OAuth client) from GOOGLE_CREDENTIALS_DIR,
runs the consent flow with the read-only scope, and writes token_<account>.json
there. Ernest's jobs only ever read those token files.
"""

from __future__ import annotations

import os
import sys

from ernest.config import load
from ernest.gmail import SCOPES


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python scripts/authorize.py <account-name>")
        sys.exit(1)
    account = sys.argv[1]
    cfg = load()
    creds_dir = cfg.google_credentials_dir
    client_file = os.path.join(creds_dir, "credentials.json")
    if not os.path.exists(client_file):
        print(f"missing {client_file}")
        print("Create an OAuth *Desktop app* client in Google Cloud (Gmail API "
              "enabled), download it, and save it there as credentials.json.")
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0)
    token_file = os.path.join(creds_dir, f"token_{account}.json")
    os.makedirs(creds_dir, exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"authorized '{account}' (read-only) → {token_file}")


if __name__ == "__main__":
    main()
