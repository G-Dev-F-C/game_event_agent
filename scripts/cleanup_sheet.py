import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(override=True)
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from tools.validator import _is_domestic

sa=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
sid=os.getenv('SHEET_ID')
tab=os.getenv('SHEET_TAB','events')
creds=Credentials.from_service_account_file(sa, scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/calendar'])
svc=build('sheets','v4',credentials=creds, cache_discovery=False)
calsvc=build('calendar','v3',credentials=Credentials.from_service_account_file(sa, scopes=['https://www.googleapis.com/auth/calendar']), cache_discovery=False)
cid=os.getenv('CALENDAR_ID','primary')
# ensure calendar list
try:
    calsvc.calendarList().get(calendarId=cid).execute()
except:
    try:
        calsvc.calendarList().insert(body={'id':cid}).execute()
        print(f"Calendar {cid} inserted to list")
    except Exception as e:
        print("calendar insert fail", e)
        cid='primary'

# read all rows
rng=f"'{tab}'!A1:M"
data=svc.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute()
rows=data.get('values',[])
if not rows:
    print("no rows")
    exit(0)
header=rows[0]
print("header", header)
# header indices
cols={h:i for i,h in enumerate(header)}
events=[]
for idx, r in enumerate(rows[1:], start=2):
    # pad
    r = r + ['']*(len(header)-len(r))
    ev={
        'row': idx,
        'id': r[cols['id']] if 'id' in cols else '',
        'title': r[cols['title']] if 'title' in cols else '',
        'category': r[cols['category']] if 'category' in cols else '',
        'start_date': r[cols['start_date']] if 'start_date' in cols else '',
        'end_date': r[cols['end_date']] if 'end_date' in cols else '',
        'deadline': r[cols['deadline']] if 'deadline' in cols else '',
        'location': r[cols['location']] if 'location' in cols else '',
        'url': r[cols['url']] if 'url' in cols else '',
        'source': r[cols['source']] if 'source' in cols else '',
        'status': r[cols['status']] if 'status' in cols else '',
        'raw': r,
    }
    events.append(ev)

print(f"total data rows {len(events)}")

def is_overseas_offline(ev):
    loc=(ev['location'] or '').strip()
    if "온라인" in loc:
        return False
    if not loc:
        return False
    # use same logic as validator
    is_dom=_is_domestic({'location':ev['location'], 'source':ev['source'], 'title':ev['title']})
    return loc.startswith("오프라인") and not is_dom

to_keep=[]
to_remove=[]
for ev in events:
    if is_overseas_offline(ev):
        to_remove.append(ev)
    else:
        to_keep.append(ev)

print(f"keep {len(to_keep)}, remove {len(to_remove)} (해외 오프라인)")
for ev in to_remove[:10]:
    print(f"  REMOVE row{ev['row']}: {ev['title']} | {ev['location']} | {ev['source']}")
for ev in to_keep[:5]:
    print(f"  KEEP row{ev['row']}: {ev['title']} | {ev['location']}")

# Build new rows (header + keep)
new_values=[header] + [ev['raw'] for ev in to_keep]

# Clear and rewrite
if to_remove:
    print(f"Rewriting sheet {tab} with {len(new_values)} rows (was {len(rows)})...")
    svc.spreadsheets().values().clear(spreadsheetId=sid, range=f"'{tab}'!A1:M").execute()
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"'{tab}'!A1", valueInputOption="RAW", body={"values": new_values}).execute()
    print("Sheet rewritten")
else:
    print("No overseas offline to remove, sheet unchanged")

# Calendar cleanup: delete events that correspond to removed rows
# Need to map via eventId hash
import hashlib
def eid(title, start_date, url):
    raw=f"{(title or '').strip().lower()}|{(start_date or '').strip()}|{(url or '').strip().lower()}"
    return "evt"+hashlib.sha1(raw.encode()).hexdigest()[:20]

# Also handle both primary and group calendars? We will clean both if needed, but focus on cid (group)
for cal_id in [cid, 'primary']:
    print(f"\nCalendar cleanup for {cal_id}...")
    for ev in to_remove:
        event_id=eid(ev['title'], ev['start_date'], ev['url'])
        try:
            calsvc.events().get(calendarId=cal_id, eventId=event_id).execute()
            calsvc.events().delete(calendarId=cal_id, eventId=event_id).execute()
            print(f"  deleted {ev['title']} ({event_id}) from {cal_id}")
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e):
                pass
            else:
                print(f"  delete fail {ev['title']}: {e}")

print("\nDone")
