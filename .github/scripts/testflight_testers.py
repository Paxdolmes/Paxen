"""TestFlight follow-through through the App Store Connect API: report the latest builds' processing state, answer
export compliance if Apple is waiting on it, and make sure every App Store Connect user of the team is an internal
tester with access to every build (so TestFlight emails them an invite). Safe to run again: it only adds what's missing.

Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH; BUNDLE_ID defaults to com.paxdolmes.paxen. Emails are masked in output.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ios_signing import API, token  # noqa: E402

BUNDLE = os.environ.get("BUNDLE_ID") or "com.paxdolmes.paxen"
GROUP_NAME = "Paxen team"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def err(d: dict) -> str:
    return "; ".join(f"{x.get('code')}: {x.get('detail')}" for x in d.get("errors", [])) or "no detail"


def mask(email: str) -> str:
    user, _, dom = email.partition("@")
    return f"{user[:2]}***@{dom}"


def main() -> None:
    code, d = call("GET", f"/apps?filter[bundleId]={BUNDLE}&limit=5")
    apps = [a for a in d.get("data", []) if a["attributes"]["bundleId"] == BUNDLE]
    if not apps:
        sys.exit(f"No App Store Connect app for {BUNDLE} ({code} {err(d)})")
    app = apps[0]["id"]
    print(f"App: {apps[0]['attributes']['name']} ({app})")

    # 1. Builds: processing state, and export compliance (a build waits silently until it's answered)
    for _ in range(20):
        code, d = call("GET", f"/builds?filter[app]={app}&sort=-uploadedDate&limit=5&include=buildBetaDetail")
        builds = d.get("data", [])
        details = {x["id"]: x["attributes"] for x in d.get("included", []) if x["type"] == "buildBetaDetails"}
        for b in builds:
            a = b["attributes"]
            bd = details.get((b["relationships"].get("buildBetaDetail", {}).get("data") or {}).get("id"), {})
            print(f"  build {a.get('version')}: uploaded {a.get('uploadedDate')}, processing {a.get('processingState')}, "
                  f"expired {a.get('expired')}, internal testing {bd.get('internalBuildState')}, "
                  f"encryption answered {a.get('usesNonExemptEncryption') is not None}")
        if builds and builds[0]["attributes"].get("processingState") == "PROCESSING":
            print("  latest build still processing; checking again in 60 s")
            time.sleep(60)
            continue
        break
    valid = [b for b in builds if b["attributes"].get("processingState") == "VALID" and not b["attributes"].get("expired")]
    for b in valid:
        if b["attributes"].get("usesNonExemptEncryption") is None:
            code, d = call("PATCH", f"/builds/{b['id']}", {"data": {"type": "builds", "id": b["id"],
                                                                   "attributes": {"usesNonExemptEncryption": False}}})
            print(f"  export compliance for build {b['attributes']['version']}: {'answered' if code < 300 else err(d)}")

    # Distribution certificates: Apple allows only a few per team, so the iPhone build reuses one (ios_signing.py)
    code, d = call("GET", "/certificates?filter[certificateType]=DISTRIBUTION,IOS_DISTRIBUTION&limit=50")
    certs = d.get("data", []) if code < 300 else []
    print(f"Distribution certificates: {len(certs)}" if code < 300 else f"Couldn't list certificates: {err(d)}")
    for c in certs:
        a = c["attributes"]
        print(f"  {c['id']}: {a.get('certificateType')}, expires {str(a.get('expirationDate'))[:10]}")

    # 2. An internal group that gets every build automatically
    code, d = call("GET", f"/betaGroups?filter[app]={app}&limit=50")
    groups = [g for g in d.get("data", []) if g["attributes"].get("isInternalGroup")]
    group = next((g for g in groups if g["attributes"].get("hasAccessToAllBuilds")), groups[0] if groups else None)
    if not group:
        code, d = call("POST", "/betaGroups", {"data": {"type": "betaGroups", "attributes": {
            "name": GROUP_NAME, "isInternalGroup": True, "hasAccessToAllBuilds": True},
            "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})
        if code >= 300:
            sys.exit(f"Couldn't create the internal testing group: {err(d)}")
        group = d["data"]
        print(f"Created internal testing group '{GROUP_NAME}' (gets every build)")
    else:
        print(f"Internal testing group: '{group['attributes']['name']}', every build: "
              f"{group['attributes'].get('hasAccessToAllBuilds')}")
    gid = group["id"]
    if not group["attributes"].get("hasAccessToAllBuilds") and valid:
        code, d = call("POST", f"/betaGroups/{gid}/relationships/builds",
                       {"data": [{"type": "builds", "id": valid[0]["id"]}]})
        print(f"  added build {valid[0]['attributes']['version']} to the group: {'ok' if code < 300 else err(d)}")

    # 3. Every team member as an internal tester (internal testers must be App Store Connect users)
    code, d = call("GET", "/users?limit=50")
    if code >= 300:
        sys.exit(f"Couldn't list the team's users (the API key needs the Admin role): {err(d)}")
    code2, d2 = call("GET", f"/betaGroups/{gid}/betaTesters?limit=200")
    already = {t["attributes"].get("email", "").lower() for t in d2.get("data", [])}
    for u in d.get("data", []):
        a = u["attributes"]
        email = (a.get("username") or a.get("email") or "").lower()
        if not email:
            continue
        if email in already:
            print(f"  {mask(email)}: already a tester")
            continue
        code, r = call("POST", "/betaTesters", {"data": {"type": "betaTesters", "attributes": {
            "email": email, "firstName": a.get("firstName") or "", "lastName": a.get("lastName") or ""},
            "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": gid}]}}}})
        if code == 409:  # a tester already exists for another group or app: link them to this group
            code3, r3 = call("GET", f"/betaTesters?filter[email]={email}&limit=1")
            tid = (r3.get("data") or [{}])[0].get("id")
            if tid:
                code, r = call("POST", f"/betaGroups/{gid}/relationships/betaTesters",
                               {"data": [{"type": "betaTesters", "id": tid}]})
        print(f"  {mask(email)}: {'added; TestFlight emails an invite' if code < 300 else err(r)}")


if __name__ == "__main__":
    main()
