import urwid as u
from datetime import datetime
from staticContent import StaticContent


# TODO  custom signals (connects pyro code to Widget)
# Should Overview be a class or a custom widget (if widget I dont need a build() method)

class LogView(object):
    loopref: u.MainLoop
    title: str
    obj_text: u.Text

    def __init__(self):
        self.title = "LogView"
        pass

    def set_loopref(self, ref) -> None:
        self.loopref = ref

    def del_loopref(self) -> None:
        self.loopref = None

    def update(self):
        now = datetime.now()
        self.obj_text.set_text(self.title + str(now.second))


    def build(self):
        self.obj_text = u.Text(self.title)
        body = u.Pile([self.obj_text])
        fill = u.Filler(body)
        return u.AttrMap(u.Frame(body=fill, header=StaticContent.header(), footer=StaticContent.footer()), 'bg')