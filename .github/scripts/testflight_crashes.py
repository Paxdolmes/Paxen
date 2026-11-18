"""Crash reports that TestFlight testers shared (the "Share" button on TestFlight's crash prompt), from the App Store
Connect API: when, which build, device and iOS version, and what crashed. The repository is public, so this prints
only the technical crash details: never the tester's email, name or comment.

    python testflight_crashes.py            # the 10 most recent

Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from testflight_testers import BUNDLE, call, err  # noqa: E402


def summarise(text: str) -> list[str]:
    """The parts of a crash report that say what crashed. iOS writes .ips reports: a JSON header line, then JSON."""
    lines = text.splitlines()
    body = None
    for start in (1, 0):
        try:
            body = json.loads("\n".join(lines[start:]))
            break
        except ValueError:
            continue
    if not isinstance(body, dict):
        return lines[:250]  # the older plain-text format already reads top-down
    out = [f"exception: {json.dumps(body.get('exception'))}", f"termination: {json.dumps(body.get('termination'))}"]
    if body.get("asi"):
        out.append(f"application specific information: {json.dumps(body['asi'])[:2000]}")
    images = body.get("usedImages") or []

    def frame(f: dict) -> str:
        img = images[f["imageIndex"]].get("name", "?") if isinstance(f.get("imageIndex"), int) and \
            f["imageIndex"] < len(images) else "?"
        return f"    {img}  {f.get('symbol', '?')}  +{f.get('symbolLocation', f.get('imageOffset', ''))}"

    last = body.get("lastExceptionBacktrace") or []
    if last:
        out.append("last exception backtrace:")
        out += [frame(f) for f in last[:40]]
    for i, t in enumerate(body.get("threads") or []):
        if t.get("triggered"):
            out.append(f"crashed thread {i} ({t.get('name') or t.get('queue') or ''}):")
            out += [frame(f) for f in (t.get("frames") or [])[:50]]
    return out


def main() -> None:
    code, d = call("GET", f"/apps?filter[bundleId]={BUNDLE}&limit=5")
    apps = [a for a in d.get("data", []) if a["attributes"]["bundleId"] == BUNDLE]
    if not apps:
        sys.exit(f"No App Store Connect app for {BUNDLE} ({code} {err(d)})")
    aid = apps[0]["id"]
    code, d = call("GET", f"/apps/{aid}/betaFeedbackCrashSubmissions?limit=10&sort=-createdDate&include=build")
    if code >= 300:
        sys.exit(f"Crash submissions: {code} {err(d)}")
    builds = {x["id"]: x["attributes"].get("version") for x in d.get("included", []) if x["type"] == "builds"}
    subs = d.get("data", [])
    print(f"{len(subs)} shared crash report(s)")
    for s in subs:
        a = s["attributes"]
        bid = (s.get("relationships", {}).get("build", {}).get("data") or {}).get("id")
        print(f"\n=== {a.get('createdDate')}  build {builds.get(bid, '?')}  {a.get('deviceModel')}  iOS {a.get('osVersion')}"
              f"  up {a.get('appUptimeInMilliseconds')} ms")
        code, log = call("GET", f"/betaFeedbackCrashSubmissions/{s['id']}/crashLog")
        text = (log.get("data") or {}).get("attributes", {}).get("logText") if code < 300 else None
        if not text:
            print(f"  (no crash log: {code} {err(log)})")
            continue
        for line in summarise(text):
            print(line[:400])


if __name__ == "__main__":
    main()
