"""Rewrite Capacitor server.url before an iOS/Android native build."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: point_ios_server.py https://hosted-desk.example")
    url = sys.argv[1].strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SystemExit("COVE_SERVER_URL must be https://your-hosted-desk")
    host = parsed.hostname.lower()
    if host in {"127.0.0.1", "localhost"} or host.endswith("trycloudflare.com"):
        raise SystemExit("Do not ship a PC tunnel URL in the TestFlight IPA.")

    cfg_path = ROOT / "mobile" / "capacitor.config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    server = cfg.setdefault("server", {})
    server["url"] = url
    nav = list(server.get("allowNavigation") or [])
    extras = [host, "evolutionfreedomltd.co.uk", "*.evolutionfreedomltd.co.uk"]
    if host.endswith(".fly.dev"):
        extras.append("*.fly.dev")
    if host.endswith(".onrender.com"):
        extras.append("*.onrender.com")
    for item in extras:
        if item not in nav:
            nav.append(item)
    server["allowNavigation"] = nav
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (ROOT / "mobile" / "www" / "server.json").write_text(
        json.dumps({"url": url}) + "\n", encoding="utf-8"
    )
    print(f"iOS WebView will load {url}")


if __name__ == "__main__":
    main()
