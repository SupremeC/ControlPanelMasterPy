"""various bash commands. """
import io
import subprocess
from typing import List
from typing_extensions import deprecated


class BashScripts:
    """various bash commands."""
    @staticmethod
    def tail(filename: str, no_of_lines: int=10, offset: int=0) -> List[str]:
        """Output the last part of a file

        Args:
            filename (str): The file to read
            no_of_lines (int, optional): No of lines to read. Defaults to 10.
            offset (int, optional): Skip X no of lines. Defaults to 0.

        Returns:
            List<str>: The X last lines of file
        """
        lines = []
        proc = subprocess.Popen(
            ['tail', '-n', str(no_of_lines + offset), filename],
            stdout=subprocess.PIPE)
        for line in io.TextIOWrapper(proc.stdout, encoding="utf-8"):
            lines.append(line)
        del lines[:offset]
        return lines


    @staticmethod
    @deprecated("Use controlPanelClass instead to set volume.")
    def set_mastervolume(volume_in_percent: int) ->None:
        """
        @deprecated
        Set master volume on system.

        Args:
            volume_in_percent (int): Integer volume level. 0-100.
        """
        volume_in_percent = BashScripts.clamp(volume_in_percent, 0, 100)
        command = ["amixer", "sset", "Master", f"{volume_in_percent}%"]
        with subprocess.Popen(command) as _:
            pass


    @staticmethod
    def clamp(val: int, minval: int, maxval: int) -> int:
        """Clamps input into the range [ minval, maxval ].

        Args:
            val (int): The input
            minval (int):  lower-bound of the range to be clamped to
            maxval (int): upper-bound of the range to be clamped to

        Returns:
            int: result of clamp op.
        """
        if val < minval:
            return minval
        if val > maxval:
            return maxval
        return val
