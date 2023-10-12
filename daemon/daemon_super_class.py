#!/usr/bin/env python

"""Generic linux daemon base class for python 3.x."""

import sys
import os
import os.path
import time
import signal


class DaemonSC:
    """A generic daemon class.
    Usage: subclass the daemon class and override the run() method."""

    def __init__(self, pidfile):
        self.pidfile = pidfile
        self.kill_now = False
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def daemonize(self):
        """Deamonize class. UNIX double fork mechanism."""
        try:
            pid = os.fork()
            if pid > 0:
                # exit first parent
                sys.exit(0)
        except OSError as error:
            sys.stderr.write(f'fork #1 failed: {error}\n')
            sys.exit(1)
        DaemonSC.print_process_info(pid)

        # decouple from parent environment
        os.chdir('/')
        os.setsid()
        os.umask(0)

        # do second fork
        try:
            pid = os.fork()
            if pid > 0:
                # exit from second parent
                sys.exit(0)
        except OSError as error:
            sys.stderr.write(f'fork #2 failed: {error}\n')
            sys.exit(1)
        DaemonSC.print_process_info(pid)
        #atexit.register(self.delpid)

        # write pidfile
        try:
            f = open(self.pidfile, 'w+', encoding="utf-8")
            f.write(str(os.getpid()) + '\n')
            f.flush()
            f.close()
            if not os.path.isfile(self.pidfile):
                sys.stderr.write('pidfile missing. \n')
        except Exception as error:
            sys.stderr.write(f'write pidfile failed: {error}\n')
            raise

        # try:
        #     pid = str(os.getpid())
        #     with open(self.pidfile, 'w+') as f:
        #         f.write(str(pid) + '\n')
        #     sys.stdout.write('wrote pidfile: {0}\n'.format(self.pidfile))
        # except Exception as error:
        #     sys.stderr.write('write pidfile failed: {0}\n'.format(err))

        # redirect standard file descriptors
        sys.stdout.flush()
        sys.stderr.flush()
        si = open(os.devnull, 'r')
        so = open(os.devnull, 'a+')
        se = open(os.devnull, 'a+')

        os.dup2(si.fileno(), sys.stdin.fileno())
        os.dup2(so.fileno(), sys.stdout.fileno())
        os.dup2(se.fileno(), sys.stderr.fileno())

    @staticmethod
    def print_process_info(p_pid: int):
        """pid greater than 0 represents the parent process"""
        if p_pid > 0 :
            print("I am parent process:")
            print("Process ID:", os.getpid())
            print("Child's process ID:", p_pid)

        # pid equal to 0 represents the created child process
        else :
            print("\nI am child process:")
            print("Process ID:", os.getpid())
            print("Parent's process ID:", os.getppid())

    def delpid(self):
        """Deletes PID file"""
        os.remove(self.pidfile)

    def start(self):
        """Start the daemon."""
        # Check for a pidfile to see if the daemon already runs
        try:
            message = "trying to read pidfile {0}\n"
            sys.stdout.write(message.format(self.pidfile))
            with open(self.pidfile, 'r', encoding="utf-8") as pf:
                pid = int(pf.read().strip())
        except IOError:
            pid = None

        if pid:
            message = "pidfile {0} already exist. " + \
                    "Daemon already running?\n"
            sys.stderr.write(message.format(self.pidfile))
            sys.exit(1)
        else:
            sys.stdout.write("pidfile do not exist. Good.\n")

        # Start the daemon
        self.daemonize()
        self.run()

    def stop(self):
        """Stop the daemon."""
        # Get the pid from the pidfile
        pid = 0
        try:
            if os.path.isfile(self.pidfile):
                pf = open(self.pidfile, 'r', encoding="utf-8")
                pid = int(pf.read().strip())
                pf.close()
        except Exception as error:
            sys.stderr.write(f'stop() reading pidfile failed: {error}\n')
        # try:
        #     with open(self.pidfile, 'r') as pf:
        #         pid = int(pf.read().strip())
        # except IOError as err:
        #     pid = None
        #     sys.stderr.write('stop() reading pidfile failed: {0}\n'.format(err))

        if not pid:
            message = "pidfile {0} does not exist. " + \
                    "Daemon not running?\n"
            sys.stderr.write(message.format(self.pidfile))
            #if os.path.exists(self.pidfile):
            #    os.remove(self.pidfile)
            return  # not an error in a restart

        # Try killing the daemon process
        try:
            while 1:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.1)
        except OSError as err:
            e = str(err.args)
            if e.find("No such process") > 0:
                if os.path.exists(self.pidfile):
                    os.remove(self.pidfile)
                print(str(err.args))

    def restart(self):
        """Restart the daemon."""
        self.stop()
        self.start()

    def run(self):
        """You should override this method when you subclass Daemon.
        It will be called after the process has been daemonized by
        start() or restart()."""

    def exit_gracefully(self, signum, _):
        """Cleans up and set Kill flag"""
        self.kill_now = True
        self.cleanup(signum, signal.Signals(signum).name)

    def cleanup(self, signum, signame):
        """You should override this method when you subclass Daemon.
        It will be called when 'stop()' is called"""
