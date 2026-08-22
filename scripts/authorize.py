"""One-time mail OAuth, run by you (not by any job).

  python scripts/authorize.py gmail work        # or bare:  authorize.py work
  python scripts/authorize.py outlook job

Gmail: reads state/google/credentials.json (a Desktop-app OAuth client), runs the
consent flow with the read-only scope, writes token_<account>.json.

Outlook: device-code flow via MSAL with the Mail.Read scope; needs MS_CLIENT_ID
set (a registered Azure/Entra public client). Writes ms_token_<account>.json.

Ernest's jobs only ever read those token files.
"""

from __future__ import annotations

import os
import sys

from ernest.config import load


def _gmail(account: str) -> None:
    from ernest.gmail import SCOPES

    cfg = load()
    client_file = os.path.join(cfg.google_credentials_dir, "credentials.json")
    if not os.path.exists(client_file):
        print(f"missing {client_file}")
        print("Create an OAuth *Desktop app* client in Google Cloud (Gmail API "
              "enabled), download it, and save it there as credentials.json.")
        sys.exit(1)
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    creds = flow.run_local_server(port=0)
    token_file = os.path.join(cfg.google_credentials_dir, f"token_{account}.json")
    os.makedirs(cfg.google_credentials_dir, exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())
    print(f"authorized gmail '{account}' (read-only) → {token_file}")


def _outlook(account: str) -> None:
    import msal

    from ernest.outlook import SCOPES, _authority, _save_cache, cache_path

    cfg = load()
    if not cfg.ms_client_id:
        print("set MS_CLIENT_ID (a registered Azure/Entra public client) first.")
        sys.exit(1)
    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(
        cfg.ms_client_id, authority=_authority(cfg), token_cache=cache
    )
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print(f"failed to start device flow: {flow}")
        sys.exit(1)
    print("\n" + flow["message"] + "\n")  # visit URL, enter the code
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"authorization failed: {result.get('error_description', result)}")
        sys.exit(1)
    path = cache_path(cfg, account)
    cache.has_state_changed = True
    _save_cache(path, cache)
    print(f"authorized outlook '{account}' (read-only) → {path}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 1:  # bare account name → gmail (back-compat)
        _gmail(args[0])
    elif len(args) == 2 and args[0] in ("gmail", "outlook"):
        (_gmail if args[0] == "gmail" else _outlook)(args[1])
    else:
        print("usage: python scripts/authorize.py [gmail|outlook] <account-name>")
        sys.exit(1)


if __name__ == "__main__":
    main()
