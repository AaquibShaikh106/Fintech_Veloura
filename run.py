from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json, sqlite3, threading, time, datetime, random, os

ROOT=Path(__file__).parent
DB=ROOT/'trustmint.db'
events=[]
lock=threading.RLock()

def now(): return datetime.datetime.now().astimezone().isoformat(timespec='seconds')
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,name TEXT,city TEXT,language TEXT,loan REAL,due REAL,dpd INTEGER,missed INTEGER,income_ratio REAL,agent TEXT,consent INTEGER,status TEXT,phone TEXT,lat REAL,lon REAL,updated TEXT);
 CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,kind TEXT,channel TEXT,note TEXT,actor TEXT,created TEXT,consent TEXT,lat REAL,lon REAL);
 CREATE TABLE IF NOT EXISTS promises(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,amount REAL,due_date TEXT,state TEXT);
 CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,kind TEXT,note TEXT,state TEXT,created TEXT);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT,action TEXT,case_id TEXT,detail TEXT,created TEXT);''')
 if c.execute('select count(*) from cases').fetchone()[0]==0:
  rng=random.Random(52); names=['Aarav Mehta','Sana Khan','Ishita Shah','Rohan Patil','Meera Joshi','Kabir Desai','Anaya Kulkarni','Vivaan Rao','Tara Iyer','Neil Kapoor','Farah Shaikh','Om Pawar','Diya Nair','Rehan Merchant','Mira Bhosale','Arjun Naik']; agents=['Aditi','Sameer','Neha','Kunal','Riya','Irfan','Dev','Priya']; langs=['English','हिंदी','मराठी']; cities=['Mumbai','Thane','Navi Mumbai','Pune'];
  for i in range(1,61):
   loan=rng.randrange(45000,450000,5000); dpd=rng.choice([3,7,12,18,25,36,48,63,78]); missed=max(1,dpd//30+ rng.choice([0,1,1])); due=round(loan*(rng.uniform(.055,.3)),2); agent=agents[(i-1)%8] if dpd>30 else ''; city=cities[(i-1)%4]; lat=19.076+rng.uniform(-.11,.11); lon=72.877+rng.uniform(-.12,.12)
   c.execute('insert into cases values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(f'TM-{i:04}',names[(i-1)%len(names)],city,langs[i%3],loan,due,dpd,missed,rng.uniform(.2,.58),agent,1 if i%17 else 0,'open',f'+91 •••• {rng.randrange(1000,9999)}',lat,lon,now()))
   if i%5==0: c.execute('insert into logs(case_id,kind,channel,note,actor,created,consent) values(?,?,?,?,?,?,?)',(f'TM-{i:04}','Reminder','WhatsApp','Polite payment options shared','System',now(),'consented'))
  c.commit()
 c.close()

def score(x):
 factors=[('Days past due',min(42,x['dpd']*.65)),('Missed instalments',min(28,x['missed']*8)),('Payment burden',max(0,(x['income_ratio']-.2)*65)),('Outstanding balance',min(12,x['due']/30000))]
 val=min(98,int(sum(v for _,v in factors))); band='High' if val>=65 else 'Watch' if val>=38 else 'Low'; action='Field visit' if band=='High' else 'Offer repayment plan' if band=='Watch' else 'Digital reminder';
 return {'score':val,'band':band,'action':action,'factors':[{'name':n,'value':round(v,1)} for n,v in sorted(factors,key=lambda f:f[1],reverse=True)[:3]]}

def audit(c,actor,action,cid,detail=''):
 c.execute('insert into audit(actor,action,case_id,detail,created) values(?,?,?,?,?)',(actor,action,cid,detail,now()))
 events.append({'time':time.time(),'type':'update','case':cid,'action':action})

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw): super().__init__(*a,directory=str(ROOT/'web'),**kw)
 def send_json(self,obj,status=200):
  data=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers(); self.wfile.write(data)
 def do_OPTIONS(self):
  self.send_response(204); self.send_header('Access-Control-Allow-Origin','*'); self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS'); self.send_header('Access-Control-Allow-Headers','Content-Type'); self.send_header('Access-Control-Max-Age','600'); self.end_headers()
 def body(self): return json.loads(self.rfile.read(int(self.headers.get('Content-Length',0)) or 0) or b'{}')
 def do_GET(self):
  path=urlparse(self.path); q=parse_qs(path.query); c=db()
  if path.path=='/api/cases':
   role=q.get('role',['manager'])[0]; cid=q.get('case',['TM-0001'])[0]
   rows=[dict(x) for x in c.execute('select * from cases order by dpd desc')]; out=[]
   for x in rows:
    x.update(score(x)); x['timeline']=[dict(z) for z in c.execute('select * from logs where case_id=? order by id desc',(x['id'],))]; x['promise']=(dict(c.execute('select * from promises where case_id=? order by id desc limit 1',(x['id'],)).fetchone()) if c.execute('select count(*) from promises where case_id=?',(x['id'],)).fetchone()[0] else None); out.append(x)
   c.close(); self.send_json({'cases':out,'role':role,'selected':cid})
  elif path.path=='/api/audit':
   rows=[dict(x) for x in c.execute('select * from audit order by id desc limit 30')]; c.close(); self.send_json(rows)
  elif path.path=='/api/stream':
   self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.send_header('Cache-Control','no-cache'); self.send_header('Connection','keep-alive'); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers(); seen=time.time(); end=seen+22
   try:
    while time.time()<end:
     newer=[e for e in events if e['time']>seen]
     if newer:
      seen=max(e['time'] for e in newer); self.wfile.write(('data: '+json.dumps(newer[-1])+'\n\n').encode()); self.wfile.flush()
     else: self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
     time.sleep(2)
   except (BrokenPipeError,ConnectionResetError): pass
  else: super().do_GET()
 def do_POST(self):
  p=urlparse(self.path).path; b=self.body(); c=db(); cid=b.get('case_id','TM-0001'); actor=b.get('actor','Manager'); row=c.execute('select * from cases where id=?',(cid,)).fetchone()
  if not row: c.close(); return self.send_json({'error':'Case not found'},404)
  x=dict(row); status=200
  if p=='/api/pay':
   amount=min(float(b.get('amount',x['due'])),x['due']); c.execute('update cases set due=max(0,due-?),status=case when due-?<=0 then ? else status end,updated=? where id=?',(amount,amount,'paid',now(),cid)); c.execute('insert into logs(case_id,kind,channel,note,actor,created,consent) values(?,?,?,?,?,?,?)',(cid,'Payment','Demo payment','Simulated payment confirmed · receipt TM-RCPT-'+cid[-4:],actor,now(),'consented')); audit(c,actor,'Payment confirmed',cid,f'₹{amount:,.0f}'); result={'success':True,'amount':amount,'receipt':'TM-RCPT-'+cid[-4:]}
  elif p=='/api/action':
   kind=b.get('kind','Visit'); channel=b.get('channel','Field'); stamp=now(); note=b.get('note','Follow-up recorded')
   if kind=='Reminder':
    cutoff=(datetime.datetime.now().astimezone()-datetime.timedelta(days=7)).isoformat(timespec='seconds')
    count=c.execute("select count(*) from logs where case_id=? and kind='Reminder' and created>?",(cid,cutoff)).fetchone()[0]
    last=c.execute("select created from logs where case_id=? and channel=? order by id desc limit 1",(cid,channel)).fetchone()
    hour=datetime.datetime.now().hour
    if not x['consent']: c.close(); return self.send_json({'success':False,'reason':'Contact blocked: borrower has opted out.'},409)
    if count>=3: c.close(); return self.send_json({'success':False,'reason':'Contact blocked: weekly contact limit reached.'},409)
    if hour<8 or hour>=19: c.close(); return self.send_json({'success':False,'reason':'Contact blocked: quiet hours are 8:00 am–7:00 pm.'},409)
    if last and (datetime.datetime.now().astimezone()-datetime.datetime.fromisoformat(last['created'])).total_seconds()<86400: c.close(); return self.send_json({'success':False,'reason':'Duplicate blocked: same channel was used within 24 hours.'},409)
   c.execute('insert into logs(case_id,kind,channel,note,actor,created,consent,lat,lon) values(?,?,?,?,?,?,?,?,?)',(cid,kind,channel,note,actor,stamp,'consented' if x['consent'] else 'do not contact',b.get('lat'),b.get('lon')))
   if kind=='Visit': note+=' · GPS '+str(b.get('lat','19.0760'))+', '+str(b.get('lon','72.8777'))
   audit(c,actor,kind,cid,note); result={'success':True,'message':kind+' saved to shared case record.'}
  elif p=='/api/assign':
   agent=b.get('agent','Aditi'); c.execute('update cases set agent=?,updated=? where id=?',(agent,now(),cid)); audit(c,actor,'Case assigned',cid,'Assigned to '+agent); result={'success':True,'message':'Assigned to '+agent}
  elif p=='/api/promise':
   c.execute('insert into promises(case_id,amount,due_date,state) values(?,?,?,?)',(cid,float(b.get('amount',x['due'])),b.get('date','2026-11-11'),'active')); c.execute('insert into logs(case_id,kind,channel,note,actor,created,consent) values(?,?,?,?,?,?,?)',(cid,'Promise to pay','Agent app','₹'+str(b.get('amount',x['due']))+' by '+b.get('date','2026-11-11'),actor,now(),'consented')); audit(c,actor,'Promise recorded',cid,b.get('date','')); result={'success':True,'message':'Promise-to-pay added.'}
  elif p=='/api/request':
   c.execute('insert into requests(case_id,kind,note,state,created) values(?,?,?,?,?)',(cid,b.get('kind','Repayment help'),b.get('note','Please contact me'), 'pending',now())); audit(c,actor,'Support requested',cid,b.get('kind','')); result={'success':True,'message':'Your request has been shared with the support team.'}
  else: c.close(); return self.send_json({'error':'Unknown action'},404)
  c.commit(); c.close(); self.send_json(result,status)
 def log_message(self,*a): pass

if __name__=='__main__':
 init()
 host=os.environ.get('TRUSTMINT_HOST','127.0.0.1')
 port=int(os.environ.get('PORT','8000'))
 server=ThreadingHTTPServer((host,port),Handler)
 print(f'TRUSTMINT is ready at http://{host}:{port} · synthetic data only · press Ctrl+C to stop',flush=True)
 server.serve_forever()
