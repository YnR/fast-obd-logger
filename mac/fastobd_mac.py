#!/usr/bin/env python3
"""Fast OBD bridge for macOS (parked use only).

Talks to an ELM327/STN adapter (OBDLink MX+) over its Bluetooth serial port and lets Claude guide the
exploration through a shared folder:
  bridge/cmd/*.json   commands dropped by Claude          bridge/out/*.json   results
  bridge/data/*.jsonl recorded samples                    bridge/done/        processed commands
A small local page (http://localhost:8765) shows the status and the instructions for the person in the car.

Safety: only read requests are ever sent to the car (OBD services 01 02 03 07 09 0A, UDS 19 and 22) and a
short list of adapter setup commands. Nothing that writes, clears codes, changes sessions or runs actuators.
Python standard library only.
"""
import argparse, glob, json, os, re, select, sys, termios, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OBD_OK = re.compile(r'^(01|02|03|07|09|0A|19|22)([0-9A-F]{2})*$')
AT_OK = re.compile(r'^(ATZ|ATI|ATRV|ATDP|ATDPN|ATE0|ATL0|ATS0|ATH[01]|ATAT[012]|ATST[0-9A-F]{2}|ATSP[0-9A-F]|ATSH[0-9A-F]{3}|ATCRA([0-9A-F]{3})?|ATAR|ATCAF[01]|STI|STDI)$')
NRC = {'10': 'general reject', '11': 'service not supported', '12': 'sub-function not supported', '13': 'bad message length',
       '14': 'response too long', '22': 'conditions not correct', '31': 'request out of range', '33': 'security access denied',
       '78': 'response pending', '7E': 'not supported in this session', '7F': 'service not supported in this session'}


def clean(cmd):
    return re.sub(r'\s+', '', str(cmd)).upper()


def allowed(cmd):
    c = clean(cmd)
    return bool(AT_OK.match(c)) if c.startswith(('AT', 'ST')) else bool(OBD_OK.match(c))


def payload(text):
    """ELM reply text (headers off) -> list of data bytes of the first complete message."""
    if not text:
        return []
    lines = [re.sub(r'\s+', '', l).upper() for l in re.split(r'[\r\n]+', text)]
    lines = [l for l in lines if l and re.match(r'^[0-9A-F:]+$', l)]
    if not lines:
        return []
    if any(re.match(r'^[0-9A-F]:', l) for l in lines):
        hx = ''.join(l[2:] for l in lines if re.match(r'^[0-9A-F]:', l))
    else:
        pos = [l for l in lines if not l.startswith('7F')]
        neg = [l for l in lines if l.startswith('7F') and l[4:6] != '78']
        hx = (pos or neg or lines)[0]
    hx = hx[:len(hx) // 2 * 2]
    return [int(hx[i:i + 2], 16) for i in range(0, len(hx), 2)]


def classify(text, req):
    b = payload(text)
    if not b:
        return {'kind': 'none'}
    hx = ''.join('%02X' % x for x in b)
    if b[0] == 0x7F and len(b) >= 3:
        n = '%02X' % b[2]
        return {'kind': 'neg', 'nrc': n, 'why': NRC.get(n, 'code ' + n)}
    if b[0] == (int(req[:2], 16) + 0x40):
        return {'kind': 'ok', 'hex': hx, 'n': len(b)}
    return {'kind': 'other', 'hex': hx}


class Elm:
    def __init__(self, log):
        self.fd = None
        self.port = ''
        self.proto = ''
        self.banner = ''
        self.log = log
        self.lock = threading.RLock()
        self.target = None

    @property
    def connected(self):
        return self.fd is not None

    def open(self, path):
        self.close()
        self.log('Opening ' + path + ' ...')
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            a = termios.tcgetattr(fd)
            a[0] = 0
            a[1] = 0
            a[2] = (a[2] | termios.CLOCAL | termios.CREAD | termios.CS8) & ~(termios.PARENB | termios.CSTOPB)
            a[3] = 0
            a[6][termios.VMIN] = 0
            a[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, a)
        except Exception as e:      # not fatal: Bluetooth serial ports ignore most of this
            self.log('note: could not set serial options (' + str(e) + ')')
        self.fd = fd
        self.port = path
        self.target = None

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
        self.fd = None
        self.proto = ''

    def _drain(self):
        try:
            while select.select([self.fd], [], [], 0)[0]:
                if not os.read(self.fd, 4096):
                    break
        except OSError:
            pass

    def send(self, cmd, timeout=1.5, force=False):
        """Send one command, return reply text without the prompt, or None on timeout."""
        c = clean(cmd)
        if not force and not allowed(c):
            raise ValueError('blocked (not a read-only request): ' + c)
        with self.lock:
            if self.fd is None:
                raise IOError('adapter not connected')
            try:
                self._drain()
                os.write(self.fd, (c + '\r').encode('ascii'))
                buf = b''
                end = time.time() + timeout
                while time.time() < end:
                    r = select.select([self.fd], [], [], max(0.0, min(0.25, end - time.time())))[0]
                    if not r:
                        continue
                    chunk = os.read(self.fd, 4096)
                    if not chunk:
                        time.sleep(0.02)
                        continue
                    buf += chunk
                    if b'>' in buf:
                        return buf.decode('latin-1').replace('>', '').replace('\x00', '')
                os.write(self.fd, b'\r')          # stop whatever the adapter is still waiting for
                time.sleep(0.15)
                self._drain()
                return None
            except OSError as e:
                self.close()
                raise IOError('adapter link lost: ' + str(e))

    def init(self):
        r = self.send('ATI', 2.5) or self.send('ATZ', 4)
        if not r:
            raise IOError('no answer to ATI: is this the OBD adapter, and is it awake?')
        self.banner = ' '.join(r.split())
        self.log('Adapter: ' + self.banner)
        for c in ('ATE0', 'ATL0', 'ATS0', 'ATH0', 'ATAT1', 'ATST32', 'ATSP0'):
            self.send(c)
        r = self.send('0100', 12)
        if not r or '4100' not in re.sub(r'\s+', '', r):
            raise IOError('the car did not answer (ignition on?): ' + ' '.join((r or 'no reply').split()))
        self.proto = (self.send('ATDPN') or '').strip().lstrip('A')
        self.log('Car answered. Protocol ' + self.proto)
        self.target = None

    def set_target(self, tx, rx=None):
        tx = clean(tx)
        rx = clean(rx) if rx else '%03X' % (int(tx, 16) + 8)
        if self.target != (tx, rx):
            self.send('ATH0')
            self.send('ATSH' + tx)
            self.send('ATCRA' + rx)
            self.target = (tx, rx)

    def request(self, req, timeout=1.5):
        req = clean(req)
        u = classify(self.send(req, timeout), req)
        if u['kind'] == 'neg' and u['nrc'] == '78':
            u = classify(self.send(req, 4), req)
        return u


class Bridge:
    def __init__(self, root, port_hint):
        self.root = root
        for d in ('cmd', 'out', 'data', 'done'):
            os.makedirs(os.path.join(root, d), exist_ok=True)
        self.lines = []
        self.elm = Elm(self.log)
        self.port_hint = port_hint
        self.ask = None            # {'id','text','hold','since'}
        self.ask_done = threading.Event()
        self.busy = ''
        self.cancel = threading.Event()
        self.seen = set()
        self.queue = []
        self.qlock = threading.Lock()
        self.last_cmd = 0

    # ---------- plumbing ----------
    def log(self, msg):
        line = time.strftime('%H:%M:%S ') + str(msg)
        print(line, flush=True)
        self.lines.append(line)
        del self.lines[:-300]

    def ports(self):
        if self.port_hint:
            return [self.port_hint]
        ps = [p for p in sorted(glob.glob('/dev/cu.*')) if 'Bluetooth-Incoming' not in p and 'debug-console' not in p]
        return sorted(ps, key=lambda p: 0 if re.search(r'obd|stn|mx', p, re.I) else 1)

    def connect(self, port=None):
        port = port or (self.ports() or [None])[0]
        if not port:
            raise IOError('no serial port found. Pair the OBDLink MX+ in macOS Bluetooth settings first.')
        with self.elm.lock:
            self.elm.open(port)
            self.elm.init()

    def state(self):
        a = self.ask
        return {'connected': self.elm.connected and bool(self.elm.proto), 'port': self.elm.port, 'proto': self.elm.proto,
                'banner': self.elm.banner, 'busy': self.busy, 'ports': self.ports(),
                'ask': None if not a else {'id': a['id'], 'text': a['text'], 'hold': a['hold'], 'elapsed': time.time() - a['since']},
                'claude': 'linked' if time.time() - self.last_cmd < 600 and self.last_cmd else 'waiting for Claude',
                'log': self.lines[-60:]}

    def write_out(self, name, obj):
        p = os.path.join(self.root, 'out', name)
        with open(p + '.tmp', 'w') as f:
            json.dump(obj, f, indent=1)
        os.replace(p + '.tmp', p)

    # ---------- command intake ----------
    def watcher(self):
        cmd_dir = os.path.join(self.root, 'cmd')
        while True:
            try:
                for name in sorted(os.listdir(cmd_dir)):
                    if not name.endswith('.json') or name in self.seen:
                        continue
                    path = os.path.join(cmd_dir, name)
                    try:
                        with open(path) as f:
                            cmd = json.load(f)
                    except Exception:
                        if time.time() - os.path.getmtime(path) < 2:
                            continue                      # still being written
                        cmd = {'op': 'bad'}
                    self.seen.add(name)
                    self.last_cmd = time.time()
                    try:
                        os.replace(path, os.path.join(self.root, 'done', name))
                    except OSError:
                        pass
                    if cmd.get('op') == 'cancel':
                        self.cancel.set()
                        self.ask_done.set()
                        self.write_out(name, {'ok': True, 'cancelled': True})
                        self.log('Claude cancelled the current task')
                    else:
                        with self.qlock:
                            self.queue.append((name, cmd))
            except Exception as e:
                self.log('watcher error: ' + str(e))
            time.sleep(0.2)

    def worker(self):
        while True:
            with self.qlock:
                item = self.queue.pop(0) if self.queue else None
            if not item:
                time.sleep(0.1)
                continue
            name, cmd = item
            self.cancel.clear()
            t0 = time.time()
            try:
                op = cmd.get('op', '')
                fn = getattr(self, 'op_' + op, None)
                if not fn:
                    raise ValueError('unknown op: ' + str(op))
                self.busy = op
                res = fn(cmd, name)
                res = dict(res or {})
                res.setdefault('ok', True)
            except Exception as e:
                res = {'ok': False, 'error': str(e)}
                self.log('Task failed: ' + str(e))
            self.busy = ''
            self.ask = None
            res['secs'] = round(time.time() - t0, 2)
            res['op'] = cmd.get('op')
            self.write_out(name, res)

    def need_car(self):
        if not (self.elm.connected and self.elm.proto):
            self.connect()

    # ---------- person in the car ----------
    def wait_person(self, text, hold=0, timeout=600, sid=''):
        self.ask = {'id': sid or str(time.time()), 'text': text, 'hold': hold, 'since': time.time()}
        self.ask_done.clear()
        self.log('INSTRUCTION: ' + text)
        ok = self.ask_done.wait(timeout)
        self.ask = None
        return ok and not self.cancel.is_set()

    # ---------- operations ----------
    def op_status(self, cmd, name):
        s = self.state()
        s.pop('log', None)
        return s

    def op_connect(self, cmd, name):
        self.connect(cmd.get('port'))
        return {'port': self.elm.port, 'proto': self.elm.proto, 'banner': self.elm.banner}

    def op_ask(self, cmd, name):
        ok = self.wait_person(cmd['text'], cmd.get('hold', 0), cmd.get('timeout', 600))
        return {'done': bool(ok)}

    def op_say(self, cmd, name):
        self.log('CLAUDE: ' + cmd.get('text', ''))
        return {}

    def op_raw(self, cmd, name):
        """Adapter/OBD commands as given (allow-listed). {'cmds':[...], 'tx':'7E1', 'timeout':2}"""
        for c in cmd.get('cmds', []):
            if not allowed(c):
                raise ValueError('blocked (not a read-only request): ' + clean(c))
        self.need_car()
        if cmd.get('tx'):
            self.elm.set_target(cmd['tx'], cmd.get('rx'))
        else:
            self.elm.target = None
        out = []
        for c in cmd.get('cmds', []):
            r = self.elm.send(c, cmd.get('timeout', 2))
            out.append({'cmd': clean(c), 'reply': None if r is None else ' | '.join(x for x in re.split(r'[\r\n]+', r) if x.strip())})
        return {'replies': out}

    def op_read(self, cmd, name):
        """{'tx':'7E1','reqs':['2201A0',...]} -> parsed replies"""
        self.need_car()
        self.elm.set_target(cmd['tx'], cmd.get('rx'))
        return {'tx': cmd['tx'], 'replies': [dict(req=clean(r), **self.elm.request(r, cmd.get('timeout', 2))) for r in cmd['reqs']]}

    def op_discover(self, cmd, name):
        """Ask every diagnostic address for one harmless ID and list who answers."""
        self.need_car()
        lo, hi = int(cmd.get('from', '700'), 16), int(cmd.get('to', '7EF'), 16)
        req = clean(cmd.get('req', '22F190'))
        if not OBD_OK.match(req):
            raise ValueError('blocked request')
        e = self.elm
        e.target = None
        for c in ('ATAR', 'ATH1', 'ATST19'):
            e.send(c)
        found = []
        try:
            for tx in range(lo, hi + 1):
                if self.cancel.is_set():
                    break
                self.busy = 'discover %03X (%d of %d), found %d' % (tx, tx - lo + 1, hi - lo + 1, len(found))
                e.send('ATSH%03X' % tx)
                r = e.send(req, 1.0) or ''
                ids = {}
                for l in re.split(r'[\r\n]+', r):
                    l = re.sub(r'\s+', '', l).upper()
                    m = re.match(r'^([0-9A-F]{3})([0-9A-F]{4,})$', l)
                    if m and m.group(1) not in ids:
                        ids[m.group(1)] = m.group(2)
                for rx, first in ids.items():
                    found.append({'tx': '%03X' % tx, 'rx': rx, 'first_frame': first})
                    self.log('Module answers: %03X -> %s  %s' % (tx, rx, first))
        finally:
            for c in ('ATH0', 'ATST32', 'ATAR'):
                try:
                    e.send(c)
                except Exception:
                    pass
        return {'modules': found, 'req': req}

    def op_scan(self, cmd, name):
        """{'tx':'7E0','from':'E000','to':'E0FF','svc':'22'} -> IDs that answer. Results also appended live to data/<name>.jsonl"""
        self.need_car()
        e = self.elm
        e.set_target(cmd['tx'], cmd.get('rx'))
        svc = clean(cmd.get('svc', '22'))
        lo, hi = int(cmd['from'], 16), int(cmd['to'], 16)
        width = 4 if svc == '22' else 2
        path = os.path.join(self.root, 'data', name.replace('.json', '.jsonl'))
        found, refused, silent, miss, n = [], [], 0, 0, 0
        e.send('ATAT2')
        try:
            with open(path, 'a') as f:
                for did in range(lo, hi + 1):
                    if self.cancel.is_set():
                        break
                    n += 1
                    req = svc + ('%0*X' % (width, did))
                    u = e.request(req, 0.8)
                    if u['kind'] == 'ok':
                        miss = 0
                        rec = {'req': req, 'hex': u['hex'], 'n': u['n']}
                        found.append(rec)
                        f.write(json.dumps(rec) + '\n')
                        f.flush()
                    elif u['kind'] == 'neg':
                        miss = 0
                        if u['nrc'] not in ('31', '11', '12'):
                            refused.append({'req': req, 'why': u['why']})
                    elif u['kind'] == 'none':
                        silent += 1
                        miss += 1
                        if miss >= 40 and not cmd.get('patient'):
                            self.log('no reply 40 times in a row, stopping this range at ' + req)
                            break
                    if n % 16 == 0:
                        self.busy = 'scan %s %s: %d of %d, found %d' % (cmd['tx'], req, n, hi - lo + 1, len(found))
        finally:
            try:
                e.send('ATAT1')
            except Exception:
                pass
        self.log('Scan %s %s %s-%s: %d answered' % (cmd['tx'], svc, cmd['from'], cmd['to'], len(found)))
        return {'tx': cmd['tx'], 'checked': n, 'found': found, 'refused': refused, 'silent': silent, 'stopped_early': self.cancel.is_set(), 'file': path}

    def op_session(self, cmd, name):
        """Record data blocks continuously while the person follows steps.
        {'tx':'7E1','reqs':['2201A0'],'steps':[{'id':'P','text':'Lever in P','hold':5} or {'id':'idle','text':'Just wait','secs':10}]}
        A step with 'secs' advances by itself; otherwise the person taps DONE (enabled after 'hold' seconds)."""
        self.need_car()
        e = self.elm
        e.set_target(cmd['tx'], cmd.get('rx'))
        reqs = [clean(r) for r in cmd['reqs']]
        for r in reqs:
            if not OBD_OK.match(r):
                raise ValueError('blocked request ' + r)
        path = os.path.join(self.root, 'data', name.replace('.json', '.jsonl'))
        t0 = time.time()
        count, summary = 0, []
        with open(path, 'a') as f:
            for i, st in enumerate(cmd['steps']):
                if self.cancel.is_set():
                    break
                sid = st.get('id', 'step%d' % (i + 1))
                secs = st.get('secs')
                self.busy = 'session step %d of %d: %s' % (i + 1, len(cmd['steps']), sid)
                self.ask = {'id': name + sid, 'text': st.get('text', sid), 'hold': st.get('hold', 0) if secs is None else -secs, 'since': time.time()}
                self.ask_done.clear()
                self.log('STEP %s: %s' % (sid, st.get('text', '')))
                s0, n0 = time.time(), count
                limit = st.get('timeout', 600)
                while not self.cancel.is_set():
                    for r in reqs:
                        u = e.request(r, 1.5)
                        f.write(json.dumps({'t': round(time.time() - t0, 3), 'step': sid, 'req': r, 'hex': u.get('hex'), 'kind': u['kind']}) + '\n')
                        count += 1
                    f.flush()
                    el = time.time() - s0
                    if secs is not None:
                        if el >= secs:
                            break
                    elif self.ask_done.is_set() or el > limit:
                        break
                summary.append({'id': sid, 'secs': round(time.time() - s0, 1), 'samples': count - n0})
        self.ask = None
        return {'file': path, 'samples': count, 'steps': summary, 'stopped_early': self.cancel.is_set()}

    def op_dtc(self, cmd, name):
        """Read stored / pending / permanent emission codes (services 03, 07, 0A) from the given ECUs."""
        self.need_car()
        out = []
        for tx in cmd.get('tx', ['7E0', '7E1']):
            self.elm.set_target(tx)
            for svc, label in (('03', 'stored'), ('07', 'pending'), ('0A', 'permanent')):
                r = self.elm.send(svc, 3)
                b = payload(r)
                codes = []
                if b and b[0] == int(svc, 16) + 0x40:
                    d = b[2:]
                    for i in range(0, len(d) - 1, 2):
                        a, c = d[i], d[i + 1]
                        if a or c:
                            codes.append('PCBU'[a >> 6] + '%d%X%02X' % ((a >> 4) & 3, a & 15, c))
                out.append({'tx': tx, 'type': label, 'codes': codes, 'raw': None if r is None else ' '.join(r.split())})
        return {'dtc': out}


PAGE = r'''<!doctype html><meta charset="utf-8"><title>Fast OBD bridge</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;background:#111418;color:#e8ecf1;font:16px/1.45 system-ui,sans-serif;padding:18px;max-width:900px;margin:auto}
.card{background:#1b2027;border-radius:12px;padding:14px 16px;margin:12px 0}
h1{font-size:20px;margin:4px 0}small{color:#8b96a5}
.pill{display:inline-block;padding:3px 10px;border-radius:99px;background:#232a33;margin-right:6px;font-size:13px}
.ok{color:#3ecf8e}.bad{color:#ff5c5c}.warn{color:#f5a524}
#ask{display:none;border:2px solid #4da3ff}
#askText{font-size:30px;font-weight:700;margin:8px 0 14px}
button{font:inherit;border:0;border-radius:10px;padding:12px 18px;background:#2a323c;color:#e8ecf1;cursor:pointer}
#done{font-size:26px;font-weight:700;padding:22px;width:100%;background:#8b96a5;color:#fff}
#done.ready{background:#3ecf8e;color:#06281a}
pre{white-space:pre-wrap;font:12px ui-monospace,monospace;color:#8b96a5;max-height:320px;overflow:auto;margin:0}
select{font:inherit;padding:10px;border-radius:8px;background:#232a33;color:#e8ecf1;border:0}
</style>
<h1>Fast OBD bridge <small>parked use only · read-only</small></h1>
<div class="card"><span class="pill" id="pConn"></span><span class="pill" id="pClaude"></span><span class="pill" id="pBusy"></span>
<div style="margin-top:10px"><select id="ports"></select> <button id="connect">Connect</button> <button id="stop">Stop current task</button></div></div>
<div class="card" id="ask"><small>Claude asks you to:</small><div id="askText"></div><button id="done">DONE</button></div>
<div class="card"><small>Activity</small><pre id="log"></pre></div>
<script>
const $=id=>document.getElementById(id); let askId=null;
async function post(u,b){ try{ return await (await fetch(u,{method:'POST',body:JSON.stringify(b||{})})).json(); }catch(e){ return {ok:false,error:String(e)}; } }
$('connect').onclick=async()=>{ $('connect').disabled=true; const r=await post('/connect',{port:$('ports').value}); if(!r.ok) alert(r.error); $('connect').disabled=false; };
$('done').onclick=()=>post('/done'); $('stop').onclick=()=>post('/cancel');
async function tick(){
  let s; try{ s=await (await fetch('/state')).json(); }catch(e){ $('pConn').innerHTML='<span class="bad">bridge script not running</span>'; return; }
  $('pConn').innerHTML=s.connected?'<span class="ok">car connected</span> · protocol '+s.proto:'<span class="bad">not connected</span>';
  $('pClaude').innerHTML=s.claude==='linked'?'<span class="ok">Claude linked</span>':'<span class="warn">'+s.claude+'</span>';
  $('pBusy').textContent=s.busy?('working: '+s.busy):'idle';
  const sel=$('ports'); const cur=sel.value; if(sel.options.length!==s.ports.length){ sel.innerHTML=s.ports.map(p=>'<option>'+p+'</option>').join(''); if(cur) sel.value=cur; }
  if(s.ask){ $('ask').style.display='block'; $('askText').textContent=s.ask.text; const b=$('done');
    if(s.ask.hold<0){ const left=Math.max(0,Math.ceil(-s.ask.hold-s.ask.elapsed)); b.textContent='recording… '+left+' s'; b.className=''; b.disabled=true; }
    else { const left=Math.ceil(s.ask.hold-s.ask.elapsed); b.disabled=false; b.className=left<=0?'ready':''; b.textContent=left>0?'DONE (hold '+left+' s)':'DONE'; }
    if(askId!==s.ask.id){ askId=s.ask.id; window.scrollTo(0,0); } }
  else { $('ask').style.display='none'; askId=null; }
  const lg=$('log'); const atEnd=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-20; lg.textContent=s.log.join('\n'); if(atEnd) lg.scrollTop=lg.scrollHeight;
}
setInterval(tick,400); tick();
document.addEventListener('keydown',e=>{ if((e.key===' '||e.key==='Enter')&&$('ask').style.display!=='none'&&!$('done').disabled){ e.preventDefault(); post('/done'); } });
</script>'''


def make_handler(bridge):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/state':
                return self._json(bridge.state())
            body = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get('Content-Length') or 0)
            try:
                data = json.loads(self.rfile.read(n) or b'{}')
            except Exception:
                data = {}
            if self.path == '/done':
                a = bridge.ask
                if a and a['hold'] >= 0:
                    bridge.ask_done.set()
                return self._json({'ok': True})
            if self.path == '/cancel':
                bridge.cancel.set()
                bridge.ask_done.set()
                bridge.log('Stopped by you')
                return self._json({'ok': True})
            if self.path == '/connect':
                if bridge.busy:
                    return self._json({'ok': False, 'error': 'busy with: ' + bridge.busy})
                try:
                    bridge.connect(data.get('port'))
                    return self._json({'ok': True})
                except Exception as e:
                    bridge.log('Connect failed: ' + str(e))
                    return self._json({'ok': False, 'error': str(e)})
            self._json({'ok': False, 'error': 'unknown'}, 404)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', help='serial port (default: first /dev/cu.* that looks like the OBD adapter)')
    ap.add_argument('--dir', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bridge'))
    ap.add_argument('--http', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    b = Bridge(a.dir, a.port)
    b.log('Fast OBD bridge. Shared folder: ' + a.dir)
    threading.Thread(target=b.watcher, daemon=True).start()
    threading.Thread(target=b.worker, daemon=True).start()

    def first_connect():
        try:
            b.connect()
        except Exception as e:
            b.log('Not connected yet: ' + str(e) + '  (choose the port on the page and press Connect)')
    threading.Thread(target=first_connect, daemon=True).start()
    srv = ThreadingHTTPServer(('127.0.0.1', a.http), make_handler(b))
    url = 'http://localhost:%d' % a.http
    b.log('Page: ' + url + '   (Ctrl-C here to quit)')
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nbye')


if __name__ == '__main__':
    main()
