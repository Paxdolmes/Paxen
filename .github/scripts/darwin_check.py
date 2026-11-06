"""Live check of the Darwin integration: Darwin actual arrivals vs TfL's countdowns for the same trains.

Consumes Darwin for a few minutes with paxen.darwin.parse (London Overground/Elizabeth line stations only) while
polling TfL's network-wide countdowns every 30 s, then reports how many actual arrivals match a TfL train and how
far TfL's predictions were from what happened. No credentials are printed.
"""
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone

import httpx
from confluent_kafka import Consumer

sys.path.insert(0, "backend")
from paxen.darwin import london_tiplocs, parse  # noqa: E402

SECONDS = int(os.environ.get("CHECK_SECONDS", "240"))
keep = london_tiplocs()
preds: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}  # (rid, stop) -> [(polled, expected)]
stop_flag = False


def poll_tfl():
    while not stop_flag:
        for mode in ("overground", "elizabeth-line"):  # one mode per request
            try:
                r = httpx.get(f"https://api.tfl.gov.uk/Mode/{mode}/Arrivals", params={"count": "-1"},
                              headers={"User-Agent": "paxen-check"}, timeout=60)
                now = datetime.now(timezone.utc)
                data = r.json()
                if not isinstance(data, list):
                    print("tfl returned", r.status_code, str(data)[:200])
                    continue
                for a in data:
                    exp = datetime.fromisoformat(a["expectedArrival"].replace("Z", "+00:00"))
                    preds.setdefault((a.get("vehicleId"), a.get("naptanId")), []).append((now, exp))
            except Exception as e:
                print("tfl poll failed:", type(e).__name__, str(e)[:200])
        time.sleep(30)


threading.Thread(target=poll_tfl, daemon=True).start()
c = Consumer({"bootstrap.servers": os.environ["DARWIN_BOOTSTRAP"], "security.protocol": "SASL_SSL",
              "sasl.mechanisms": "PLAIN", "sasl.username": os.environ["DARWIN_USERNAME"],
              "sasl.password": os.environ["DARWIN_PASSWORD"], "group.id": os.environ.get("DARWIN_GROUP") or "paxen",
              "auto.offset.reset": "latest", "enable.auto.commit": False})
c.subscribe([os.environ["DARWIN_TOPIC"]])
start, msgs, actuals = time.time(), 0, {}
while time.time() - start < SECONDS:
    m = c.poll(1.0)
    if m is None or m.error():
        continue
    msgs += 1
    for a in parse(m.value() or b"", keep):
        actuals.setdefault((a.rid, f"910G{a.tiploc}"), a.arrived_at)
c.close()
stop_flag = True
recent = {k: v for k, v in actuals.items() if v.timestamp() >= start - 120}  # arrivals during the check
matched = {k: v for k, v in recent.items() if k in preds}
rid_seen = {k for k in recent if any(r == k[0] for r, _ in preds)}
errs = {"0-2m": [], "2-5m": [], "5-10m": [], "10m+": []}
for k, at in matched.items():
    for polled, exp in preds[k]:
        lead = (exp - polled).total_seconds()
        if polled > at or lead < 0:
            continue
        b = "0-2m" if lead < 120 else "2-5m" if lead < 300 else "5-10m" if lead < 600 else "10m+"
        errs[b].append((at - exp).total_seconds())
print(f"London stations watched: {len(keep)}; Darwin messages: {msgs} in {SECONDS}s")
print(f"actual arrivals at London Overground/Elizabeth line stations: {len(recent)}")
print(f"  with the same train id in TfL's countdowns: {len(rid_seen)} ({len(rid_seen)/max(1,len(recent)):.0%})")
print(f"  with a TfL prediction for that train AND station: {len(matched)} ({len(matched)/max(1,len(recent)):.0%})")
for b, e in errs.items():
    if e:
        print(f"  TfL vs actual, lead {b}: n={len(e)} mean abs {statistics.fmean(abs(x) for x in e):.0f}s, "
              f"bias {statistics.fmean(e):+.0f}s (positive = later than TfL said)")
sys.exit(0 if recent else 1)
