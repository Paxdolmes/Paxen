"""Paxen's privacy policy, served at /privacy. Keep it true to what the code does: if storage changes, change this."""

UPDATED = "10 November 2026"
CONTACT = "dan124@live.ie"

PAGE = f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paxen privacy policy</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#57534e; --rule:#e7e5e4; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#0c0a09; --fg:#f5f5f4; --muted:#a8a29e; --rule:#292524; }} }}
body {{ background:var(--bg); color:var(--fg); font:16px/1.6 -apple-system, system-ui, sans-serif; margin:0; }}
main {{ max-width:680px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:28px; margin:0 0 4px; }} h2 {{ font-size:18px; margin:32px 0 8px; }}
p, li {{ color:var(--fg); }} .muted {{ color:var(--muted); }} ul {{ padding-left:20px; }}
hr {{ border:0; border-top:1px solid var(--rule); margin:32px 0; }}
</style></head><body><main>
<h1>Paxen privacy policy</h1>
<p class="muted">Last updated {UPDATED}</p>

<p>Paxen is a London commute assistant. It is built to need as little about you as possible: there is no sign-up,
and Paxen never asks for your name, email address or phone number.</p>

<h2>What Paxen stores</h2>
<ul>
<li><strong>An anonymous account.</strong> The app creates a random key on your phone. The server keeps only a scrambled
(hashed) copy of it, so it can recognise your phone but not who you are.</li>
<li><strong>Your saved places and commutes</strong>, such as Home and Work, rounded to about 10 metres, with the stops you
prefer and the times you usually travel.</li>
<li><strong>Your journeys</strong>: when a trip started and finished, and the route, so Paxen can learn what a normal journey
is for you.</li>
<li><strong>Alerts</strong> Paxen sent you, and your rating of them if you gave one.</li>
<li><strong>Your settings</strong>: quiet hours, alert thresholds, and whether monitoring is paused.</li>
<li><strong>A notification token</strong>, if you allow notifications. Apple (or your browser's push service) issues it so
Paxen can send alerts to your device. It identifies the device for notifications only.</li>
</ul>

<h2>Location</h2>
<p>If you allow location, your phone's position is sent only while you have a live trip open, to show your progress
and the next departure. It is used for that one response and is never stored.</p>
<p><strong>Automatic trips</strong> (off unless you turn it on in You): your iPhone watches an area of about 150 m
around your Home and Work, using its built-in low-power area alerts. When you leave or reach one of them, the app
sends only which place and the time (for example "left Home at 08:03"), never your position. Paxen uses these to
time your commute. A trip that took far longer than any route would (say you stopped at the shops) is deleted, not
kept. Turn it off at any time in You; the iPhone then stops watching the areas. Paxen still never tracks where you
go in between.</p>

<h2>What Paxen does not do</h2>
<ul>
<li>No advertising, no ad tracking, no selling or sharing of your data.</li>
<li>No analytics in the iPhone app.</li>
<li>Your data is never used to identify you, and never combined with data from other companies.</li>
</ul>

<h2>Transport and weather data</h2>
<p>Live and historical transport data comes from Transport for London and National Rail; weather comes from
Open-Meteo. Paxen records this public data to improve its predictions. None of it contains anything about you.
Your own journeys may be used, without your account, to measure how accurate Paxen's predictions are.</p>

<h2>Where it is kept</h2>
<p>Paxen's server and database run on Railway, in the EU (europe-west4). The web app is served by Vercel.
Notifications are delivered by Apple Push Notification service or your browser's push service.</p>

<h2>Deleting your data</h2>
<p>In the app, go to <strong>You → Privacy</strong>. <em>Clear journey history</em> deletes your trips and alerts.
<em>Delete account</em> deletes everything Paxen holds about you, immediately. Deleting the app without doing this
leaves the anonymous account unused; it holds nothing that identifies you.</p>

<h2>Children</h2>
<p>Paxen isn't directed at children under 13.</p>

<h2>Changes and contact</h2>
<p>If this policy changes, the date above changes with it. Questions: <a href="mailto:{CONTACT}">{CONTACT}</a>.</p>
<hr><p class="muted">Contains public sector information licensed under the Open Government Licence. Powered by TfL Open Data.</p>
</main></body></html>
"""
