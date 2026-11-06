"""External TestFlight (friends) through the App Store Connect API: test information, the beta review contact, a
"Friends" group with a public link, and each new build added and submitted for beta review. Safe to run again.

    python testflight_external.py          # after each build: add the latest build to Friends and submit it
    CONTACT_* set                         # first run: also fill in test information and the review contact

Needs ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_PATH. Optional: CONTACT_FIRST, CONTACT_LAST, CONTACT_PHONE, CONTACT_EMAIL.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from testflight_testers import BUNDLE, call, err  # noqa: E402

GROUP = "Friends"
PRIVACY_URL = "https://paxen-production.up.railway.app/privacy"
DESCRIPTION = (
    "Paxen is a commute assistant for London. Save your Home and Work, and it learns your normal journey, watches "
    "the Tube, buses, Overground, Elizabeth line and National Rail, and tells you before you leave when today isn't "
    "normal, with a better route and an honest confidence level.")
WHAT_TO_TEST = (
    "Set up Home and Work, then check Today before a journey. Try planning a trip, starting a live trip, and the "
    "alerts (You > Alerts > send a test notification). Tell us when a prediction or alert was wrong.")
REVIEW_NOTES = (
    "No login: the app creates an anonymous account on first launch. To try it, search a London place for Home "
    "(e.g. 'Orford Road') and Work (e.g. 'Regent Street'). Live data comes from Transport for London.")


def main() -> None:
    code, d = call("GET", f"/apps?filter[bundleId]={BUNDLE}&limit=5")
    app = next(a for a in d["data"] if a["attributes"]["bundleId"] == BUNDLE)
    aid, locale = app["id"], app["attributes"].get("primaryLocale") or "en-GB"
    email = os.environ.get("CONTACT_EMAIL")

    # Test information (what testers and Apple see)
    code, d = call("GET", f"/betaAppLocalizations?filter[app]={aid}&limit=20")
    locs = d.get("data", [])
    attrs = {"description": DESCRIPTION, "privacyPolicyUrl": PRIVACY_URL}
    if email:
        attrs["feedbackEmail"] = email
    if locs:
        code, d = call("PATCH", f"/betaAppLocalizations/{locs[0]['id']}",
                       {"data": {"type": "betaAppLocalizations", "id": locs[0]["id"], "attributes": attrs}})
    else:
        code, d = call("POST", "/betaAppLocalizations", {"data": {"type": "betaAppLocalizations",
                       "attributes": {**attrs, "locale": locale},
                       "relationships": {"app": {"data": {"type": "apps", "id": aid}}}}})
    print(f"Test information: {'ok' if code < 300 else err(d)}")

    # Beta review contact (Apple only)
    if email:
        code, d = call("GET", f"/apps/{aid}/betaAppReviewDetail")
        rid = d.get("data", {}).get("id")
        code, d = call("PATCH", f"/betaAppReviewDetails/{rid}", {"data": {"type": "betaAppReviewDetails", "id": rid,
                       "attributes": {"contactFirstName": os.environ["CONTACT_FIRST"],
                                      "contactLastName": os.environ["CONTACT_LAST"],
                                      "contactPhone": os.environ["CONTACT_PHONE"], "contactEmail": email,
                                      "demoAccountRequired": False, "notes": REVIEW_NOTES}}})
        print(f"Review contact: {'ok' if code < 300 else err(d)}")

    # The Friends group, with a public link
    code, d = call("GET", f"/betaGroups?filter[app]={aid}&limit=50")
    group = next((g for g in d.get("data", []) if g["attributes"]["name"] == GROUP
                  and not g["attributes"].get("isInternalGroup")), None)
    if not group:
        code, d = call("POST", "/betaGroups", {"data": {"type": "betaGroups", "attributes": {
            "name": GROUP, "publicLinkEnabled": True, "publicLinkLimitEnabled": False, "feedbackEnabled": True},
            "relationships": {"app": {"data": {"type": "apps", "id": aid}}}}})
        if code >= 300:
            sys.exit(f"Couldn't create the {GROUP} group: {err(d)}")
        group = d["data"]
        print(f"Created the {GROUP} group")
    elif not group["attributes"].get("publicLinkEnabled"):
        code, d = call("PATCH", f"/betaGroups/{group['id']}", {"data": {"type": "betaGroups", "id": group["id"],
                       "attributes": {"publicLinkEnabled": True, "publicLinkLimitEnabled": False}}})
        group = d.get("data", group)
    gid = group["id"]

    # The latest valid build: "what to test", into the group, submitted for beta review
    code, d = call("GET", f"/builds?filter[app]={aid}&filter[processingState]=VALID&filter[expired]=false"
                          f"&sort=-uploadedDate&limit=1")
    if not d.get("data"):
        sys.exit("No processed build yet")
    b = d["data"][0]
    bid, ver = b["id"], b["attributes"]["version"]
    code, d = call("GET", f"/builds/{bid}/betaBuildLocalizations")
    if not any(x["attributes"].get("whatsNew") for x in d.get("data", [])):
        if d.get("data"):
            x = d["data"][0]
            code, d = call("PATCH", f"/betaBuildLocalizations/{x['id']}", {"data": {"type": "betaBuildLocalizations",
                           "id": x["id"], "attributes": {"whatsNew": WHAT_TO_TEST}}})
        else:
            code, d = call("POST", "/betaBuildLocalizations", {"data": {"type": "betaBuildLocalizations",
                           "attributes": {"locale": locale, "whatsNew": WHAT_TO_TEST},
                           "relationships": {"build": {"data": {"type": "builds", "id": bid}}}}})
        print(f"What to test (build {ver}): {'ok' if code < 300 else err(d)}")
    code, d = call("POST", f"/betaGroups/{gid}/relationships/builds", {"data": [{"type": "builds", "id": bid}]})
    print(f"Build {ver} in {GROUP}: {'ok' if code < 300 else err(d)}")
    code, d = call("GET", f"/builds/{bid}/buildBetaDetail")
    state = d.get("data", {}).get("attributes", {}).get("externalBuildState")
    if state in ("READY_FOR_BETA_SUBMISSION", "MISSING_EXPORT_COMPLIANCE", None):
        code, d = call("POST", "/betaAppReviewSubmissions", {"data": {"type": "betaAppReviewSubmissions",
                       "relationships": {"build": {"data": {"type": "builds", "id": bid}}}}})
        print(f"Submitted build {ver} for beta review: {'ok' if code < 300 else err(d)}")
    else:
        print(f"Build {ver} external state: {state}")

    code, d = call("GET", f"/betaGroups/{gid}")
    print(f"Public link: {d.get('data', {}).get('attributes', {}).get('publicLink')}")


if __name__ == "__main__":
    main()
