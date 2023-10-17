"""View"""
import urwid as u
from client.static_content import StaticContent
from client.bashscripts import BashScripts
from pathlib import Path
import daemon.global_variables


class SelectableText(u.Text):
    """
    dummy class. Only purpose is to make the listbox content scrollable
    The 'magic' is setting '_selectable = True'
    """

    _selectable = True

    def keypress(self, _, key):
        """def keypress(self, size, key):"""
        return key


class LogView:
    """View"""

    loopref: u.MainLoop
    walker: u.SimpleListWalker
    listbox: u.ListBox

    def __init__(self, cp_daemon):
        self.title = "LogView"
        self.cp_daemon = cp_daemon

    def set_loopref(self, ref) -> None:
        """loop reference"""
        self.loopref = ref

    def del_loopref(self) -> None:
        """Delete loop reference. Because memory cleanup"""
        self.loopref = None

    def update(self):
        """Do shit here to update values in View"""
        # now = datetime.now()
        # self.obj_text.set_text(self.file_content + str(now.second))
        # self.obj_text.set_text(self.get_text_from_logfile())

    def get_text_from_logfile(self, nr_of_lines) -> str:
        "Read logfile and return the last lines (tail)"
        approot = Path(daemon.global_variables.root_path)
        logfile = approot.joinpath("logs.log")
        return BashScripts.tail(logfile, nr_of_lines, 0)

    def build(self):
        """Build widgets in this View

        Returns:
            u.Frame: Frame containing View widgets
        """
        lines_to_read = 80
        self.walker = u.SimpleFocusListWalker([])
        self.listbox = u.ListBox(self.walker)
        listbox = u.AttrMap(self.listbox, "listbox")
        listbox = u.LineBox(listbox, f"Log file (-tail {lines_to_read})")
        textlines = self.get_text_from_logfile(lines_to_read)
        for line in textlines:
            self.walker.append(
                u.AttrMap(
                    SelectableText(line.strip(), wrap="clip"), "listbox", "reveal focus"
                )
            )
        self.listbox.set_focus(self.walker.positions(True)[0])

        # ===============
        listbox = u.Columns([listbox])
        # toprow = u.BoxAdapter(toprow, 10)
        # listbox = u.Filler(listbox)
        return u.AttrMap(
            u.Frame(
                body=listbox,
                header=StaticContent.header(),
                footer=StaticContent.footer(),
            ),
            "bg",
        )
