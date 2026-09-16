import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import hashlib, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
SEOUL=ZoneInfo("Asia/Seoul")

sa=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
sid=os.getenv('SHEET_ID')
tab=os.getenv('SHEET_TAB','events')
cid=os.getenv('CALENDAR_ID')

creds_sheet=Credentials.from_service_account_file(sa, scopes=['https://www.googleapis.com/auth/spreadsheets'])
svc=build('sheets','v4',credentials=creds_sheet, cache_discovery=False)
creds_cal=Credentials.from_service_account_file(sa, scopes=['https://www.googleapis.com/auth/calendar'])
cal=build('calendar','v3',credentials=creds_cal, cache_discovery=False)
# ensure calendar list
try:
    cal.calendarList().get(calendarId=cid).execute()
except:
    cal.calendarList().insert(body={'id':cid}).execute()
    print(f"inserted {cid} to list")

# read sheet
rng=f"'{tab}'!A1:M"
data=svc.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute()
rows=data.get('values',[])
header=rows[0]
cols={h:i for i,h in enumerate(header)}
events=[]
for r in rows[1:]:
    r=r+['']*(len(header)-len(r))
    events.append({
        'id': r[cols['id']],
        'title': r[cols['title']],
        'category': r[cols['category']],
        'start_date': r[cols['start_date']],
        'end_date': r[cols['end_date']],
        'deadline': r[cols['deadline']],
        'location': r[cols['location']],
        'url': r[cols['url']],
        'source': r[cols['source']],
        'status': r[cols['status']],
    })
print(f"Sheet {tab} has {len(events)} events")

def eid(title, start_date, url):
    raw=f"{(title or '').strip().lower()}|{(start_date or '').strip()}|{(url or '').strip().lower()}"
    return "evt"+hashlib.sha1(raw.encode()).hexdigest()[:20]

def parse_date(s):
    if not s: return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except: return None

def build_event(ev):
    from datetime import timedelta
    start=parse_date(ev.get('start_date')) or parse_date(ev.get('deadline')) or datetime.now(SEOUL).date()
    end=parse_date(ev.get('end_date')) or (start+timedelta(days=1))
    end_ex=end+timedelta(days=1)
    desc=[]
    if ev.get('source'): desc.append(f"출처: {ev['source']}")
    if ev.get('category'): desc.append(f"카테고리: {ev['category']}")
    if ev.get('deadline'): desc.append(f"마감: {ev['deadline']}")
    if ev.get('url'): desc.append(f"링크: {ev['url']}")
    return {
        'summary': f"[{ev.get('category','event')}] {ev['title']}",
        'location': ev.get('location',''),
        'description': "\n".join(desc),
        'start': {'date': start.isoformat()},
        'end': {'date': end_ex.isoformat()},
        'transparency': 'transparent',
    }

# sync to group calendar
inserted=0
skipped=0
for ev in events:
    event_id=eid(ev['title'], ev['start_date'], ev['url'])
    try:
        cal.events().get(calendarId=cid, eventId=event_id).execute()
        skipped+=1
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e):
            body=build_event(ev)
            body['id']=event_id
            try:
                cal.events().insert(calendarId=cid, body=body).execute()
                print(f"inserted {ev['title']} -> {event_id}")
                inserted+=1
                time.sleep(0.3)
            except Exception as ie:
                print(f"insert fail {ev['title']}: {ie}")
        else:
            print(f"get fail {ev['title']}: {e}")

print(f"Sync done: inserted {inserted}, skipped {skipped} for {cid}")

# also verify primary? keep primary as is or sync similarly
# list primary and compare
