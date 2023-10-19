"""GUI CLient"""
import urwid as u
from Pyro5.api import Proxy, register_class_to_dict, register_dict_to_class
from client.overview import OverView
from client.logview import LogView
from daemon.pyro_daemon import PyroDaemon
from daemon.packet import Packet


try:
    PYRO_DAEMON_URI = PyroDaemon.get_uri_fromfile()
    cp_daemon = Proxy(PYRO_DAEMON_URI)
    register_dict_to_class("pyro-custom-Packet", Packet.packet_dict_to_class)
    register_class_to_dict(Packet, Packet.packet_class_to_dict)
except FileNotFoundError as e:
    print(f"Could not read uri_file.{e.filename}")
    raise


views = {"overview": OverView(cp_daemon), "logview": LogView(cp_daemon)}


class App:
    """GUI App"""

    current_view: str

    def __init__(self):
        self.palette = {
            ("bg", "light gray", "black"),
            ("normalText", "light gray", "black"),
            ("topheader", "", "", "", "#F5F5F5, bold", "#006400"),
            ("footer", "white, bold", "dark red"),
            ("listbox", "", "", "", "#F5FFFA", "black"),
            # ('reveal focus', 'yellow', 'dark cyan', 'standout'),
            ("reveal focus", "", "", "", "#2F4F4F, bold", "#48D1CC"),
            ("button", "light red", "default"),
        }

        # col_rows = u.raw_display.Screen().get_cols_rows()
        # h = col_rows[0] - 2
        self.current_view = "overview"
        frame = views[self.current_view].build()
        self.loop = u.MainLoop(
            frame, self.palette, unhandled_input=self.unhandled_input
        )
        self.loop.screen.set_terminal_properties(colors=256)
        self.loop.set_alarm_in(2, self.refresh)
        views[self.current_view].set_loopref(self.loop)

    def unhandled_input(self, key):
        """Handle all events that no other widget wants to handle"""
        if key in ("f1", "1"):
            self.set_view("overview")
        if key in ("f2", "2"):
            self.set_view("logview")
        if key in ("q", "Q", "esc"):
            raise u.ExitMainLoop()

    def set_view(self, view_name: str):
        """Set which View that is visible"""

        # I was afraid of memory leaks because the View held a reference to <loop>.
        # That is why I delete it. However: I changed the design so probably not needed
        # anymore and can be removed.
        views[self.current_view].del_loopref()

        # set View
        self.current_view = view_name
        self.loop.widget = views[view_name].build()
        views[view_name].set_loopref(self.loop)

    def start(self):
        """Start GUI"""
        self.loop.screen.set_terminal_properties(colors=256)
        self.loop.run()

    def refresh(self, _loop, _data):
        """Refresh current view"""
        views[self.current_view].update()
        _loop.set_alarm_in(2, self.refresh)

    def wipe_screen(self, *_):
        """
        A crude hack to repaint the whole screen. I didnt immediately
        see anything to acheive this in the MainLoop methods so this
        will do, I suppose.
        """
        self.loop.stop()
        self.loop.start()


if __name__ == "__main__":
    app = App()
    app.start()
