#!/usr/bin/env python3
# Busy window without buttons (zenity's pulsating progress has an OK that does nothing).
# Reads "# text" lines from stdin like zenity --progress; ends when killed. No GTK: becomes zenity (same PID).
import os
import sys

title = sys.argv[1] if len(sys.argv) > 1 else "ChituLinux"


def zenity():
    os.execvp("zenity", ["zenity", "--progress", "--pulsate", "--no-cancel", "--width=460", "--title=" + title])


try:
    import gi
    try:
        gi.require_version("Gtk", "4.0")
        GTK = 4
    except ValueError:
        gi.require_version("Gtk", "3.0")
        GTK = 3
    from gi.repository import GLib, Gtk
except Exception:
    zenity()

if not (Gtk.init_check() if GTK == 4 else Gtk.init_check()[0]):
    zenity()

win = Gtk.Window(title=title)
win.set_default_size(460, -1)
win.set_resizable(False)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
for side in ("top", "bottom", "start", "end"):
    getattr(box, "set_margin_" + side)(20)
label = Gtk.Label(label="")
label.set_xalign(0)
label.set_wrap(True) if GTK == 4 else label.set_line_wrap(True)
bar = Gtk.ProgressBar()
box_add = box.append if GTK == 4 else box.add
box_add(label)
box_add(bar)
(win.set_child if GTK == 4 else win.add)(box)

def pulse():
    bar.pulse()
    return True

GLib.timeout_add(100, pulse)

buf = b""

def on_input(fd, cond):
    global buf
    data = os.read(fd, 4096) if cond & GLib.IOCondition.IN else b""
    if not data:  # EOF: stay until killed (Wine's processes may hold the pipe)
        return False
    buf += data
    *lines, buf = buf.split(b"\n")
    for line in lines:
        line = line.decode(errors="replace")
        if line.startswith("#"):
            label.set_text(line[1:].strip())
    return True

GLib.io_add_watch(0, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN | GLib.IOCondition.HUP, on_input)

if GTK == 4:
    loop = GLib.MainLoop()
    win.connect("close-request", lambda w: (loop.quit(), False)[1])
    win.present()
    loop.run()
else:
    win.connect("delete-event", lambda *a: Gtk.main_quit())
    win.show_all()
    Gtk.main()
