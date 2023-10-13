"""View"""
import sys
import urwid as u
import daemon.packet
from client.static_content import StaticContent

sys.path.append("..")



# TOODO  custom signals (connects pyro code to Widget)
# Should Overview be class or custom widget (if widget I dont need a build() method)

class OverView(object):
    """View"""
    loopref: u.MainLoop
    rwalker: u.SimpleListWalker
    swalker: u.SimpleListWalker
    rlistbox: u.ListBox
    slistbox: u.ListBox
    statuslistbox: u.ListBox
    statuswalker: u.SimpleListWalker

    def __init__(self, cp_daemon):
        self.title = "OverView"
        self.cp_remote_daemon = cp_daemon


    def set_loopref(self, ref) -> None:
        """loop reference"""
        self.loopref = ref


    def del_loopref(self) -> None:
        """Delete loop reference. Because memory cleanup"""
        self.loopref = None


    def update(self):
        """Do shit here to update values in View"""
        #idx = self.rlistbox.focus_position
        #am = self.rwalker[idx].original_widget
        #am.set_label(am.get_label()[::-1])


    def packetpress(self, _: u.Button, packet: daemon.packet.Packet):
        """Handles event when a packet is clicked"""
        #idx = self.rlistbox.focus_position
        #am = self.rwalker[idx].original_widget
        #am.set_label("xx:"+packet.as_human_friendly_str())
        StaticContent.dialog_ok(
            self, self.loopref,
            "PacketInfo", None, 
            StaticContent.packet_to_urwid(packet)
            )

    def build_received_packets(self):
        """urwid box"""
        self.rwalker = u.SimpleFocusListWalker([])
        self.rlistbox = u.ListBox(self.rwalker)
        listbox = u.AttrMap(self.rlistbox, "listbox")
        listbox = u.LineBox(listbox, "Last Received Packets")
        remote_data = self.cp_remote_daemon.get_latest_rpackets()
        for p in remote_data:
            self.rwalker.append(
                u.AttrMap(u.Button(p.as_human_friendly_str(),
                                   self.packetpress, p), "listbox", "reveal focus"))
        return listbox


    def build_sent_packets(self):
        """urwid box"""
        self.swalker = u.SimpleFocusListWalker([])
        self.slistbox = u.ListBox(self.swalker)
        listbox = u.AttrMap(self.slistbox, "listbox")
        listbox = u.LineBox(listbox, "Last Sent Packets")
        # for i in range(6):
        #     p = daemon.packet.Packet()
        #     p.target = 42 - i
        #     p.val = 1
        #     p.hw_event = random.choice(list(daemon.packet.HWEvent))
        #     p.error = (daemon.packet.ErrorType.INVALIDTARGET
        #                if p.target == 42 else daemon.packet.ErrorType.NONE_)
        #     p.created = datetime.now() - timedelta(hours=i, minutes=50-(i*3))
        remote_data = self.cp_remote_daemon.get_latest_spackets()
        for p in remote_data:
            self.swalker.append(
                u.AttrMap(u.Button(p.as_human_friendly_str(),
                                   self.packetpress, p), "listbox", "reveal focus"))
        return listbox


    def build_status_box(self):
        """urwid box"""
        self.statuswalker = u.SimpleFocusListWalker([])
        self.statuslistbox = u.ListBox(self.statuswalker)
        listbox = u.AttrMap(self.statuslistbox, "listbox")
        listbox = u.LineBox(listbox, "Control Panel Daemon Status")
        remote_data = self.cp_remote_daemon.get_status()
        # stuff: dict = {}
        # stuff.update({"ReceiveQueue length": "21"})
        # stuff.update({"SendQueue length": "0"})
        # stuff.update({"LastIncomingHello": "21"})
        # stuff.update({"Volume": "78"})
        # stuff.update({"mainSwitch": "off"})
        # stuff.update({"Ctrl leds": "off"})
        # stuff.update({"Demo theme": "0"})
        # stuff.update({"Recording": "True"})
        for title, value in remote_data.items():
            self.statuswalker.append(
                u.AttrMap(u.Button(str(title).ljust(25,' ') + str(value), None, None),
                          "listbox", "reveal focus"))
        return listbox


    def build(self):
        """Build widgets in this View

        Returns:
            u.Frame: Frame containing View widgets
        """
        left = self.build_received_packets()
        right = self.build_sent_packets()
        toprow = u.Columns([left, right])
        toprow = u.BoxAdapter(toprow, 10)

        allwidgets = []
        allwidgets.append(toprow)
        allwidgets.append(u.BoxAdapter(self.build_status_box(), 10))
        body = u.Pile(allwidgets)
        # body = u.BoxAdapter(self.get_last_received_packets(), 10)
        fill = u.Filler(body, valign='top')
        return u.AttrMap(
            u.Frame(body=fill, header=StaticContent.header(),
                    footer=StaticContent.footer()), 'bg')
