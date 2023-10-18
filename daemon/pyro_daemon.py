"""
    Pyro:

    Allows communication between applications over ethernet.
    By default only calls from localhost are allowed.
"""


import threading
import pathlib
import logging
from Pyro5.api import Daemon, register_class_to_dict, register_dict_to_class
from daemon.packet import Packet
import daemon.global_variables


logger = logging.getLogger("daemon.ctrlPanel")


class PyroDaemon(threading.Thread):
    """runs Pyro in its own thread"""

    pyro_daemon: Daemon = None
    uri: str = None
    owner = None
    started: threading.Event = None
    uri_file: str = None

    def __init__(self, owner):
        threading.Thread.__init__(self)
        self.uri = None
        self.owner = owner
        self.started = threading.Event()
        register_dict_to_class("pyro-custom-Packet", Packet.packet_dict_to_class)
        register_class_to_dict(Packet, Packet.packet_class_to_dict)

    def run(self) -> None:
        """Start Pyro daemon"""
        self.pyro_daemon = Daemon()
        self.uri = self.pyro_daemon.register(self.owner, "pyro_cpdaemon")
        self.started.set()
        self.pyro_daemon.requestLoop()

    def stop(self) -> None:
        """Shutdown Pyro daemon"""
        self.pyro_daemon.shutdown()
        self.pyro_daemon.close()

    def write_uri_file(self) -> None:
        """Writes PyroDaemon uri to file
        so that other apps can read it"""
        file = PyroDaemon.get_path_urifile()
        logger.debug("writing uri to: %s", file.absolute())
        with file.open("w", -1, "utf-8") as filehandle:
            filehandle.write(str(self.uri))
        logger.info("PyroDaemon started on URI: %s", self.uri)
        logger.info("URI written to: %s", file.absolute())

    @staticmethod
    def get_path_urifile() -> pathlib.Path:
        """Absolute path to file containing Pyro uri"""
        source = pathlib.Path(daemon.global_variables.root_path)
        file = source.joinpath("pyro_uri.text").absolute()
        return file

    @staticmethod
    def get_uri_fromfile() -> str:
        """Read uri from text file"""
        return PyroDaemon.get_path_urifile().read_text(encoding="utf-8")
