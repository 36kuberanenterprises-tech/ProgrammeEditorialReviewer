"""Admin-only full ZIP export. Includes all historical staff records and retained selfies."""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone


def csv_data(rows,headers):
    out=io.StringIO(newline="")
    writer=csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h) if row.get(h) is not None else "" for h in headers])
    return ("\ufeff"+out.getvalue()).encode("utf-8")


def zip_backup(conn):
    output=io.BytesIO()
    staff=conn.execute("""SELECT id,name,role,active,created_at,updated_at,updated_by
                      FROM staff ORDER BY id""").fetchall()
    attendance=conn.execute("""SELECT a.id,a.day,a.staff_id,s.name AS staff_name,a.action,
                         a.happened_at,a.location,a.remarks,a.latitude,a.longitude,a.accuracy,
                         a.captured_at,a.gps_at,a.photo_id
                         FROM attendance a JOIN staff s ON s.id=a.staff_id
                         ORDER BY a.day,a.staff_id,a.action""").fetchall()
    plans=conn.execute("""SELECT p.staff_id,s.name AS staff_name,p.day,p.plan,p.saved_at
                       FROM work_plans p JOIN staff s ON s.id=p.staff_id
                       ORDER BY p.day,p.staff_id""").fetchall()
    submitted=conn.execute("""SELECT staff_id,day,submitted_at FROM submitted_days
                           ORDER BY day,staff_id""").fetchall()
    audit=conn.execute("""SELECT happened_at,actor,action,target,details
                       FROM audit ORDER BY happened_at""").fetchall()
    photos=conn.execute("""SELECT p.id,p.staff_id,p.image
                        FROM photos p ORDER BY p.created_at""").fetchall()
    with zipfile.ZipFile(output,mode="w",compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as archive:
        archive.writestr("README.txt",
            "EDII Staff Attendance confidential archive\n"
            "Includes attendance, work plans, all retained selfie photographs and account metadata.\n"
            "Passwords, PIN hashes and session tokens are deliberately excluded.\n"
            "Keep this ZIP private. Upload a copy to an administrator-only Google Drive folder.\n"
            "This is a manual backup and does not mean automatic Google synchronisation is active.\n"
            "Do not delete historical data unless an authorised administrator instructs it.\n")
        archive.writestr("employee_master.csv",csv_data(staff,
          ["id","name","role","active","created_at","updated_at","updated_by"]))
        archive.writestr("attendance.csv",csv_data(attendance,
          ["id","day","staff_id","staff_name","action","happened_at","location",
           "remarks","latitude","longitude","accuracy","captured_at","gps_at","photo_id"]))
        archive.writestr("work_plans.csv",csv_data(plans,
          ["staff_id","staff_name","day","plan","saved_at"]))
        archive.writestr("submitted_days.csv",csv_data(submitted,
          ["staff_id","day","submitted_at"]))
        archive.writestr("admin_audit.csv",csv_data(audit,
          ["happened_at","actor","action","target","details"]))
        for photo in photos:
            archive.writestr("selfies/"+photo["staff_id"]+"/"+photo["id"]+".jpg",bytes(photo["image"]))
        archive.writestr("summary.json",json.dumps({
          "exported_at_utc":datetime.now(timezone.utc).isoformat(),
          "employees":len(staff),"attendance_events":len(attendance),
          "work_plans":len(plans),"completed_days":len(submitted),
          "selfie_photos":len(photos),
          "contains_credentials":False
        },indent=2))
    output.seek(0)
    return output.read()
