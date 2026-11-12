"""Run Kit in a real pty, emulate the terminal (with colours), and capture screenshots."""
import codecs, os, pty, re, select, struct, fcntl, termios, time, sys
from PIL import Image, ImageDraw, ImageFont

QUAD = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

def c256(n):
    if n < 16: return (128, 128, 128)
    if n >= 232: v = 8 + (n - 232) * 10; return (v, v, v)
    n -= 16; lv = [0, 95, 135, 175, 215, 255]; return (lv[n // 36], lv[(n // 6) % 6], lv[n % 6])

class Emu:
    def __init__(s, rows, cols):
        s.R, s.C = rows, cols; s.reset(); s.carry = ""
    def reset(s):
        s.g = [[(" ", (230, 230, 230), (0, 0, 0))] * s.C for _ in range(s.R)]
        s.r = s.c = 0; s.fg = (230, 230, 230); s.bg = (0, 0, 0); s.sv = (0, 0, (230, 230, 230), (0, 0, 0)); s.alt = False
    def sgr(s, a):
        i = 0
        while i < len(a):
            v = a[i]
            if v == 0: s.fg, s.bg = (230, 230, 230), (0, 0, 0)
            elif v == 38 and i + 1 < len(a) and a[i + 1] == 2: s.fg = tuple(a[i + 2:i + 5]); i += 4
            elif v == 48 and i + 1 < len(a) and a[i + 1] == 2: s.bg = tuple(a[i + 2:i + 5]); i += 4
            elif v == 38 and i + 1 < len(a) and a[i + 1] == 5: s.fg = c256(a[i + 2]); i += 2
            elif v == 48 and i + 1 < len(a) and a[i + 1] == 5: s.bg = c256(a[i + 2]); i += 2
            i += 1
    def feed(s, data):
        data = s.carry + data; s.carry = ""; i = 0
        while i < len(data):
            ch = data[i]
            if ch == "\x1b":
                m = re.match(r"\x1b\[([?0-9;]*)([A-Za-z])", data[i:])
                if m:
                    p, f = m.groups(); i += m.end()
                    if p.startswith("?"):
                        if p == "?1049" and f == "h": s.reset()
                        continue
                    a = [int(x) if x else 0 for x in p.split(";")] if p else []
                    if f == "m": s.sgr(a or [0])
                    elif f == "H": s.r = (a[0] or 1) - 1 if a else 0; s.c = ((a[1] or 1) - 1) if len(a) > 1 else 0; s.r = min(s.r, s.R - 1); s.c = min(s.c, s.C - 1)
                    elif f == "K":
                        mode = a[0] if a else 0
                        rng = range(s.c, s.C) if mode == 0 else range(0, s.C)
                        for x in rng: s.g[s.r][x] = (" ", s.fg, s.bg)
                    elif f == "J":
                        if a and a[0] == 2: s.g = [[(" ", s.fg, s.bg)] * s.C for _ in range(s.R)]
                    continue
                if i + 1 >= len(data): s.carry = data[i:]; return
                if data[i + 1] == "7": s.sv = (s.r, s.c, s.fg, s.bg); i += 2; continue
                if data[i + 1] == "8": s.r, s.c, s.fg, s.bg = s.sv; i += 2; continue
                if data[i + 1] == "]":
                    j = data.find("\x07", i)
                    if j < 0: s.carry = data[i:]; return
                    i = j + 1; continue
                if data[i + 1] == "[" : s.carry = data[i:]; return
                i += 2; continue
            i += 1
            if ch == "\n": s.r = min(s.r + 1, s.R - 1)
            elif ch == "\r": s.c = 0
            elif ch in "\x01\x02\x07": pass
            elif ch == "\x08": s.c = max(0, s.c - 1)
            elif ch >= " ":
                if s.c >= s.C: s.c = 0; s.r = min(s.r + 1, s.R - 1)
                s.g[s.r][s.c] = (ch, s.fg, s.bg); s.c += 1
    def text(s): return "\n".join("".join(c[0] for c in row).rstrip() for row in s.g)
    def image(s, path, cw=9, ch=18):
        im = Image.new("RGB", (s.C * cw, s.R * ch)); d = ImageDraw.Draw(im)
        try: font = ImageFont.truetype(FONT, 14)
        except Exception: font = ImageFont.load_default()
        for y, row in enumerate(s.g):
            for x, (chr_, f, b) in enumerate(row):
                X, Y = x * cw, y * ch
                d.rectangle([X, Y, X + cw, Y + ch], fill=b)
                if chr_ in QUAD and chr_ != " " or chr_ == "▀":
                    m = 3 if chr_ == "▀" else QUAD.index(chr_)
                    for sy in range(2):
                        for sx in range(2):
                            if m >> (sy * 2 + sx) & 1:
                                d.rectangle([X + sx * cw // 2, Y + sy * ch // 2, X + (sx + 1) * cw // 2, Y + (sy + 1) * ch // 2], fill=f)
                elif chr_ == "█": d.rectangle([X, Y, X + cw, Y + ch], fill=f)
                elif chr_ != " ": d.text((X, Y + 1), chr_, font=font, fill=f)
        im.save(path)

class Session:
    def __init__(self, rows=36, cols=124, args=(), env=None, cwd=None):
        self.emu = Emu(rows, cols); self.raw = b""; self.dec = codecs.getincrementaldecoder('utf-8')('replace')
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            e = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", HOME="/tmp/kithome", **(env or {}))
            if cwd: os.chdir(cwd)
            os.execvpe("python3", ["python3", "/mnt/user-data/outputs/corvi/kit.py", "--base-url", "http://127.0.0.1:11999/v1", *args], e)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    def pump(self, sec):
        end = time.time() + sec
        while time.time() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                try: d = os.read(self.fd, 65536)
                except OSError: return False
                if not d: return False
                self.raw += d; self.emu.feed(self.dec.decode(d))
        return True
    def send(self, s, wait=0.6): os.write(self.fd, s.encode()); self.pump(wait)
    def resize(self, rows, cols):
        self.emu.R, self.emu.C = rows, cols; self.emu.reset()
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        os.kill(self.pid, 28); self.pump(0.8)


import subprocess, atexit
_SERVERS = {}
def start_mock(port=11999, script=None):
    """Start the scripted model server on a port (kept alive for this process)."""
    if port in _SERVERS: return
    here = os.path.dirname(os.path.abspath(__file__))
    p = subprocess.Popen([sys.executable, os.path.join(here, "mock_server.py"), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _SERVERS[port] = p; atexit.register(p.kill); time.sleep(0.8)
