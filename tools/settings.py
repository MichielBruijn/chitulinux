#!/usr/bin/env python3
"""ChituLinux settings: scale, graphics and Wine's tools.

usage: settings.py   (needs CHITULINUX_HOME, WINEPREFIX and CHITULINUX_RUN; chitulinux-run sets them)

Each choice is a file in CHITULINUX_HOME; no file is the default. chitulinux-run applies them when CHITUBOX
starts. Exits with 2 without GTK 3; chitulinux-run then opens winecfg.
"""
import os
import socket
import subprocess
import sys

os.environ.setdefault('GDK_BACKEND', 'x11')

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import GLib, Gtk
except (ImportError, ValueError):
    sys.exit(2)

DATA = os.environ.get('CHITULINUX_HOME') or os.path.expanduser('~/.local/share/chitulinux')
PREFIX = os.environ.get('WINEPREFIX', os.path.join(DATA, 'prefix'))
RUN = os.environ.get('CHITULINUX_RUN', '')
TOOLS = os.path.dirname(os.path.abspath(__file__))


def read(name):
    try:
        with open(os.path.join(DATA, name)) as f:
            return f.read().strip()
    except OSError:
        return ''


def write(name, value):
    """VALUE in the file NAME; None removes it (the default)."""
    path = os.path.join(DATA, name)
    if value is None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    os.makedirs(DATA, exist_ok=True)
    with open(path + '.tmp', 'w') as f:
        f.write(value + '\n')
    os.replace(path + '.tmp', path)


def desktop_percent():
    try:
        dpi = int(subprocess.run([os.path.join(TOOLS, 'desktop-dpi')], capture_output=True, text=True,
                                 timeout=5).stdout.strip())
        return round(dpi * 100 / 96)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def wine_running():
    """Whether a wineserver has the prefix open."""
    try:
        st = os.stat(PREFIX)
    except OSError:
        return False
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect('/tmp/.wine-%d/server-%x-%x/socket' % (os.getuid(), st.st_dev, st.st_ino))
        return True
    except OSError:
        return False
    finally:
        s.close()


def gpu_vendors():
    """The PCI vendor IDs of the GPUs, e.g. {'0x8086', '0x10de'}."""
    found = set()
    try:
        cards = os.listdir('/sys/class/drm')
    except OSError:
        return found
    for card in cards:
        if card.startswith('card') and '-' not in card:
            try:
                with open('/sys/class/drm/%s/device/vendor' % card) as f:
                    found.add(f.read().strip())
            except OSError:
                pass
    return found


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title='CHITUBOX settings')
        self.set_border_width(18)
        self.set_resizable(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect('destroy', self.on_destroy)
        self.loading = True
        self.children = []

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(box)

        # --- scale
        box.pack_start(self.heading('Size of text and icons'), False, False, 0)
        desk = desktop_percent()
        self.follow = Gtk.RadioButton.new_with_label(
            None, 'Follow the desktop' + (' (now %d%%)' % desk if desk else ''))
        box.pack_start(self.follow, False, False, 0)
        row = Gtk.Box(spacing=8)
        self.fixed = Gtk.RadioButton.new_with_label_from_widget(self.follow, 'Fixed:')
        self.percent = Gtk.SpinButton.new_with_range(50, 400, 25)
        self.percent.set_numeric(True)
        row.pack_start(self.fixed, False, False, 0)
        row.pack_start(self.percent, False, False, 0)
        row.pack_start(Gtk.Label(label='%'), False, False, 0)
        box.pack_start(row, False, False, 0)
        scale = read('scale')
        self.percent.set_value(int(scale) if scale.isdigit() else (desk or 100))
        (self.fixed if scale.isdigit() else self.follow).set_active(True)
        self.percent.set_sensitive(self.fixed.get_active())
        if os.environ.get('CHITUBOX_SCALE'):
            box.pack_start(self.small('CHITUBOX_SCALE=%s is set and comes first.'
                                      % os.environ['CHITUBOX_SCALE']), False, False, 0)
        self.fixed.connect('toggled', self.on_scale)
        self.percent.connect('value-changed', self.on_scale)

        # --- graphics: only a choice on a computer with more than one GPU
        vendors = gpu_vendors()
        if len(vendors & {'0x8086', '0x10de', '0x1002'}) > 1:
            heading = self.heading('Graphics')
            heading.set_margin_top(6)
            box.pack_start(heading, False, False, 0)
            grid = Gtk.Grid(column_spacing=12, row_spacing=6)
            items = [('', 'Automatic (DXVK chooses)')]
            if '0x8086' in vendors:
                items.append(('intel', 'Integrated GPU (Intel)'))
            if '0x10de' in vendors:
                items.append(('nvidia', 'NVIDIA GPU'))
            grid.attach(Gtk.Label(label='Draw on', xalign=0), 0, 0, 1, 1)
            self.gpu = Gtk.ComboBoxText()
            for key, label in items:
                self.gpu.append(key, label)
            current = read('gpu')
            self.gpu.set_active_id(current if current in [k for k, _ in items] else '')
            self.gpu.connect('changed', lambda c: self.save('gpu', c.get_active_id() or None))
            grid.attach(self.gpu, 1, 0, 1, 1)
            box.pack_start(grid, False, False, 0)
            box.pack_start(self.small('Try the other GPU when the 3D view flickers or goes black.'), False, False, 0)

        self.status = self.small('Changes are used from the next start of CHITUBOX.')
        box.pack_start(self.status, False, False, 10)

        buttons = Gtk.Box(spacing=8)
        for label, command, tip in (
                ('Wine configuration...', 'winecfg', 'Wine\'s own settings (winecfg). A scale set there '
                                                     'is replaced by the one set here.'),
                ('Registry editor...', 'regedit', None)):
            b = Gtk.Button(label=label)
            if tip:
                b.set_tooltip_text(tip)
            b.connect('clicked', self.on_tool, command)
            b.set_sensitive(bool(RUN))
            buttons.pack_start(b, False, False, 0)
        close = Gtk.Button(label='Close')
        close.connect('clicked', lambda b: self.destroy())
        buttons.pack_end(close, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.loading = False

    @staticmethod
    def heading(text):
        label = Gtk.Label(xalign=0)
        label.set_markup('<b>%s</b>' % text)
        return label

    @staticmethod
    def small(markup):
        label = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        label.set_markup('<small>%s</small>' % markup)
        return label

    def save(self, name, value):
        if self.loading:
            return
        try:
            write(name, value)
        except OSError as e:
            self.status.set_markup('<small>Saving failed: %s</small>' % GLib.markup_escape_text(str(e)))
            return
        self.status.set_markup('<small>Saved. %s</small>' % (
            'Close CHITUBOX and start it again to use it.' if wine_running()
            else 'Used from the next start of CHITUBOX.'))

    def on_scale(self, *args):
        self.percent.set_sensitive(self.fixed.get_active())
        self.save('scale', str(self.percent.get_value_as_int()) if self.fixed.get_active() else None)

    def on_tool(self, button, command):
        self.children.append(subprocess.Popen([RUN, command], stdin=subprocess.DEVNULL))

    def on_destroy(self, *args):
        # the AppImage stays mounted while this runs: wait for winecfg or regedit
        self.hide()
        for child in self.children:
            child.wait()
        Gtk.main_quit()


def main():
    Window().show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
