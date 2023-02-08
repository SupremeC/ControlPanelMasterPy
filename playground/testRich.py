"""
Demonstrates a Rich "application" using the Layout and Live classes.
"""
from datetime import datetime

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

console = Console()

def make_layout() -> Layout:
    """Define the layout."""
    layout = Layout(name="root")

    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=7),
    )
    layout["main"].split_row(
        Layout(name="side"),
        Layout(name="body", ratio=2, minimum_size=60),
    )
    layout["side"].split(Layout(name="box1"), Layout(name="box2"))
    return layout


class Header:
    """Display header with clock."""

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="right")
        grid.add_row(
            "[b]Rich[/b] Layout application",
            datetime.now().ctime().replace(":", "[blink]:[/]"),
        )
        return Panel(grid, style="white on blue")


layout = make_layout()
layout["header"].update(Header())
layout["body"].update("hej")
layout["box2"].update(Panel("box2:Hej", border_style="green"))
layout["box1"].update(Panel(layout.tree, border_style="red"))
layout["footer"].update("footer")


from time import sleep

from rich.live import Live

"""with Live(layout, refresh_per_second=10, screen=True):
    while not overall_progress.finished:
        sleep(0.5)
        for job in job_progress.tasks:

            if not job.finished:
                job_progress.advance(job.id)

        completed = sum(task.completed for task in job_progress.tasks)
        overall_progress.update(overall_task, completed=completed)   """ 
