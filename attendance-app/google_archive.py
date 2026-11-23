"""Server side Google Sheets and Drive archive queue. Never deletes history automatically."""
import base64
import json
import os
import re
import secrets
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

from psycopg.rows import dict_row

GOOGLE_ARCHIVE_URL = os.getenv("EDII_GOOGLE_ARCHIVE_URL", "").strip()
GOOGLE_ARCHIVE_TOKEN = os.getenv("EDII_GOOGLE_ARCHIVE_TOKEN", "").strip()


def configured():
    p = urlparse(GOOGLE_ARCHIVE_URL)
    return (
        p.scheme == "https"
        and p.hostname == "script.google.com"
        and p.path.startswith("/macros/s/")
        and p.path.endswith("/exec")
        and len(GOOGLE_ARCHIVE_TOKEN) >= 32
    )


def create_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS archive_outbox (
      event_id TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      entity_key TEXT NOT NULL,
      queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      archived_at TIMESTAMPTZ,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      last_error TEXT
    )""")


def enqueue(conn, kind, entity_key, event_id=None):
    if kind not in ("staff", "attendance", "plan", "submitted"):
        raise ValueError("Unsupported archive event")
    unique = event_id or (kind + ":" + secrets.token_hex(15))
    conn.execute(
       "INSERT INTO archive_outbox(event_id,kind,entity_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
       (unique, kind, str(entity_key))
    )
    return unique


def queue_existing(conn):
    """Idempotently queue every historical record, even if it predates archiving."""
    rows = [
        ("staff", conn.execute("SELECT id AS k FROM staff").fetchall()),
        ("attendance", conn.execute("SELECT id AS k FROM attendance").fetchall()),
        ("plan", conn.execute("SELECT staff_id || ':' || day::text AS k FROM work_plans").fetchall()),
        ("submitted", conn.execute("SELECT staff_id || ':' || day::text AS k FROM submitted_days").fetchall())
    ]
    for kind, found in rows:
        for row in found:
            # Stable one-time backfill events. Later actions create new events.
            enqueue(conn,kind,row["k"], "historic:" + kind + ":" + row["k"])
    return sum(len(found) for kind,found in rows)


def stats(conn):
    q=conn.execute("""SELECT COUNT(*) AS total,
      COUNT(*) FILTER (WHERE archived_at IS NULL) AS pending,
      COUNT(*) FILTER (WHERE archived_at IS NOT NULL) AS archived
      FROM archive_outbox""").fetchone()
    errors=conn.execute("""SELECT kind, entity_key, last_error, attempt_count FROM archive_outbox
      WHERE archived_at IS NULL AND last_error IS NOT NULL
      ORDER BY queued_at DESC LIMIT 6""").fetchall()
    return {
      "configured":configured(),
      "total":int(q["total"]),
      "pending":int(q["pending"]),
      "archived":int(q["archived"]),
      "errors":[{"kind":e["kind"],"key":e["entity_key"],
                 "error":e["last_error"],"attempts":e["attempt_count"]} for e in errors]
    }


def _serialize(kind, key, conn):
    if kind == "staff":
        r=conn.execute("""SELECT id,name,role,active,created_at,updated_at
            FROM staff WHERE id=%s""",(key,)).fetchone()
        if not r:return None
        return {
          "staffId":r["id"],"name":r["name"],"role":r["role"],"active":r["active"],
          "createdAt":r["created_at"].isoformat(),"updatedAt":r["updated_at"].isoformat()
        }
    if kind == "attendance":
        a=conn.execute("""SELECT a.id, a.day, a.staff_id, s.name,
          a.action, a.happened_at, a.location, a.remarks, a.latitude, a.longitude,
          a.accuracy, a.captured_at, a.gps_at, p.image FROM attendance a
          JOIN staff s ON a.staff_id=s.id JOIN photos p ON p.id=a.photo_id
          WHERE a.id=%s""",(key,)).fetchone()
        if not a:return None
        return {
          "recordId":a["id"],"date":a["day"].isoformat(),
          "staffId":a["staff_id"],"staffName":a["name"],"action":a["action"],
          "time":a["happened_at"].isoformat(),"location":a["location"],
          "remarks":a["remarks"] or "","latitude":a["latitude"],"longitude":a["longitude"],
          "accuracy":a["accuracy"],"capturedAt":a["captured_at"].isoformat(),
          "gpsAt":a["gps_at"].isoformat(),
          "photoBase64":base64.b64encode(bytes(a["image"])).decode("ascii")
        }
    if kind in ("plan","submitted"):
        staff_id, day=key.split(":",1)
        if kind == "plan":
            p=conn.execute("""SELECT p.staff_id,p.day,p.plan,p.saved_at,s.name FROM work_plans p
              JOIN staff s ON s.id=p.staff_id WHERE p.staff_id=%s AND p.day=%s""",(staff_id,day)).fetchone()
            if not p:return None
            return {"date":p["day"].isoformat(),"staffId":p["staff_id"],
              "staffName":p["name"],"plan":p["plan"],"time":p["saved_at"].isoformat()}
        p=conn.execute("""SELECT d.staff_id,d.day,d.submitted_at,s.name FROM submitted_days d
              JOIN staff s ON s.id=d.staff_id WHERE d.staff_id=%s AND d.day=%s""",(staff_id,day)).fetchone()
        if not p:return None
        return {"date":p["day"].isoformat(),"staffId":p["staff_id"],
          "staffName":p["name"],"time":p["submitted_at"].isoformat()}
    return None


def _send(event):
    if not configured():
        raise RuntimeError("Google archive has not been authorised and configured")
    payload=json.dumps({"token":GOOGLE_ARCHIVE_TOKEN,"event":event},
                       separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if len(payload)>10000000: raise ValueError("Archive payload exceeds maximum size")
    request=urllib.request.Request(
        GOOGLE_ARCHIVE_URL,data=payload,
        headers={"Content-Type":"application/json","User-Agent":"EDII-Attendance-Archive/1.0"},
        method="POST"
    )
    with urllib.request.urlopen(request,timeout=24) as response:
        answer=response.read(20000).decode("utf-8")
    try:
        decoded=json.loads(answer)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError("Google archive did not return JSON. Check deployment access.")
    if decoded.get("ok") is not True:
        raise RuntimeError(str(decoded.get("error","Archive rejected event"))[:200])
    return decoded


def test_archive():
    return _send({"kind":"ping"})


def sync_pending(conn, limit=4):
    """Returns consistent per-event result, and leaves all unsuccessful entries pending."""
    limit=max(1,min(int(limit),10))
    if not configured():
        return {"configured":False,"synced":0,"failed":0,"pending":stats(conn)["pending"],
                "message":"Google Apps Script URL and token have not been configured"}
    rows=conn.execute("""SELECT event_id,kind,entity_key FROM archive_outbox
          WHERE archived_at IS NULL ORDER BY queued_at,event_id LIMIT %s""",(limit,)).fetchall()
    ok=0;failed=0
    for row in rows:
        try:
            data=_serialize(row["kind"],row["entity_key"],conn)
            if data is None:raise RuntimeError("Original source record not available")
            _send({"kind":row["kind"],"id":row["event_id"],"data":data})
            conn.execute("""UPDATE archive_outbox SET archived_at=NOW(),
                last_error=NULL, attempt_count=attempt_count+1 WHERE event_id=%s""",(row["event_id"],))
            conn.commit()
            ok+=1
        except Exception as exc:
            # Never delete the source record or discard unsuccessful archive work.
            conn.execute("""UPDATE archive_outbox SET attempt_count=attempt_count+1,last_error=%s
                   WHERE event_id=%s""",(str(exc)[:250],row["event_id"]))
            conn.commit()
            failed+=1
    return {"configured":True,"synced":ok,"failed":failed,"pending":stats(conn)["pending"]}
