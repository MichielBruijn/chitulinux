#!/usr/bin/env python3
"""wait-window.py CLASS PID [TIMEOUT]: wait until an X11 window of WM_CLASS CLASS is on screen, PID has ended
or TIMEOUT seconds (default 120) have passed. For the "Starting CHITUBOX" dialog: Wine draws on X11 (also
under Wayland, through Xwayland). Without libX11 or a display: waits until PID ends or the timeout"""
import ctypes, ctypes.util, os, sys, time


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    # a zombie (ended, not yet reaped) counts as ended
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:
        return False


class ClassHint(ctypes.Structure):
    _fields_ = [('res_name', ctypes.c_char_p), ('res_class', ctypes.c_char_p)]


class Attributes(ctypes.Structure):
    # XWindowAttributes up to map_state; the rest as padding
    _fields_ = [('x', ctypes.c_int), ('y', ctypes.c_int), ('width', ctypes.c_int), ('height', ctypes.c_int),
                ('border_width', ctypes.c_int), ('depth', ctypes.c_int), ('visual', ctypes.c_void_p),
                ('root', ctypes.c_ulong), ('class_', ctypes.c_int), ('bit_gravity', ctypes.c_int),
                ('win_gravity', ctypes.c_int), ('backing_store', ctypes.c_int),
                ('backing_planes', ctypes.c_ulong), ('backing_pixel', ctypes.c_ulong),
                ('save_under', ctypes.c_int), ('colormap', ctypes.c_ulong), ('map_installed', ctypes.c_int),
                ('map_state', ctypes.c_int), ('pad', ctypes.c_char * 256)]


def x11():
    name = ctypes.util.find_library('X11') or 'libX11.so.6'
    x = ctypes.cdll.LoadLibrary(name)
    W, P = ctypes.c_ulong, ctypes.c_void_p
    x.XOpenDisplay.restype = P
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = W
    x.XDefaultRootWindow.argtypes = [P]
    x.XQueryTree.argtypes = [P, W, ctypes.POINTER(W), ctypes.POINTER(W), ctypes.POINTER(ctypes.POINTER(W)),
                             ctypes.POINTER(ctypes.c_uint)]
    x.XGetClassHint.argtypes = [P, W, ctypes.POINTER(ClassHint)]
    x.XGetWindowAttributes.argtypes = [P, W, ctypes.POINTER(Attributes)]
    x.XFree.argtypes = [P]
    # a window that disappears between XQueryTree and the next call: BadWindow, which must not end us
    handler = ctypes.CFUNCTYPE(ctypes.c_int, P, P)(lambda d, e: 0)
    x.XSetErrorHandler.argtypes = [handler.__class__]
    x.XSetErrorHandler(handler)
    x._keep = handler
    return x


def shown(x, d, root, wanted):
    """a viewable window of class wanted: among the root's children (override-redirect) and their children
    (a window manager's frames)"""
    def children(w):
        r, p, kids, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
        if not x.XQueryTree(d, w, ctypes.byref(r), ctypes.byref(p), ctypes.byref(kids), ctypes.byref(n)):
            return []
        out = [kids[i] for i in range(n.value)]
        if kids:
            x.XFree(kids)
        return out

    def match(w):
        a = Attributes()
        if not x.XGetWindowAttributes(d, w, ctypes.byref(a)) or a.map_state != 2:  # IsViewable
            return False
        h = ClassHint()
        if not x.XGetClassHint(d, w, ctypes.byref(h)):
            return False
        ok = (h.res_class or b'').decode(errors='replace').lower() == wanted or \
             (h.res_name or b'').decode(errors='replace').lower() == wanted
        return ok and a.width > 1 and a.height > 1

    for top in children(root):
        if match(top) or any(match(c) for c in children(top)):
            return True
    return False


def main():
    wanted, pid = sys.argv[1].lower(), int(sys.argv[2])
    end = time.monotonic() + (float(sys.argv[3]) if len(sys.argv) > 3 else 120)
    x = d = None
    try:
        if os.environ.get('DISPLAY'):
            x = x11()
            d = x.XOpenDisplay(None)
    except OSError:
        pass
    start = time.monotonic()
    why = 'timeout' if d else 'no X11 display'
    while time.monotonic() < end:
        if not alive(pid):
            why = 'ended'
            break
        if d and shown(x, d, x.XDefaultRootWindow(d), wanted):
            why = 'window'
            break
        time.sleep(0.3)
    print(f'wait-window: {why} after {time.monotonic() - start:.1f}s', file=sys.stderr)


if __name__ == '__main__':
    main()
