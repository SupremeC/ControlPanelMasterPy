import sys
sys.path.append("..")

from datetime import datetime, timedelta
import random
import urwid as u
import daemon.packet
from staticContent import StaticContent



# TODO  custom signals (connects pyro code to Widget)
# Should Overview be class or custom widget (if widget I dont need a build() method)

class OverView(object):
    loopref: u.MainLoop
    rwalker: u.SimpleListWalker
    swalker: u.SimpleListWalker
    rlistbox: u.ListBox
    slistbox: u.ListBox

    def __init__(self):
        self.title = "OverView"
        pass

    def set_loopref(self, ref) -> None:
        self.loopref = ref

    def del_loopref(self) -> None:
        self.loopref = None

    def update(self):
        #idx = self.rlistbox.focus_position
        #am = self.rwalker[idx].original_widget
        #am.set_label(am.get_label()[::-1])
        pass

    def packetpress(self, button: u.Button, packet: daemon.packet.Packet):
        #idx = self.rlistbox.focus_position
        #am = self.rwalker[idx].original_widget
        #am.set_label("xx:"+packet.as_human_friendly_str())
        StaticContent.dialog_ok(
            self, self.loopref, 
            "PacketInfo", None, 
            StaticContent.packet_to_urwid(packet)
            )


    def get_last_received_packets(self):
        self.rwalker = u.SimpleFocusListWalker([])
        self.rlistbox = u.ListBox(self.rwalker)
        listbox = u.AttrMap(self.rlistbox, "listbox")
        listbox = u.LineBox(listbox, "ReceivedPackets")
        for i in range(6):
            p = daemon.packet.Packet()
            p.target = 42 - i
            p.val = 1
            p.hwEvent = random.choice(list(daemon.packet.HWEvent))
            p.error = daemon.packet.ErrorType.INVALIDTARGET if p.target == 42 else daemon.packet.ErrorType.NONE_
            p._created = datetime.now() - timedelta(hours=i, minutes=50-(i*3))
            self.rwalker.append(u.AttrMap(u.Button(p.as_human_friendly_str(), self.packetpress, p), "listbox", "reveal focus"))
        return listbox

    def get_last_sent_packets(self):
        self.swalker = u.SimpleFocusListWalker([])
        self.slistbox = u.ListBox(self.swalker)
        listbox = u.AttrMap(self.slistbox, "listbox")
        listbox = u.LineBox(listbox, "Sent Packets")
        for i in range(6):
            p = daemon.packet.Packet()
            p.target = 42 - i
            p.val = 1
            p.hwEvent = daemon.packet.HWEvent.BOOTMEGA
            p.error = daemon.packet.ErrorType.INVALIDTARGET if p.target == 42 else daemon.packet.ErrorType.NONE_
            p._created = datetime.now() - timedelta(hours=i, minutes=50-(i*3))
            self.swalker.append(u.AttrMap(u.Button(p.as_human_friendly_str(), self.packetpress, p), "listbox", "reveal focus"))
        return listbox

    def build(self):
        left = self.get_last_received_packets()
        right = self.get_last_sent_packets()
        body = u.Columns([left, right])
        body = u.BoxAdapter(body, 10)
        # body = u.BoxAdapter(self.get_last_received_packets(), 10)
        fill = u.Filler(body, valign='top')
        return u.AttrMap(
            u.Frame(body=fill, header=StaticContent.header(), 
                    footer=StaticContent.footer()), 'bg')

