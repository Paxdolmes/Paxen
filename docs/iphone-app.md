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

## Notifications
Two kinds reach the phone through APNs (`backend/paxen/apns.py`; the API and the worker both need `APNS_KEY_ID`,
`APNS_TEAM_ID` and `APNS_PRIVATE_KEY`, because the worker sends the scheduled ones):

- **Daily briefing** (`briefing.py`), at the time set per commute in You, on the commute's days. For example:
  "To work: 6 min slower than normal / About 38 min today (usually 32). Take the Victoria → Central instead: 7 min
  quicker than your usual route. Leave 08:00, arrive about 08:31." It is sent even when everything is normal.
  Tapping it opens Today.
- **Alerts** (`engine.maybe_alert`), only when the usual route becomes clearly slower or stops running, inside the
  commute's travel window and outside quiet hours.

Both also land in the Alerts tab. To check delivery, use You → Send a test notification, then look at `/v1/health` →
`data.push`. It shows the devices registered and how the last week's alerts were delivered, and `errors_7d` gives the
reason for failed pushes. For example, `not_configured` means the worker is missing the APNs variables, and
`400 BadDeviceToken` means the wrong APNs environment.

## Automatic trips
Off until the user turns it on (You → Automatic trips, or the one-time card on Today). The app then asks for
location "Always" and has iOS watch a 150 m area around Home and Work (region monitoring: low power, and iOS wakes the
app briefly in the background even when it's closed; no background-location mode). Each crossing is sent to
`POST /v1/trips/events` as "left/reached <place> at <time>", never a position. Crossings that can't be sent wait on the
phone and go with the next one.

The server (`backend/paxen/autotrips.py`) pairs them into trips: leaving a commute's origin starts a pending trip with
Paxen's forecast for leaving at that moment; reaching the destination within 3 hours finishes it, adding ~2 minutes at
each end for the walk from the door to the edge of the area. `live.judge()` then keeps or deletes it: slower than the
slowest likely route by more than max(8 min, 20%) means a stop on the way, and less than half the quickest forecast is
impossible. Kept trips feed the personal baseline, route reliability and "trips as predicted"; deleted ones are only
counted (shown in You). Returning to where it started drops the pending trip, and a live trip that's running is ended
on arrival instead of being doubled. The same check now applies to live and hand-entered trips; invalid trips are
deleted a day later. None of this touches the network arrival model or its pre-registered evaluation.

## Home-screen widget and the trip on the lock screen

Both come from one widget extension (`expo-widgets`; layouts in `mobile/src/widgets/`). They are **left out of the
build unless asked for**, because they need an App Group that Apple's API cannot create.

**One-off, by hand** at developer.apple.com/account > Certificates, Identifiers & Profiles > Identifiers:

1. Choose **App Groups** in the filter at the top right, press **+**, and register `group.com.paxdolmes.paxen`.
2. Back under **App IDs**, open `com.paxdolmes.paxen`, press **Configure** next to App Groups, tick the group, Save.
3. Run the build once with **widgets** ticked (Actions > "iPhone app to TestFlight" > Run workflow). It registers
   `com.paxdolmes.paxen.widgets`, then stops and lists these steps because that identifier has no group yet.
4. Open `com.paxdolmes.paxen.widgets` under App IDs and tick the same group. Run the build again with widgets ticked.

What they do:

- **Widget ("Commute")**: when to leave for the next commute, whether it is running normally, and the route. Small
  and medium on the home screen; rectangular and inline on the lock screen. It is refreshed whenever the app loads
  Today. Live times are shown for 20 minutes; after that it falls back to the usual journey time, because iOS does
  not let the app refresh it on a timer.
- **Trip on the lock screen** (a Live Activity, also in the Dynamic Island): starts with a trip, shows the arrival
  time, what you are doing now and the next train. The app sends its push token to `PUT /v1/trips/{id}/activity`
  and the worker updates it once a minute (`backend/paxen/activity.py`), so it stays right with the app closed. It
  ends when the trip does. Live Activities can be switched off per app in iOS Settings; the app works without them.

Neither has been run on a phone from this repository's CI yet: the layouts compile and the server payload is
tested, but how they look needs checking on a device.
