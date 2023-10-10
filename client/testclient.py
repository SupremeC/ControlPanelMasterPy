import urwid as u
from staticContent import StaticContent
from overview import OverView
from logview import LogView



views = {
    "overview": OverView(), 
    "logview": LogView()
}


class App(object):
    current_view: str

    def __init__(self):
        self.palette = {
            ("bg",               "light gray",  "black"),
            ("normalText",          "light gray",       "black"),
            ("topheader",        "", "", "", "#F5F5F5, bold", "#006400"),
            ("footer",           "white, bold", "dark red"),
            ("listbox", "light gray", "black"),
            ('reveal focus', 'yellow', 'dark cyan', 'standout'),
            ("button", "light red", "default")
        }   
        
        col_rows = u.raw_display.Screen().get_cols_rows()
        h = col_rows[0] - 2
                
        # test_text = u.AttrMap(u.Text("Hej David"), "country")
        # self.main_text = u.Text("Huvudtext")
        # self.main_content = u.Filler(u.AttrMap(self.main_text, "normalText"), valign='top')

        # main_box = u.Columns([('weight', 70, main_content)])
        # f2 = u.Filler(main_box, valign='top')
        # frame = u.AttrMap(u.Frame(body=self.main_content, header=StaticContent.header(), footer=StaticContent.footer()), 'bg')
        self.current_view = "overview"
        frame = views[self.current_view].build()
        self.loop = u.MainLoop(frame, self.palette, unhandled_input=self.unhandled_input)
        self.loop.set_alarm_in(2, self.refresh)
        views[self.current_view].set_loopref(self.loop)


    def unhandled_input(self, key):
        if key in ('f1','1'):
            self.set_view("overview")
        if key in ('f2','2'):
            self.set_view("logview")
        if key in ('q','Q','esc'):
            raise u.ExitMainLoop()
        
    def set_view(self, view_name:str):
        views[self.current_view].del_loopref()
        self.current_view = view_name
        self.loop.widget = views[view_name].build()
        views[view_name].set_loopref(self.loop)
        
    def start(self):
        self.loop.screen.set_terminal_properties(colors=256)
        self.loop.run()

    def refresh(self, _loop, _data):
        views[self.current_view].update()
        _loop.set_alarm_in(2, self.refresh)

    def wipe_screen(*_):
        """
        A crude hack to repaint the whole screen. I didnt immediately
        see anything to acheive this in the MainLoop methods so this
        will do, I suppose.
        """
        app.loop.stop()
        app.loop.start()

if __name__ == '__main__':

    app = App()
    app.start()