import sys
import urwid as u
import daemon.packet

sys.path.append("..")


class StaticContent:
    """helper methods"""

    @staticmethod
    def header():
        """header"""
        header_widgets = []
        for w in [
            "[F1]Overview",
            "[F2]FakeIncomingPacket",
            "[F3] SendCommand",
            "[F4]Logs",
        ]:
            header_widgets.append(u.AttrMap(u.Text(w), "topheader"))
        return u.Columns(header_widgets)

    @staticmethod
    def footer():
        """footer"""
        return u.AttrMap(u.Text(" Q to exit"), "footer")

    staticmethod

    def remove_overlays(loopref) -> None:
        """
        Remove ALL urwid.Overlay objects which are currently covering the base
        widget.
        """
        while True:
            try:
                loopref.widget = loopref.widget[0]
            except:
                break

    @staticmethod
    def cute_button(label, callback=None, data=None):
        """
        Urwid's default buttons are shit, and they have ugly borders.
        This function returns buttons that are a bit easier to love.
        """
        button = u.Button("", callback, data)
        super(u.Button, button).__init__(u.SelectableIcon(label))
        return button

    @staticmethod
    def packet_to_urwid(packet: daemon.packet.Packet):
        """Prettify Packet as Urwid text widgets"""
        texts = []
        texts.append(f"Created: {packet.created}")
        texts.append(f"HWEvent: {packet.hw_event.name}")
        texts.append(f"Target : {packet.target}")
        texts.append(f"Val: {packet.val}")
        texts.append(f"Error: {packet.error.name}")

        w = []
        for e in texts:
            w.append(u.AttrMap(u.Text(e), "style_TODO"))
        return w

    @staticmethod
    def dialog_yesno(classref, loopref, title, message, callback_yes, callback_no):
        """
        Prompts the user to confirm deletion of an item.
        This can delete either a thread or a post.
        """
        buttons = [
            u.Text(("bold", message)),
            u.Divider(),
            StaticContent.cute_button(
                ("10", ">> Yes"),
                lambda _: [StaticContent.remove_overlays(loopref), classref.update()],
            ),
            StaticContent.cute_button(
                ("30", "<< No"),
                lambda _: [StaticContent.remove_overlays(loopref), classref.update()],
            ),
        ]
        popup = OptionsMenu(u.ListBox(u.SimpleFocusListWalker(buttons)), title)
        popup.loopref = loopref

        loopref.widget = u.Overlay(
            popup,
            loopref.widget,
            align=("relative", 50),
            valign=("relative", 50),
            width=30,
            height=10,
        )

    @staticmethod
    def dialog_ok(classref, loopref, title, message=None, messagewidgets=None):
        """
        Prompts the user to confirm deletion of an item.
        This can delete either a thread or a post.
        """
        buttons = []
        if isinstance(message, str) and message is not None:
            buttons.append(u.Text(("bold", message)))
        elif isinstance(messagewidgets, list):
            buttons += messagewidgets
        buttons.append(u.Divider())
        buttons.append(
            StaticContent.cute_button(
                ("10", ">> OK"),
                lambda _: [StaticContent.remove_overlays(loopref), classref.update()],
            )
        )
        popup = OptionsMenu(u.ListBox(u.SimpleFocusListWalker(buttons)), title)
        popup.loopref = loopref

        loopref.widget = u.Overlay(
            popup,
            loopref.widget,
            align=("relative", 50),
            valign=("relative", 50),
            width=40,
            height=9,
        )


class OptionsMenu(u.LineBox):
    """Extends base class to handle keypress for Overlay dialogs"""

    loopref = None

    def keypress(self, size, key):
        """handle keypress events"""
        keyl = key.lower()
        if keyl in ("esc", "ctrl g"):
            self.loopref.widget = self.loopref.widget[0]
        # try to let the base class handle the key, if not, we'll take over
        elif not super(OptionsMenu, self).keypress(size, key):
            return

        elif key in ("ctrl n", "j", "n"):
            return self.keypress(size, "down")

        elif key in ("ctrl p", "k", "p"):
            return self.keypress(size, "up")

        elif keyl in ("left", "h", "q"):
            self.loopref.widget = self.loopref.widget[0]

        elif keyl in ("right", "l"):
            return self.keypress(size, "enter")
