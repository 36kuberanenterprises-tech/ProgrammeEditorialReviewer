/**
 * EDII Staff Attendance archive.
 * Deploy as a Google Apps Script Web App using the Google account that owns the workbook.
 * Execute as: Me. Access: Anyone (server-to-server only, authenticated with the token).
 * The secret must be entered in Project Settings > Script Properties as EDII_ARCHIVE_TOKEN.
 * Never share the secret or deploy the archive as a browser-facing employee application.
 * No record is deleted by this script.
 */
const EDII_SHEET_ID = '1QYp9HrV40gciL8QpKeNb3U1Xdk0KDNOJXdnFVQPH9xE';
const EDII_PHOTO_FOLDER_ID = '1TqqfMIMWxQDUT0ei7wuA63smeGH_0KDU';

function doGet() {
  return response_({ok:true, service:'EDII archive bridge', method:'POST only'});
}
function response_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
     .setMimeType(ContentService.MimeType.JSON);
}
function doPost(e) {
  let lock = null;
  try {
    const raw = e && e.postData ? e.postData.contents : '';
    if (!raw || raw.length > 10000000) throw Error('Invalid upload size');
    const request = JSON.parse(raw);
    const requiredSecret = PropertiesService.getScriptProperties().getProperty('EDII_ARCHIVE_TOKEN');
    if (!requiredSecret || requiredSecret.length < 32 || String(request.token || '') !== requiredSecret) {
      throw Error('Archive authentication failed');
    }
    const evt = request.event;
    if (!evt || typeof evt !== 'object') throw Error('Event missing');
    if (evt.kind === 'ping') return response_({ok:true,archived:false,kind:'ping'});
    const kinds = ['staff','attendance','plan','submitted','audit'];
    if (!kinds.includes(evt.kind)) throw Error('Unknown event type');
    if (!/^[a-zA-Z0-9_:|.-]{3,160}$/.test(String(evt.id||''))) throw Error('Invalid archive ID');

    lock = LockService.getScriptLock();
    lock.waitLock(25000);
    const book = SpreadsheetApp.openById(EDII_SHEET_ID);
    let result;
    if (evt.kind === 'staff') result = archiveStaff_(book,evt);
    if (evt.kind === 'attendance') result = archiveAttendance_(book,evt);
    if (evt.kind === 'plan') result = archivePlan_(book,evt);
    if (evt.kind === 'submitted') result = archiveSubmission_(book,evt);
    if (evt.kind === 'audit') result = archiveAudit_(book,evt);
    SpreadsheetApp.flush();
    return response_({ok:true,id:evt.id,kind:evt.kind,result});
  } catch (err) {
    return response_({ok:false,error:String(err.message || err).slice(0,250)});
  } finally {
    if (lock) try {lock.releaseLock();}catch(e){}
  }
}
function sheet_(book,name) {
  const sh = book.getSheetByName(name);
  if (!sh) throw Error('Missing sheet: '+name);
  return sh;
}
function rowBy_(sh,col,key) {
  const end=sh.getLastRow();
  if(end<2) return -1;
  const arr=sh.getRange(2,col,end-1,1).getDisplayValues();
  for(let i=0;i<arr.length;i++){
    if(String(arr[i][0])===String(key)) return i+2;
  }
  return -1;
}
function clean_(v,len) {
  return String(v===null||v===undefined?'':v).slice(0,len||500);
}
function safeCell_(v,len) {
  const t=clean_(v,len);
  // Do not interpret field-entered user text as a spreadsheet formula.
  return /^[=+\-@\t\r]/.test(t)?("'"+t):t;
}
function iso_(v) {
  const s=clean_(v,40);
  if (!s || isNaN(new Date(s).getTime())) throw Error('Invalid timestamp');
  return s;
}
function archiveStaff_(book,e) {
  const p=e.data||{};
  const id=clean_(p.staffId,30).toUpperCase();
  if(!/^[A-Z0-9_]{3,30}$/.test(id)) throw Error('Staff ID invalid');
  const sh=sheet_(book,'Employee Master');
  const row=rowBy_(sh,1,id);
  const old=row>0?sh.getRange(row,1,1,9).getValues()[0]:[];
  const newData=[
    id,safeCell_(p.name,80),clean_(old[2],150),p.role==='ADMIN'?'ADMIN':'STAFF',
    p.active===false?'Inactive':'Active',
    old[5]||clean_(p.createdAt,45)||new Date().toISOString(),
    clean_(p.updatedAt,45)||new Date().toISOString(),
    clean_(old[7],120),
    clean_(old[8],250)
  ];
  if(row>0){sh.getRange(row,1,1,9).setValues([newData]);return 'updated';}
  sh.appendRow(newData);return 'created';
}
function archiveAttendance_(book,e) {
  const p=e.data||{};
  const sh=sheet_(book,'Attendance');
  const recId=clean_(p.recordId,100);
  if(!recId || !p.photoBase64) throw Error('Attendance ID or photograph missing');
  if(rowBy_(sh,16,recId)>0) return 'duplicate ignored';
  const lat=Number(p.latitude),lon=Number(p.longitude),accuracy=Number(p.accuracy);
  if(!isFinite(lat)||!isFinite(lon)||!isFinite(accuracy))throw Error('Invalid GPS');
  const action=p.action==='OUT'?'OUT':p.action==='IN'?'IN':null;
  if(!action)throw Error('Invalid action');
  const image=String(p.photoBase64);
  if(image.length<1000||image.length>4000000||!/^[A-Za-z0-9+/=]+$/.test(image))throw Error('Invalid photo');
  const blob=Utilities.newBlob(
     Utilities.base64Decode(image),'image/jpeg',
     [clean_(p.date,10),clean_(p.staffId,30),action,recId].join('_')+'.jpg'
  );
  // The folder and images stay private to the Google account unless the owner shares them.
  const photo=DriveApp.getFolderById(EDII_PHOTO_FOLDER_ID).createFile(blob);
  const map='https://www.google.com/maps?q='+lat+','+lon;
  sh.appendRow([
    clean_(p.date,10),clean_(p.staffId,30),safeCell_(p.staffName,80),action,
    iso_(p.time),safeCell_(p.location,120),safeCell_(p.remarks,250),
    lat,lon,accuracy,photo.getUrl(),photo.getId(),iso_(p.capturedAt),
    iso_(p.gpsAt),map,recId
  ]);
  return 'archived';
}
function archivePlan_(book,e) {
  const p=e.data||{};
  const sh=sheet_(book,'Work Plans');
  const day=clean_(p.date,10),id=clean_(p.staffId,30),key=day+'|'+id;
  const rows=sh.getLastRow()<2?[]:sh.getRange(2,1,sh.getLastRow()-1,2).getDisplayValues();
  for(let i=0;i<rows.length;i++){
    if(rows[i][0]+'|'+rows[i][1]===key)return 'existing plan retained';
  }
  sh.appendRow([day,id,safeCell_(p.staffName,80),'PLAN',iso_(p.time),safeCell_(p.plan,2000)]);
  return 'archived';
}
function archiveSubmission_(book,e) {
  const p=e.data||{};
  const sh=sheet_(book,'Day Submissions');
  const day=clean_(p.date,10),id=clean_(p.staffId,30);
  const rows=sh.getLastRow()<2?[]:sh.getRange(2,1,sh.getLastRow()-1,2).getDisplayValues();
  for(let i=0;i<rows.length;i++){
    if(rows[i][0]===day&&rows[i][1]===id)return 'duplicate ignored';
  }
  sh.appendRow([day,id,safeCell_(p.staffName,80),iso_(p.time),clean_(e.id,100)]);
  return 'archived';
}
function archiveAudit_(book,e) {
  const p=e.data||{};
  const sh=sheet_(book,'Admin Audit');
  const id=clean_(e.id,100);
  const rows=sh.getLastRow()<2?[]:sh.getRange(2,5,sh.getLastRow()-1,1).getDisplayValues();
  for(let i=0;i<rows.length;i++)if(rows[i][0].includes('[event '+id+']'))return 'duplicate ignored';
  sh.appendRow([iso_(p.time),clean_(p.actor,30),safeCell_(p.action,70),
    clean_(p.target,30),'[event '+id+'] '+safeCell_(p.details,150)]);
  return 'archived';
}

/** Run only once from the Apps Script editor to prepare a private archive token. */
function prepareEDIIArchive() {
  const props=PropertiesService.getScriptProperties();
  let token=props.getProperty('EDII_ARCHIVE_TOKEN');
  if(!token){
    token=Utilities.getUuid().replace(/-/g,'')+Utilities.getUuid().replace(/-/g,'');
    props.setProperty('EDII_ARCHIVE_TOKEN',token);
  }
  SpreadsheetApp.openById(EDII_SHEET_ID);
  DriveApp.getFolderById(EDII_PHOTO_FOLDER_ID);
  Logger.log('Authorisation completed. Copy EDII_ARCHIVE_TOKEN from Project Settings > Script Properties into Render environment variables; do not send it in chat or share it with employees.');
}
