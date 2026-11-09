# The Paxen iPhone app

The iPhone app is a native React Native app built with Expo (`mobile/`), with the same screens, wording and design
tokens as the web app (designed in v0). It talks to the same API. Its data contract and wording are shared with the
web app: `mobile/src/shared/` is copied from `web/lib/` (`npm run sync-shared`; CI fails if they drift). Alerts arrive
as native notifications through Apple's push service (`backend/paxen/apns.py`), and the live trip shows Apple Maps.
A GitHub Actions workflow generates the Xcode project (`expo prebuild`), builds it on a cloud Mac and uploads it to
TestFlight (`.github/workflows/ios-testflight.yml`), so no Mac is needed.

Bundle id: `com.paxdolmes.paxen` (change it in `mobile/app.config.ts`, the workflow's `BUNDLE_ID` and `APNS_TOPIC`
together if you need a different one). Until build 6 the app was the web app in a Capacitor shell (`web/ios`); that
shell is no longer built.

Run it locally: `cd mobile && npm install && npx expo start` (Expo Go or a simulator), or `npm run web` for a browser
preview. `EXPO_PUBLIC_PAXEN_API_URL` points it at another API (default: production).

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
GitHub > **Actions** > **iPhone app to TestFlight** > **Run workflow** (about 20-30 minutes on a cloud Mac, roughly
£1 of Actions minutes, so it isn't run on every merge). The build number goes up
automatically. When it's processed (another 5-30 minutes), add yourself in App Store Connect > the app >
**TestFlight > Internal Testing**, and install it with the **TestFlight** app on your iPhone.

## Notes
- Internal TestFlight testers (up to 100 people on your team) need no Apple review; external testers need a short
  beta review.
- Native apps don't send a browser origin, so `PAXEN_CORS_ORIGINS` doesn't affect the iPhone app.
- Location is asked for only on a live trip (message in `mobile/app.config.ts`), and is never stored.
- Never edit `mobile/ios`: it's generated on each build from `mobile/app.config.ts`.
- Signing reuses one distribution certificate, whose key is kept encrypted in the Actions cache (`.signing-cache`).
  The daily "TestFlight testers" job opens that cache so GitHub doesn't delete it after 7 idle days; its log also
  lists the team's distribution certificates (Apple allows only a few).

## Sharing with friends (public TestFlight link)
The "TestFlight testers" workflow runs after every build. It keeps the team in the internal "Paxen team" group, and
adds each new build to the external **Friends** group, which has a public link, then submits it for Apple's beta
review. The first review takes about a day; later builds are usually approved within hours. Friends install the
TestFlight app, open the link, and get every new build automatically. Test information and the review contact were
set on the first run (workflow inputs); the privacy policy is served by the API at `/privacy` (`backend/paxen/privacy.py`).
