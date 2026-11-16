"""Signing for the TestFlight build, done entirely through the App Store Connect API (no Mac needed).

    python ios_signing.py setup    # distribution certificate (reused) + App Store profile, keychain, Xcode settings
    python ios_signing.py cleanup  # remove the temporary keychain

One distribution certificate is created on the first build and reused: its private key is kept in the GitHub
Actions cache (SIGNING_CACHE), inside a .p12 whose password is derived from the App Store Connect key, so the
cached file is useless without that secret. (Never revoke it right after uploading: Apple checks the signature
again while processing, and rejects the build with ITMS-90721.) A new certificate is made only if the cached one
is missing, expired or revoked. Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH, TEAM_ID, BUNDLE_ID, RUNNER_TEMP,
SIGNING_CACHE.

With WIDGET_BUNDLE_ID and APP_GROUP_ID set, the widget extension (home-screen widget, trip on the lock screen) is
signed too: its identifier is registered if needed, App Groups is switched on for both identifiers and each gets
its own profile. One thing Apple's API cannot do is create the App Group and attach it to the identifiers; that is
done once by hand (docs/iphone-app.md), and the script stops with those steps if it hasn't been.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

API = "https://api.appstoreconnect.apple.com/v1"
TEMP = Path(os.environ.get("RUNNER_TEMP", "/tmp"))
STATE = TEMP / "signing-state.json"
CACHE = Path(os.environ.get("SIGNING_CACHE", str(TEMP / "signing-cache")))
PROFILE_NAME = "Paxen App Store CI"
WIDGET_PROFILE_NAME = "Paxen Widgets App Store CI"
PBXPROJ = Path(os.environ.get("PBXPROJ") or "mobile/ios/Paxen.xcodeproj/project.pbxproj")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def token() -> str:
    key = serialization.load_pem_private_key(Path(os.environ["ASC_KEY_PATH"]).read_bytes(), password=None)
    now = int(time.time())
    head = _b64(json.dumps({"alg": "ES256", "kid": os.environ["ASC_KEY_ID"], "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 1000,
                            "aud": "appstoreconnect-v1"}).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"{head}.{body}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def api(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{API}{path}", method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"App Store Connect API {method} {path} failed: {e.code} {e.read().decode()[:800]}")


def sh(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


def make_p12(cert_der: bytes, key: rsa.RSAPrivateKey, password: bytes) -> bytes:
    """A .p12 the macOS keychain can import (legacy 3DES/SHA-1 encryption, which `security import` expects)."""
    cert = x509.load_der_x509_certificate(cert_der)
    enc = (serialization.PrivateFormat.PKCS12.encryption_builder().kdf_rounds(50000)
           .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC).hmac_hash(hashes.SHA1()).build(password))
    return pkcs12.serialize_key_and_certificates(b"Paxen CI", key, cert, None, enc)


def patch_project(text: str, team: str, profile: str, bundle: str) -> str:
    """Manual distribution signing for the Release configuration of the target with this bundle identifier, and no
    other (Debug, Pods and Swift packages are untouched)."""
    # One build configuration: from its "isa" back to the "{" that opens it and on to the "};" that closes it at
    # the same depth. Xcode writes "name = Release;" after buildSettings; generated targets may write it before.
    block = re.compile(r"\{(?:(?!\{)[^}])*?isa = XCBuildConfiguration;.*?buildSettings = \{.*?\n\t\t\t\};.*?\n\t\t\};", re.S)

    def fix(m: re.Match) -> str:
        body = m.group(0)
        if "name = Release;" not in body or not re.search(rf'PRODUCT_BUNDLE_IDENTIFIER = "?{re.escape(bundle)}"?;', body):
            return body
        body = re.sub(r"\n\s*(CODE_SIGN_STYLE|CODE_SIGN_IDENTITY|PROVISIONING_PROFILE_SPECIFIER|"
                      r"DEVELOPMENT_TEAM|\"CODE_SIGN_IDENTITY\[sdk=iphoneos\*\]\") = [^;]*;", "", body)
        extra = (f'\n\t\t\t\tCODE_SIGN_STYLE = Manual;\n\t\t\t\tCODE_SIGN_IDENTITY = "Apple Distribution";'
                 f'\n\t\t\t\tDEVELOPMENT_TEAM = {team};\n\t\t\t\tPROVISIONING_PROFILE_SPECIFIER = "{profile}";')
        return body.replace("buildSettings = {", "buildSettings = {" + extra, 1)

    out = block.sub(fix, text)
    if out == text:
        sys.exit(f"Couldn't find the Release build settings for {bundle} in project.pbxproj")
    return out


def _cache_password() -> bytes:
    return hashlib.sha256(b"paxen-signing:" + Path(os.environ["ASC_KEY_PATH"]).read_bytes()).hexdigest().encode()


def _cached_certificate() -> tuple[str, bytes] | None:
    """(certificate id, p12) from the cache, if Apple still lists that certificate as valid."""
    meta, p12 = CACHE / "certificate.json", CACHE / "dist.p12"
    if not meta.exists() or not p12.exists():
        return None
    cert_id = json.loads(meta.read_text())["certificate_id"]
    req = urllib.request.Request(f"{API}/certificates/{cert_id}", headers={"Authorization": f"Bearer {token()}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            attrs = json.loads(r.read())["data"]["attributes"]
    except urllib.error.HTTPError:
        return None  # revoked or deleted
    if attrs.get("expirationDate", "9999") < time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 7 * 86400)):
        return None  # expiring within a week: make a fresh one
    return cert_id, p12.read_bytes()


def _new_certificate() -> tuple[str, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Paxen CI")]))
           .sign(key, hashes.SHA256()))
    cert = api("POST", "/certificates", {"data": {"type": "certificates", "attributes": {
        "certificateType": "DISTRIBUTION", "csrContent": csr.public_bytes(serialization.Encoding.PEM).decode()}}})["data"]
    p12 = make_p12(base64.b64decode(cert["attributes"]["certificateContent"]), key, _cache_password())
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "dist.p12").write_bytes(p12)
    (CACHE / "certificate.json").write_text(json.dumps({"certificate_id": cert["id"]}))
    print(f"Created a distribution certificate ({cert['id']}); it will be reused by later builds")
    return cert["id"], p12


APP_GROUP_HELP = """
The widget build needs the App Group "{group}", and Apple's API cannot create it. Once, at
developer.apple.com/account > Certificates, Identifiers & Profiles > Identifiers:
  1. Choose "App Groups" in the filter at the top right, press +, and register the group {group}
  2. Back under "App IDs", open {app}, press Configure next to App Groups, tick the group, Save
  3. Do the same for {widget}
Then run this build again.
"""


def ensure_bundle_id(identifier: str, label: str) -> str:
    """The App Store Connect id of an app identifier, registering it if it doesn't exist yet."""
    found = api("GET", f"/bundleIds?filter[identifier]={identifier}&limit=20")["data"]
    match = next((b["id"] for b in found if b["attributes"]["identifier"] == identifier), None)
    if match:
        return match
    made = api("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
        "identifier": identifier, "name": label, "platform": "IOS"}}})["data"]
    print(f"Registered the identifier {identifier}")
    return made["id"]


def ensure_capability(bundle_id: str, capability: str) -> None:
    have = api("GET", f"/bundleIds/{bundle_id}/bundleIdCapabilities")["data"]
    if any(c["attributes"]["capabilityType"] == capability for c in have):
        return
    api("POST", "/bundleIdCapabilities", {"data": {"type": "bundleIdCapabilities", "attributes": {
        "capabilityType": capability}, "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bundle_id}}}}})


def make_profile(name: str, bundle_id: str, cert_id: str) -> bytes:
    """A fresh App Store profile each build (so it always has the current certificate and capabilities)."""
    for old in api("GET", f"/profiles?filter[name]={urllib.parse.quote(name)}&limit=20")["data"]:
        api("DELETE", f"/profiles/{old['id']}")
    prof = api("POST", "/profiles", {"data": {"type": "profiles", "attributes": {
        "name": name, "profileType": "IOS_APP_STORE"}, "relationships": {
        "bundleId": {"data": {"type": "bundleIds", "id": bundle_id}},
        "certificates": {"data": [{"type": "certificates", "id": cert_id}]}}}})["data"]
    content = base64.b64decode(prof["attributes"]["profileContent"])
    for d in (Path.home() / "Library/MobileDevice/Provisioning Profiles",
              Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles"):
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{prof['attributes']['uuid']}.mobileprovision").write_bytes(content)
    return content


def profile_has_group(content: bytes, group: str) -> bool:
    """Whether a provisioning profile (a signed wrapper around a property list) grants this App Group."""
    m = re.search(rb"<key>com\.apple\.security\.application-groups</key>\s*<array>(.*?)</array>", content, re.S)
    return bool(m) and f"<string>{group}</string>".encode() in m.group(1)


def setup() -> None:
    team, bundle = os.environ["TEAM_ID"], os.environ["BUNDLE_ID"]
    cert_id, p12_bytes = _cached_certificate() or _new_certificate()
    state = {"certificate_id": cert_id}

    p12 = TEMP / "dist.p12"
    p12.write_bytes(p12_bytes)
    keychain, kc_pass = str(TEMP / "signing.keychain-db"), secrets.token_hex(16)
    sh("security", "create-keychain", "-p", kc_pass, keychain)
    sh("security", "set-keychain-settings", "-lut", "21600", keychain)
    sh("security", "unlock-keychain", "-p", kc_pass, keychain)
    sh("security", "import", str(p12), "-k", keychain, "-P", _cache_password().decode(), "-T", "/usr/bin/codesign",
       "-T", "/usr/bin/security")
    sh("security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", kc_pass, keychain)
    existing = subprocess.run(["security", "list-keychains", "-d", "user"], capture_output=True, text=True).stdout
    sh("security", "list-keychains", "-d", "user", "-s", keychain, *[k.strip().strip('"') for k in existing.split()])
    p12.unlink()
    state["keychain"] = keychain
    STATE.write_text(json.dumps(state))

    widget, group = os.environ.get("WIDGET_BUNDLE_ID"), os.environ.get("APP_GROUP_ID")
    targets = [(bundle, PROFILE_NAME, "Paxen")] + ([(widget, WIDGET_PROFILE_NAME, "Paxen widgets")] if widget else [])
    project = PBXPROJ.read_text()
    for identifier, name, label in targets:
        bundle_id = ensure_bundle_id(identifier, label)
        if widget:
            ensure_capability(bundle_id, "APP_GROUPS")
        content = make_profile(name, bundle_id, cert_id)
        if widget and group and not profile_has_group(content, group):
            sys.exit(APP_GROUP_HELP.format(group=group, app=bundle, widget=widget))
        project = patch_project(project, team, name, identifier)
    PBXPROJ.write_text(project)
    profiles = "".join(f"<key>{i}</key><string>{n}</string>" for i, n, _ in targets)
    (TEMP / "export.plist").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>teamID</key><string>{team}</string>
  <key>signingStyle</key><string>manual</string>
  <key>signingCertificate</key><string>Apple Distribution</string>
  <key>provisioningProfiles</key><dict>{profiles}</dict>
</dict></plist>
""")
    name = ", ".join(n for _, n, _ in targets)
    print(f"Signing ready: certificate {cert_id}, profiles: {name}")


def cleanup() -> None:
    """Only the temporary keychain goes: the certificate stays valid for Apple's processing and later builds."""
    if STATE.exists() and json.loads(STATE.read_text()).get("keychain"):
        subprocess.run(["security", "delete-keychain", json.loads(STATE.read_text())["keychain"]])


if __name__ == "__main__":
    {"setup": setup, "cleanup": cleanup}[sys.argv[1]]()
