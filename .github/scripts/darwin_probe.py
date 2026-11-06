"""Connect to Darwin (Rail Data Marketplace, Kafka) for a short while and describe what arrives.

Prints message counts, the message structure and a few truncated samples: public train data only, never the
credentials. Used to build Paxen's Darwin integration against the real feed.
"""
import collections
import json
import os
import re
import sys
import time

from confluent_kafka import Consumer, KafkaException

SECONDS = int(os.environ.get("PROBE_SECONDS", "120"))
conf = {
    "bootstrap.servers": os.environ["DARWIN_BOOTSTRAP"],
    "security.protocol": "SASL_SSL",
    "sasl.mechanisms": "PLAIN",
    "sasl.username": os.environ["DARWIN_USERNAME"],
    "sasl.password": os.environ["DARWIN_PASSWORD"],
    "group.id": os.environ.get("DARWIN_GROUP") or "paxen-probe",
    "auto.offset.reset": "latest",
    "enable.auto.commit": False,
}
c = Consumer(conf)
c.subscribe([os.environ["DARWIN_TOPIC"]])
start, n, size = time.time(), 0, 0
kinds, tags, samples, errors = collections.Counter(), collections.Counter(), [], []
while time.time() - start < SECONDS:
    m = c.poll(1.0)
    if m is None:
        continue
    if m.error():
        errors.append(str(m.error()))
        continue
    n += 1
    raw = m.value() or b""
    size += len(raw)
    text = raw.decode("utf-8", "replace")
    try:
        obj = json.loads(text)
        kinds["json:" + ",".join(sorted(obj.keys()))[:120]] += 1
        inner = json.dumps(obj)
    except ValueError:
        kinds["text"] += 1
        inner = text
    for t in re.findall(r"<(?:\w+:)?(\w+)[ >/]", inner.replace('\\"', '"')):
        tags[t] += 1
    if len(samples) < 4:
        samples.append(text[:2500])
c.close()
print(f"messages: {n} in {SECONDS}s, {size/1024:.0f} KB, errors: {len(errors)} {errors[:3]}")
print("message kinds:", kinds.most_common(5))
print("XML element counts:", tags.most_common(40))
for i, s in enumerate(samples):
    print(f"--- sample {i+1} ---\n{s}\n")
sys.exit(0 if n else 1)
