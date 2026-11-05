# The Paxen iPhone app

The iPhone app is the same app as the web version (designed in v0): the web app's static build (`MOBILE_BUILD=1`)
inside a native shell (Capacitor, `web/ios`). Alerts arrive as native notifications through Apple's push service
(`backend/paxen/apns.py`). A GitHub Actions workflow builds it on a cloud Mac and uploads it to TestFlight
(`.github/workflows/ios-testflight.yml`), so no Mac is needed.

Bundle id: `com.paxdolmes.paxen` (change `appId` in `web/capacitor.config.ts`, `PRODUCT_BUNDLE_IDENTIFIER` in the
Xcode project and `APNS_TOPIC` together if you need a different one).

## One-off setup
1. **Apple Developer Program** (about £79 / $99 a year): https://developer.apple.com/programs/enroll/
2. **Create the app** in App Store Connect: https://appstoreconnect.apple.com/apps, then **+ > New App**. Platform
   iOS, name Paxen, bundle id `com.paxdolmes.paxen` (register it first at
   https://developer.apple.com/account/resources/identifiers/list, with the **Push Notifications** capability
   ticked), SKU `paxen`.
3. **App Store Connect API key** (lets the build sign and upload): https://appstoreconnect.apple.com/access/integrations/api,
   **Team Keys > +**, access **Admin**. Note the **Key ID** and **Issuer ID** and download the `.p8` file (once only).
4. **Push key** (lets the backend send notifications): https://developer.apple.com/account/resources/authkeys/list,
   **+**, tick **Apple Push Notifications service (APNs)**. Note its **Key ID**, download the `.p8`. Your **Team ID**
   is at https://developer.apple.com/account (Membership details).
5. **GitHub** (https://github.com/Paxdolmes/Paxen/settings/secrets/actions):
   - Secrets: `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_PRIVATE_KEY` (the whole API-key `.p8` file's text), `APPLE_TEAM_ID`.
   - Optional, Variables tab: `PAXEN_API_URL`, only if the API moves from https://paxen-production.up.railway.app.
6. **Railway**, on both **api** and **worker**: `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_PRIVATE_KEY` (the push key's
   `.p8` text), and optionally `APNS_TOPIC` if the bundle id differs. Redeploy.

## Each build
GitHub > **Actions** > **iPhone app to TestFlight** > **Run workflow** (about 15 minutes). The build number goes up
automatically. When it's processed (another 5-30 minutes), add yourself in App Store Connect > the app >
**TestFlight > Internal Testing**, and install it with the **TestFlight** app on your iPhone.

## Notes
- Internal TestFlight testers (up to 100 people on your team) need no Apple review; external testers need a short
  beta review.
- If `PAXEN_CORS_ORIGINS` is set, the API still allows the app's origin (`capacitor://localhost`) automatically.
- Location is asked for only on a live trip (message in `web/ios/App/App/Info.plist`).
