#!/usr/bin/env python3
"""CHITUBOX → Resin Print Portal: a network printer in CHITUBOX that hands what it gets to RPP.

usage: rpp-bridge.py --rpp URL --spool DIR [--log FILE] [--watch PID] [--printer HOST]

CHITUBOX sends files to SDCP V1 printers (ELEGOO Saturn 3 Ultra, Mars 4 Ultra, ...) on its own LAN: it
broadcasts M99999 on UDP port 3000, the printer answers with its attributes; to send, CHITUBOX runs an MQTT
broker and tells the printer with M66666 PORT to connect to it, then asks it (Cmd 256) to download the file
from CHITUBOX's HTTP server. This answers as that printer, under the name "RPP (...)", downloads the file
and uploads it to RPP (POST /upload). "Start printing" in CHITUBOX (Cmd 128) asks RPP to print it.

The printer's model and resolution (CHITUBOX lists only printers of the machine chosen in it) come from
the printer RPP uses, asked once with M99999, as RPP itself does; nothing else is ever sent to the printer.
Runs until PID (CHITUBOX) exits.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid

PORT = 3000
SAVED = None  # the printer's attributes, in --spool
log_file = None


def log(*args):
    line = time.strftime('%F %T ') + ' '.join(str(a) for a in args)
    print(line, file=log_file or sys.stderr, flush=True)


# --- RPP ------------------------------------------------------------------------------------------------

class RPP:
    def __init__(self, url):
        self.url = url.rstrip('/')
        u = urllib.parse.urlsplit(self.url)
        self.https = u.scheme == 'https'
        self.host = u.hostname
        self.port = u.port or (443 if self.https else 80)
        self.base = u.path

    def get(self, path, timeout=10):
        with urllib.request.urlopen(self.url + path, timeout=timeout) as r:
            return json.load(r)

    def post_json(self, path, data, timeout=30):
        req = urllib.request.Request(self.url + path, json.dumps(data).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def upload(self, path, name, progress=None):
        """POST /upload as multipart, streamed; RPP's answer (its name for the file in 'filename')."""
        boundary = uuid.uuid4().hex
        quoted = name.replace('"', '_')
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{quoted}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode()
        tail = f'\r\n--{boundary}--\r\n'.encode()
        size = os.path.getsize(path)
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        conn = cls(self.host, self.port, timeout=120)
        try:
            conn.putrequest('POST', self.base + '/upload')
            conn.putheader('Content-Type', f'multipart/form-data; boundary={boundary}')
            conn.putheader('Content-Length', str(len(head) + size + len(tail)))
            conn.endheaders()
            conn.send(head)
            done = 0
            with open(path, 'rb') as f:
                while chunk := f.read(1 << 20):
                    conn.send(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, size)
            conn.send(tail)
            r = conn.getresponse()
            body = r.read()
        finally:
            conn.close()
        try:
            answer = json.loads(body)
        except ValueError:
            raise OSError(f'RPP answered {r.status}: {body[:200]!r}')
        if r.status != 200 or 'error' in answer:
            raise OSError(f"RPP: {answer.get('error', r.status)}")
        return answer


def printer_attributes(rpp, host=None):
    """The attributes of the printer RPP prints on, asked once (M99999); saved for when it is off."""
    try:
        host = host or rpp.get('/get-printer-ip').get('ip')
        if host:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            with s:
                s.settimeout(3)
                s.sendto(b'M99999', (host, PORT))
                data, _ = s.recvfrom(8192)
            attrs = json.loads(data)['Data']['Attributes']
            try:
                with open(SAVED + '.tmp', 'w') as f:
                    json.dump(attrs, f)
                os.replace(SAVED + '.tmp', SAVED)
            except OSError:
                pass
            return attrs
    except (OSError, ValueError, KeyError) as e:
        log('the printer did not answer:', e)
    try:
        with open(SAVED) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# --- MQTT 3.1.1, the client side, just what SDCP needs ------------------------------------------------

def mqtt_str(s):
    b = s.encode()
    return struct.pack('>H', len(b)) + b


def mqtt_packet(kind, body):
    n, length = len(body), b''
    while True:
        byte, n = n % 128, n // 128
        length += bytes([byte | (0x80 if n else 0)])
        if not n:
            return bytes([kind]) + length + body


class MQTT:
    def __init__(self, host, port, client_id):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.lock = threading.Lock()
        self.pid = 0
        self.send(mqtt_packet(0x10, mqtt_str('MQTT') + bytes([4, 2]) + struct.pack('>H', 60) + mqtt_str(client_id)))
        kind, body = self.read()
        if kind >> 4 != 2 or body[1] != 0:
            raise OSError(f'MQTT connection refused ({body!r})')
        self.sock.settimeout(None)

    def send(self, data):
        with self.lock:
            self.sock.sendall(data)

    def recv(self, n):
        b = b''
        while len(b) < n:
            chunk = self.sock.recv(n - len(b))
            if not chunk:
                raise EOFError('MQTT connection closed')
            b += chunk
        return b

    def read(self):
        kind = self.recv(1)[0]
        n, shift = 0, 0
        while True:
            byte = self.recv(1)[0]
            n |= (byte & 0x7f) << shift
            shift += 7
            if not byte & 0x80:
                break
        return kind, self.recv(n)

    def subscribe(self, topic):
        self.pid = self.pid % 0xffff + 1
        self.send(mqtt_packet(0x82, struct.pack('>H', self.pid) + mqtt_str(topic) + b'\0'))

    def publish(self, topic, payload):
        # QoS 1, as printers publish (Cassini's broker expects a packet ID)
        with self.lock:
            self.pid = self.pid % 0xffff + 1
            pid = self.pid
        self.send(mqtt_packet(0x32, mqtt_str(topic) + struct.pack('>H', pid) + payload.encode()))

    def ping(self):
        self.send(b'\xc0\0')

    def messages(self):
        """(topic, payload) of each PUBLISH, until the connection closes."""
        while True:
            kind, body = self.read()
            if kind >> 4 == 3:
                qos = (kind >> 1) & 3
                n = struct.unpack('>H', body[:2])[0]
                topic, rest = body[2:2 + n].decode(), body[2 + n:]
                if qos:
                    self.send(mqtt_packet(0x40 if qos == 1 else 0x50, rest[:2]))
                    rest = rest[2:]
                elif rest[2:3] == b'{' and rest[:1] != b'{':
                    rest = rest[2:]  # Cassini's broker: a packet ID also at QoS 0
                yield topic, rest.decode('utf-8', 'replace')

    def close(self):
        try:
            self.send(b'\xe0\0')
            self.sock.close()
        except OSError:
            pass


# --- the printer --------------------------------------------------------------------------------------

class Printer:
    def __init__(self, rpp, attrs, spool):
        self.rpp = rpp
        self.spool = spool
        self.attrs = dict(attrs)
        self.id = hashlib.md5(b'rpp' + attrs.get('MainboardID', '').encode()).hexdigest()[:16]
        self.sid = uuid.uuid4().hex
        self.attrs.update(Name=f"RPP ({attrs.get('Name') or attrs.get('MachineName') or 'printer'})",
                          MainboardID=self.id, SDCPStatus=0, LocalSDCPAddress='', SDCPAddress='')
        self.transfer = dict(Status=0, DownloadOffset=0, CheckOffset=0, FileTotalSize=0, Filename='')
        self.busy = False
        self.files = {}  # CHITUBOX's name -> RPP's
        self.mqtt = None

    def status(self):
        return dict(CurrentStatus=1 if self.busy else 0, PreviousStatus=0,
                    PrintInfo=dict(Status=0, CurrentLayer=0, TotalLayer=0, CurrentTicks=0, TotalTicks=0,
                                   ErrorNumber=0, Filename=''),
                    FileTransferInfo=dict(self.transfer))

    def discovery(self, ip):
        return json.dumps(dict(Id=self.sid, Data=dict(Attributes=dict(self.attrs, MainboardIP=ip),
                                                      Status=self.status())))

    def message(self, data):
        return json.dumps(dict(Id=self.sid, Data=dict(data, MainboardID=self.id,
                                                      TimeStamp=int(time.time() * 1000))))

    def send_status(self):
        if self.mqtt:
            self.mqtt.publish(f'/sdcp/status/{self.id}', self.message(dict(Status=self.status())))

    def respond(self, req, ack=0):
        self.mqtt.publish(f'/sdcp/response/{self.id}', self.message(
            dict(Cmd=req['Cmd'], Data=dict(Ack=ack), RequestID=req.get('RequestID', ''))))

    # CHITUBOX's MQTT broker at HOST:PORT
    def connect(self, host, port):
        if self.mqtt:
            self.mqtt.close()
        log(f'connecting to CHITUBOX at {host}:{port}')
        mqtt = self.mqtt = MQTT(host, port, self.id)
        mqtt.subscribe(f'/sdcp/request/{self.id}')
        self.send_status()
        mqtt.publish(f'/sdcp/attributes/{self.id}', self.message(dict(Attributes=self.attrs)))
        alive = threading.Event()

        def keepalive():
            while not alive.wait(5):
                try:
                    mqtt.ping()
                    self.send_status()
                except OSError:
                    return
        threading.Thread(target=keepalive, daemon=True).start()
        try:
            for topic, payload in mqtt.messages():
                try:
                    req = json.loads(payload)['Data']
                except (ValueError, KeyError, TypeError):
                    continue
                self.request(req, host)
                if req.get('Cmd') == 64:
                    break
        except (OSError, EOFError) as e:
            log('MQTT:', e)
        finally:
            alive.set()
            mqtt.close()
            if self.mqtt is mqtt:
                self.mqtt = None
            log('disconnected')

    def request(self, req, host):
        cmd = req.get('Cmd')
        data = req.get('Data') or {}
        log('request', cmd, {k: v for k, v in data.items() if k != 'MD5'} if isinstance(data, dict) else data)
        if cmd == 256:
            if self.busy:
                return self.respond(req, 1)
            self.respond(req, 0)
            self.busy = True
            threading.Thread(target=self.receive, args=(data, host), daemon=True).start()
        elif cmd == 128:
            name = self.files.get(data.get('Filename'))
            if not name:
                return self.respond(req, 2)
            try:
                answer = self.rpp.post_json('/print-file', {'filename': name})
                log('RPP print:', answer)
                self.respond(req, 1 if 'error' in answer else 0)
            except (OSError, ValueError) as e:
                log('RPP print failed:', e)
                self.respond(req, 1)
        else:  # 0, 1, 64 (disconnect), 512 (status period), ...
            self.respond(req, 0)

    # Cmd 256: download from CHITUBOX, check, hand to RPP
    def receive(self, data, host):
        given = str(data.get('Filename') or 'chitubox.ctb')
        name = os.path.basename(given.replace('\\', '/'))
        size = int(data.get('FileSize') or 0)
        url = str(data.get('URL', '')).replace('${ipaddr}', host)
        self.transfer = dict(Status=0, DownloadOffset=0, CheckOffset=0, FileTotalSize=size, Filename=given)
        last = [0.0]

        def progress(done, total, upload=False):
            # CHITUBOX shows one transfer: the download from it is the first half, the upload to RPP the second
            part = done / total if total else 0
            self.transfer['DownloadOffset'] = int((0.5 + part / 2 if upload else part / 2) * size)
            if time.time() - last[0] > 0.5:
                last[0] = time.time()
                self.send_status()

        fd, tmp = tempfile.mkstemp(dir=self.spool, suffix='-' + name)
        try:
            log(f'downloading {name} ({size} bytes) from {url}')
            md5 = hashlib.md5()
            done = 0
            with os.fdopen(fd, 'wb') as f, urllib.request.urlopen(url, timeout=60) as r:
                total = size or int(r.headers.get('Content-Length') or 0)
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    md5.update(chunk)
                    done += len(chunk)
                    progress(done, total or done)
            if size and done != size:
                raise OSError(f'got {done} of {size} bytes')
            if data.get('MD5') and md5.hexdigest().lower() != str(data['MD5']).lower():
                raise OSError('MD5 does not match')
            log(f'uploading {name} to {self.rpp.url}')
            answer = self.rpp.upload(tmp, name, lambda d, t: progress(d, t, True))
            self.files[given] = answer.get('filename') or name
            log('RPP:', answer)
            self.transfer.update(Status=2, DownloadOffset=size or done, FileTotalSize=size or done)
        except Exception as e:  # anything: CHITUBOX must hear that it failed
            log(f'sending {name} failed: {e}')
            self.transfer['Status'] = 3
        finally:
            self.busy = False
            try:
                os.remove(tmp)
            except OSError:
                pass
            self.send_status()


def main():
    global log_file
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rpp', required=True, help="RPP's address, e.g. http://bloemkool:5001")
    ap.add_argument('--log')
    ap.add_argument('--spool', required=True, help='a folder for files on their way, and what it knows')
    ap.add_argument('--watch', type=int, help='exit when this process is gone')
    ap.add_argument('--printer', help="the printer's address (default: RPP's setting)")
    a = ap.parse_args()
    if a.log:
        log_file = open(a.log, 'a')
    os.makedirs(a.spool, exist_ok=True)
    global SAVED
    SAVED = os.path.join(a.spool, 'printer.json')

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        udp.bind(('', PORT))
    except OSError as e:
        log(f'UDP port {PORT} is taken ({e}); another bridge runs')
        return 1
    rpp = RPP(a.rpp)
    attrs = printer_attributes(rpp, a.printer)
    if not attrs:
        log("the printer's model is unknown (printer and RPP off?); not offering RPP to CHITUBOX")
        return 1
    printer = Printer(rpp, attrs, a.spool)
    log(f"offering {printer.attrs['Name']} ({attrs.get('MachineName')}, {attrs.get('Resolution')}) "
        f'to CHITUBOX, sending to {rpp.url}')

    if a.watch:
        def watch():
            while os.path.exists(f'/proc/{a.watch}'):
                time.sleep(2)
            log('CHITUBOX closed')
            os._exit(0)
        threading.Thread(target=watch, daemon=True).start()

    while True:
        data, addr = udp.recvfrom(1024)
        text = data.decode('ascii', 'replace').strip()
        if text == 'M99999':
            # answered from the address CHITUBOX reached us on
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                probe.connect(addr)
                ip = probe.getsockname()[0]
            finally:
                probe.close()
            udp.sendto(printer.discovery(ip).encode(), addr)
        elif m := re.fullmatch(r'M66666 (\d+)', text):
            threading.Thread(target=lambda: _connect(printer, addr[0], int(m.group(1))), daemon=True).start()


def _connect(printer, host, port):
    try:
        printer.connect(host, port)
    except Exception as e:
        log(f'connecting to CHITUBOX failed: {e}')


if __name__ == '__main__':
    sys.exit(main())
