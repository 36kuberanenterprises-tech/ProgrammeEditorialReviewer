import base64
import hashlib
import hmac
import io
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
TZ = ZoneInfo("Asia/Kolkata")
DB = os.getenv("DATABASE_URL", "")
SESSION_COOKIE = "edii_attendance_session"
HERE = Path(__file__).parent

def connect():
    if not DB:
        raise HTTPException(status_code=503, detail="Secure database connection is being set up by the administrator.")
    return psycopg.connect(DB, row_factory=dict_row, connect_timeout=15)

def now_ist():
    return datetime.now(TZ)

def today():
    return now_ist().date()

def iso(t):
    return t.isoformat() if isinstance(t, datetime) else str(t or "")

def pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), 260000).hex()

def add_audit(conn, actor, action, target, details=""):
    conn.execute("INSERT INTO audit(actor,action,target,details) VALUES (%s,%s,%s,%s)",
                 (actor,action,target,str(details)[:300]))

def init_database():
    if not DB:
        return
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS staff(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
            salt TEXT NOT NULL, pin_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS sessions(
            token_hash TEXT PRIMARY KEY, staff_id TEXT NOT NULL REFERENCES staff(id),
            expires_at TIMESTAMPTZ NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS attempts(
            staff_id TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        c.execute("""CREATE TABLE IF NOT EXISTS photos(
            id TEXT PRIMARY KEY, staff_id TEXT NOT NULL REFERENCES staff(id),
            image BYTEA NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        c.execute("""CREATE TABLE IF NOT EXISTS attendance(
            id TEXT PRIMARY KEY, day DATE NOT NULL, staff_id TEXT NOT NULL REFERENCES staff(id),
            action TEXT NOT NULL CHECK(action IN ('IN','OUT')),
            happened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), location TEXT NOT NULL, remarks TEXT,
            latitude DOUBLE PRECISION NOT NULL, longitude DOUBLE PRECISION NOT NULL,
            accuracy DOUBLE PRECISION NOT NULL, captured_at TIMESTAMPTZ NOT NULL,
            gps_at TIMESTAMPTZ NOT NULL, photo_id TEXT NOT NULL REFERENCES photos(id),
            UNIQUE(staff_id,day,action))""")
        c.execute("""CREATE TABLE IF NOT EXISTS work_plans(
            staff_id TEXT NOT NULL REFERENCES staff(id), day DATE NOT NULL,
            plan TEXT NOT NULL, saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(staff_id,day))""")
        c.execute("""CREATE TABLE IF NOT EXISTS submitted_days(
            staff_id TEXT NOT NULL REFERENCES staff(id), day DATE NOT NULL,
            submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY(staff_id,day))""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit(
            happened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), actor TEXT NOT NULL,
            action TEXT NOT NULL, target TEXT NOT NULL, details TEXT)""")
        n = c.execute("SELECT COUNT(*) AS n FROM staff").fetchone()["n"]
        if n == 0:
            pin = os.getenv("INITIAL_ADMIN_PIN","")
            if not re.fullmatch(r"\d{6}",pin):
                raise RuntimeError("Initial admin PIN must be a six digit number")
            salt = secrets.token_hex(18)
            c.execute("INSERT INTO staff(id,name,role,salt,pin_hash,updated_by) VALUES(%s,%s,%s,%s,%s,%s)",
                      ("ADMIN001","EDII Administrator","ADMIN",salt,pin_hash(pin,salt),"INITIAL_SETUP"))
            add_audit(c,"INITIAL_SETUP","ADD_ADMIN","ADMIN001","Initial account created")

@app.on_event("startup")
def startup():
    init_database()

@app.middleware("http")
async def headers(request:Request, call_next):
    if request.method not in ("GET","HEAD","OPTIONS"):
        origin=request.headers.get("origin")
        host=request.headers.get("host","")
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != host:
                return JSONResponse({"error":"Origin not permitted"},status_code=403)
    response=await call_next(request)
    response.headers["Cache-Control"]="no-store"
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

def user_for(request):
    cookie=request.cookies.get(SESSION_COOKIE,"")
    if not re.fullmatch(r"[A-Za-z0-9_-]{40,150}",cookie):
        raise HTTPException(401,"Please sign in again")
    key=hashlib.sha256(cookie.encode()).hexdigest()
    with connect() as c:
        row=c.execute("""SELECT st.id,st.name,st.role,st.active
            FROM sessions se JOIN staff st ON st.id=se.staff_id
            WHERE se.token_hash=%s AND se.expires_at>NOW()""",(key,)).fetchone()
    if not row or not row["active"]:
        raise HTTPException(401,"Session expired or account inactive")
    return {"id":row["id"],"name":row["name"],"role":row["role"]}

def only_admin(user):
    if user["role"]!="ADMIN":
        raise HTTPException(403,"Administrator access required")

def clean_id(value):
    result=str(value or "").strip().upper()
    if not re.fullmatch("[A-Z0-9_]{3,30}",result):
        raise HTTPException(400,"Enter a valid Staff ID")
    return result

def clean_pin(value):
    result=str(value or "")
    if not re.fullmatch(r"\d{6}",result):
        raise HTTPException(400,"Use a six digit PIN")
    return result

def require_user(request):
    return user_for(request)

@app.get("/")
def homepage():
    return FileResponse(HERE/"index.html",media_type="text/html")

@app.get("/health")
def health():
    if not DB:
        return JSONResponse({"status":"setup_required","message":"Database connection required"},status_code=503)
    with connect() as c:
        c.execute("SELECT 1").fetchone()
    return {"status":"ok","storage":"postgres","timeZone":"Asia/Kolkata"}

@app.post("/apiLogin")
async def login(request:Request):
    x=await request.json()
    sid=clean_id(x.get("staffId"))
    pin=clean_pin(x.get("pin"))
    with connect() as c:
        a=c.execute("SELECT failures,locked_until FROM attempts WHERE staff_id=%s FOR UPDATE",(sid,)).fetchone()
        if a and a["locked_until"] and a["locked_until"]>datetime.now(timezone.utc):
            raise HTTPException(429,"Too many login attempts. Try again after 15 minutes.")
        s=c.execute("SELECT * FROM staff WHERE id=%s",(sid,)).fetchone()
        valid=bool(s and s["active"] and hmac.compare_digest(pin_hash(pin,s["salt"]),s["pin_hash"]))
        if not valid:
            if a:
                failures=a["failures"]+1
                locked=datetime.now(timezone.utc)+timedelta(minutes=15) if failures>=5 else None
                c.execute("UPDATE attempts SET failures=%s,locked_until=%s,updated_at=NOW() WHERE staff_id=%s",(failures,locked,sid))
            else:
                c.execute("INSERT INTO attempts(staff_id,failures) VALUES(%s,1)",(sid,))
        else:
            c.execute("DELETE FROM attempts WHERE staff_id=%s",(sid,))
            token=secrets.token_urlsafe(48)
            digest=hashlib.sha256(token.encode()).hexdigest()
            c.execute("INSERT INTO sessions(token_hash,staff_id,expires_at) VALUES(%s,%s,%s)",
                      (digest,sid,datetime.now(timezone.utc)+timedelta(hours=12)))
    if not valid:
        raise HTTPException(401,"Incorrect Staff ID or PIN")
    response=JSONResponse({"user":{"id":s["id"],"name":s["name"],"role":s["role"]}})
    response.set_cookie(SESSION_COOKIE,token,max_age=43200,httponly=True,secure=True,samesite="strict",path="/")
    return response

@app.post("/apiLogout")
async def logout(request:Request):
    cookie=request.cookies.get(SESSION_COOKIE,"")
    if cookie:
        with connect() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=%s",(hashlib.sha256(cookie.encode()).hexdigest(),))
    response=JSONResponse({"ok":True})
    response.delete_cookie(SESSION_COOKIE,path="/",secure=True,samesite="strict")
    return response

@app.post("/apiSession")
async def session(request:Request):
    return {"user":user_for(request)}

def day_events(c,sid,day):
    a=c.execute("""SELECT action,happened_at FROM attendance WHERE staff_id=%s AND day=%s ORDER BY happened_at""",(sid,day)).fetchall()
    p=c.execute("SELECT plan,saved_at FROM work_plans WHERE staff_id=%s AND day=%s",(sid,day)).fetchone()
    sub=c.execute("SELECT submitted_at FROM submitted_days WHERE staff_id=%s AND day=%s",(sid,day)).fetchone()
    out=[{"action":x["action"],"time":iso(x["happened_at"])} for x in a]
    if p:out.append({"action":"PLAN","time":iso(p["saved_at"]),"plan":p["plan"]})
    if sub:out.append({"action":"SUBMITTED","time":iso(sub["submitted_at"])})
    return out

@app.post("/apiDay")
async def day(request:Request):
    u=user_for(request)
    d=today()
    with connect() as c:
        r=day_events(c,u["id"],d)
    return {"date":d.isoformat(),"records":r}

def parse_date(s):
    try:
        value=datetime.fromisoformat(str(s).replace("Z","+00:00"))
        if value.tzinfo is None:raise ValueError()
        delta=abs((datetime.now(timezone.utc)-value).total_seconds())
        if delta>600:raise ValueError()
        return value
    except Exception:
        raise HTTPException(400,"Selfie or location is older than 10 minutes. Capture again.")

def parse_geo(data):
    try:
        lat=float(data.get("latitude"));lon=float(data.get("longitude"));acc=float(data.get("accuracy"))
    except Exception:
        raise HTTPException(400,"Please capture accurate GPS location")
    if not (-90<=lat<=90 and -180<=lon<=180 and 0<=acc<=1000):
        raise HTTPException(400,"GPS location is invalid or accuracy exceeds 1000 metres")
    gps=parse_date(data.get("gpsAt"))
    photographed=parse_date(data.get("capturedAt"))
    return lat,lon,acc,gps,photographed

def stamp_photo(data,staff,action,place,lat,lon,acc):
    m=re.fullmatch(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)",str(data or ""))
    if not m or len(data)>3000000:
        raise HTTPException(400,"Take a fresh JPEG selfie under 2 MB")
    try:
        raw=base64.b64decode(m.group(1),validate=True)
        if len(raw)<1500 or len(raw)>2250000:
            raise ValueError()
        image=ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        image.load()
        if image.width<200 or image.height<200:
            raise ValueError()
        image=image.convert("RGB")
        image.thumbnail((1024,1024))
        # Overprint a server-side watermark. This is evidence, not independently verified GPS.
        w,h=image.size
        font_size=max(13,min(23,int(w/44)))
        try:
            font=ImageFont.truetype("DejaVuSans.ttf",font_size)
        except OSError:
            font=ImageFont.load_default()
        lines=[
            "EDII STAFF ATTENDANCE | "+("MORNING CHECK IN" if action=="IN" else "EVENING CHECK OUT"),
            staff["id"]+" | "+staff["name"][:40],
            "Server time IST: "+now_ist().strftime("%d/%m/%Y %I:%M:%S %p"),
            "Device GPS: %.6f, %.6f | Accuracy: %.0f m"%(lat,lon,acc),
            "Work location: "+place[:70],
        ]
        lh=font_size+6
        bar=min(h,lh*len(lines)+20)
        overlay=Image.new("RGBA",image.size,(0,0,0,0))
        d=ImageDraw.Draw(overlay)
        d.rectangle((0,h-bar,w,h),fill=(0,18,27,220))
        for i,line in enumerate(lines):
            d.text((12,h-bar+9+i*lh),line,fill="white",font=font,stroke_width=0)
        img=Image.alpha_composite(image.convert("RGBA"),overlay).convert("RGB")
        buf=io.BytesIO();img.save(buf,"JPEG",quality=70,optimize=True)
        return buf.getvalue()
    except (ValueError,UnidentifiedImageError,OSError,OverflowError):
        raise HTTPException(400,"Photograph could not be verified. Retake the live selfie.")

@app.post("/apiAttendance")
async def attendance(request:Request):
    u=user_for(request)
    r=await request.json()
    action=str(r.get("action","")).upper()
    if action not in ("IN","OUT"):
        raise HTTPException(400,"Invalid attendance action")
    if action=="OUT" and now_ist().hour<17:
        raise HTTPException(403,"Evening selfie and checkout are available only after 5:00 PM IST")
    location=str(r.get("workLocation") or "").strip()[:120]
    if not location:
        raise HTTPException(400,"Enter the work location")
    remarks=str(r.get("remarks") or "").strip()[:250]
    lat,lon,acc,gps,capture=parse_geo(r)
    photo=stamp_photo(r.get("photoData"),u,action,location,lat,lon,acc)
    date=today()
    with connect() as c:
        existing=c.execute("SELECT action FROM attendance WHERE staff_id=%s AND day=%s FOR UPDATE",(u["id"],date)).fetchall()
        actions={x["action"] for x in existing}
        if action in actions:
            raise HTTPException(409,"This selfie has already been submitted today")
        if action=="OUT":
            if "IN" not in actions:
                raise HTTPException(400,"Check in first")
            plan=c.execute("SELECT 1 FROM work_plans WHERE staff_id=%s AND day=%s",(u["id"],date)).fetchone()
            if not plan:
                raise HTTPException(400,"Save today's work plan first")
        photo_id=secrets.token_hex(18)
        c.execute("INSERT INTO photos(id,staff_id,image) VALUES(%s,%s,%s)",
                  (photo_id,u["id"],photo))
        c.execute("""INSERT INTO attendance(id,day,staff_id,action,location,remarks,
                  latitude,longitude,accuracy,captured_at,gps_at,photo_id)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                  (secrets.token_hex(18),date,u["id"],action,location,remarks,lat,lon,acc,capture,gps,photo_id))
    return {"ok":True,"date":date.isoformat()}

@app.post("/apiPlan")
async def plan(request:Request):
    u=user_for(request)
    r=await request.json()
    text=str(r.get("plan") or "").strip()
    if not 5<=len(text)<=2000:
        raise HTTPException(400,"Enter today's activities, at least five characters")
    with connect() as c:
        events={e["action"] for e in day_events(c,u["id"],today())}
        if "IN" not in events:
            raise HTTPException(400,"Morning check in is required before saving the plan")
        if "PLAN" in events:
            raise HTTPException(409,"Today's work plan is already saved")
        if "OUT" in events:
            raise HTTPException(400,"Work plan must be saved before checkout")
        c.execute("INSERT INTO work_plans(staff_id,day,plan) VALUES(%s,%s,%s)",(u["id"],today(),text))
    return {"ok":True}

@app.post("/apiSubmitDay")
async def submit_day(request:Request):
    u=user_for(request)
    with connect() as c:
        events={e["action"] for e in day_events(c,u["id"],today())}
        if not {"IN","PLAN","OUT"}.issubset(events):
            raise HTTPException(400,"Complete morning selfie, work plan and evening selfie first")
        if "SUBMITTED" in events:
            raise HTTPException(409,"Already submitted")
        c.execute("INSERT INTO submitted_days(staff_id,day) VALUES(%s,%s)",(u["id"],today()))
    return {"ok":True}

@app.post("/apiList")
async def all_records(request:Request):
    u=user_for(request)
    p=await request.json()
    frm=p.get("from") or "2000-01-01";to=p.get("to") or "2100-01-01"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(frm)) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",str(to)):
        raise HTTPException(400,"Invalid date filter")
    extra="" if u["role"]=="ADMIN" else " AND a.staff_id = %(who)s "
    args={"frm":frm,"to":to,"who":u["id"]}
    with connect() as c:
        attendance=c.execute("""SELECT a.day,a.staff_id,s.name,a.action,a.happened_at,
          a.location,a.remarks,a.latitude,a.longitude,a.accuracy,a.photo_id
          FROM attendance a JOIN staff s ON s.id=a.staff_id
          WHERE a.day BETWEEN %(frm)s AND %(to)s"""+extra+" ORDER BY a.happened_at DESC LIMIT 5000",args).fetchall()
        pextra="" if u["role"]=="ADMIN" else " AND p.staff_id = %(who)s "
        plans=c.execute("""SELECT p.day,p.staff_id,s.name,p.plan,p.saved_at
          FROM work_plans p JOIN staff s ON s.id=p.staff_id WHERE p.day BETWEEN %(frm)s AND %(to)s"""+pextra+" ORDER BY p.saved_at DESC LIMIT 5000",args).fetchall()
        submitted=c.execute("""SELECT sub.day,sub.staff_id,s.name,sub.submitted_at
          FROM submitted_days sub JOIN staff s ON s.id=sub.staff_id
          WHERE sub.day BETWEEN %(frm)s AND %(to)s"""+pextra.replace("p.staff_id","sub.staff_id")+" ORDER BY sub.submitted_at DESC LIMIT 5000",args).fetchall()
    rows=[]
    for x in attendance:
        rows.append({"date":str(x["day"]),"staffId":x["staff_id"],"staffName":x["name"],"action":x["action"],"time":iso(x["happened_at"]),"location":x["location"],"remarks":x["remarks"] or "","latitude":x["latitude"],"longitude":x["longitude"],"accuracy":x["accuracy"],"photoId":x["photo_id"],"mapUrl":"https://www.google.com/maps?q=%s,%s"%(x["latitude"],x["longitude"])})
    for x in plans:
        rows.append({"date":str(x["day"]),"staffId":x["staff_id"],"staffName":x["name"],"action":"PLAN","time":iso(x["saved_at"]),"plan":x["plan"]})
    for x in submitted:
        rows.append({"date":str(x["day"]),"staffId":x["staff_id"],"staffName":x["name"],"action":"SUBMITTED","time":iso(x["submitted_at"])})
    rows.sort(key=lambda x:x["time"],reverse=True)
    return rows[:5000]

@app.post("/apiPhoto")
async def get_photo(request:Request):
    u=user_for(request)
    p=await request.json()
    photo_id=str(p.get("fileId") or "")
    if not re.fullmatch("[a-f0-9]{36}",photo_id):
        raise HTTPException(400,"Invalid photograph ID")
    with connect() as c:
        x=c.execute("SELECT staff_id,image FROM photos WHERE id=%s",(photo_id,)).fetchone()
    if not x or (u["role"]!="ADMIN" and x["staff_id"]!=u["id"]):
        raise HTTPException(403,"Photograph not available")
    return {"dataUrl":"data:image/jpeg;base64,"+base64.b64encode(x["image"]).decode()}

@app.post("/apiStaffList")
async def staff_list(request:Request):
    u=user_for(request);only_admin(u)
    with connect() as c:
        r=c.execute("SELECT id,name,role,active FROM staff ORDER BY id").fetchall()
    return r

@app.post("/apiStaffSave")
async def save_staff(request:Request):
    u=user_for(request);only_admin(u)
    x=await request.json()
    sid=clean_id(x.get("staffId"))
    name=str(x.get("name") or "").strip()
    if not 2<=len(name)<=80:
        raise HTTPException(400,"Enter the employee's name")
    role=str(x.get("role") or "STAFF").upper()
    if role not in ("STAFF","ADMIN"):
        raise HTTPException(400,"Invalid role")
    newpin=str(x.get("pin") or "")
    if newpin:clean_pin(newpin)
    if sid==u["id"] and role!="ADMIN":
        raise HTTPException(400,"Cannot remove your own admin role")
    with connect() as c:
        exists=c.execute("SELECT id FROM staff WHERE id=%s FOR UPDATE",(sid,)).fetchone()
        if not exists and not newpin:
            raise HTTPException(400,"Set a six digit PIN for the new employee")
        if newpin:
            salt=secrets.token_hex(18);digest=pin_hash(newpin,salt)
        if exists:
            if newpin:
                c.execute("UPDATE staff SET name=%s,role=%s,active=TRUE,salt=%s,pin_hash=%s,updated_at=NOW(),updated_by=%s WHERE id=%s",
                          (name,role,salt,digest,u["id"],sid))
                c.execute("DELETE FROM sessions WHERE staff_id=%s",(sid,))
            else:
                c.execute("UPDATE staff SET name=%s,role=%s,active=TRUE,updated_at=NOW(),updated_by=%s WHERE id=%s",
                          (name,role,u["id"],sid))
        else:
            c.execute("INSERT INTO staff(id,name,role,salt,pin_hash,updated_by) VALUES(%s,%s,%s,%s,%s,%s)",
                      (sid,name,role,salt,digest,u["id"]))
        add_audit(c,u["id"],"UPDATE_STAFF" if exists else "ADD_STAFF",sid,"Role "+role)
    return {"ok":True}

@app.post("/apiStaffDeactivate")
async def deactivate(request:Request):
    u=user_for(request);only_admin(u)
    x=await request.json()
    sid=clean_id(x.get("staffId"))
    if sid==u["id"]:
        raise HTTPException(400,"Cannot deactivate your own account")
    with connect() as c:
        row=c.execute("SELECT id FROM staff WHERE id=%s",(sid,)).fetchone()
        if not row:raise HTTPException(404,"Employee not found")
        c.execute("UPDATE staff SET active=FALSE,updated_by=%s,updated_at=NOW() WHERE id=%s",(u["id"],sid))
        c.execute("DELETE FROM sessions WHERE staff_id=%s",(sid,))
        add_audit(c,u["id"],"DEACTIVATE_STAFF",sid,"Previous attendance retained")
    return {"ok":True}

@app.post("/apiChangePin")
async def change_pin(request:Request):
    u=user_for(request)
    x=await request.json()
    old=clean_pin(x.get("oldPin"));new=clean_pin(x.get("newPin"))
    if old==new:
        raise HTTPException(400,"Choose a different PIN")
    with connect() as c:
        row=c.execute("SELECT salt,pin_hash FROM staff WHERE id=%s FOR UPDATE",(u["id"],)).fetchone()
        if not hmac.compare_digest(pin_hash(old,row["salt"]),row["pin_hash"]):
            raise HTTPException(401,"Current PIN is incorrect")
        salt=secrets.token_hex(18)
        c.execute("UPDATE staff SET salt=%s,pin_hash=%s,updated_at=NOW() WHERE id=%s",(salt,pin_hash(new,salt),u["id"]))
        add_audit(c,u["id"],"CHANGE_PIN",u["id"])
    return {"ok":True}
