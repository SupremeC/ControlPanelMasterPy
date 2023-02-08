#!/usr/bin/env python3
"""
There are 3 concurrent activities: GUI, audio callback, file-writing thread.

Neither the GUI nor the audio callback is supposed to block.
Blocking in any of the GUI functions could make the GUI "freeze", blocking in
the audio callback could lead to drop-outs in the recording.
Blocking the file-writing thread for some time is no problem, as long as the
recording can be stopped successfully when it is supposed to.

"""
import os
import queue
import tempfile
import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
import logging
import time

logger = logging.getLogger('daemon.rec')


class AudioRec():
    stream: sd.InputStream = None
    audio_q: queue.Queue
    recording: bool
    recordingstart: float
    previously_recording: bool
    thread: threading.Thread
    rec_filename: str
    __dir: str
    device_ID: int
    max_rec_time: int

    def __init__(self, dir:str):
        '''
        :param dir: The directory to save the recorded .wave file to
        '''
        self.recording = False
        self.previously_recording = False
        self.audio_q = queue.Queue()
        self.metering_q = queue.Queue(maxsize=1)
        self.peak = 0
        self.device_ID = 10 # default device
        max_rec_time = 30  # in seconds

        self.__dir = dir
        self.__create_dir(path = self.__dir)

    def rec(self) -> bool:
        '''starts recording in a new thread. The resulting file
        path can be found in <AudioRec.rec_filename>.
        Call 'stop()' before reading/altering/deleting file.
        30 seconds is the maximum length
        '''
        if self.recording:
            logger.warning("rec() was called but a recording is already running")
            return False
        
        self._create_stream(device=self.device_ID)
        self.recording = True
        self.recordingstart = time.time()
        filename = tempfile.mktemp(
            prefix='tmp_rec', suffix='.wav', dir=self.__dir)
        if self.audio_q.qsize() != 0:
            logger.warning('WARNING: req.Queue not empty!')
        self.thread = threading.Thread(
            target=self.file_writing_thread,
            kwargs=dict(
                file=filename,
                mode='x',
                samplerate=int(self.stream.samplerate),
                channels=self.stream.channels,
                q=self.audio_q,
            ), daemon=True
        )
        self.rec_filename = filename
        self.thread.start()  # NB: File creation might fail!  For brevity, we don't check for this.
        return True

    def stop(self, *args):
        '''Stops recording process. Might take a while (blocking)...'''
        self.stream.stop()
        self._wait_for_thread()
        self.recording = False

    def set_device(self, dev_id: int) -> None:
        '''Set the Device ID. Use list_hostapis() and list_devices()
        to find the ID'''
        self.device_ID = dev_id

    def list_hostapis() -> dict:
        hosts = {}
        for hostapi in sd.query_hostapis():
            print(str(i) + ": " + str(hostapi) + "\n")
            hosts[i] = str(hostapi)
            i = i + 1
        return hosts

    def list_devices(self, hostapi_id:int) -> dict:
        devices = {}
        hostapi = sd.query_hostapis(hostapi_id)
        device_ids = [
            idx
            for idx in hostapi['devices']
            if sd.query_devices(idx)['max_input_channels'] > 0]
        device_list = [
            sd.query_devices(idx)['name'] for idx in device_ids]

        for i in range(len(device_ids)):
            devices[i] = str(device_list[i])
        return devices

    def file_writing_thread(self, *, q, **soundfile_args):
        """Write data from queue to file until *None* is received."""
        # NB: If you want fine-grained control about the buffering of the file, you
        #     can use Python's open() function (with the "buffering" argument) and
        #     pass the resulting file object to sf.SoundFile().
        with sf.SoundFile(**soundfile_args) as f:
            while True:
                data = q.get()
                if data is None or  time.time() - self.recordingstart > self.max_rec_time:
                    self.recording = False
                    break
                f.write(data)
                
    def __create_dir(self, path:str) -> None:
        try:
            if not os.path.exists(path):
                os.makedirs(path)
        except Exception as e:
            logger.error(f"Failed to create folder{path}")
            logger.error(e)
            raise

    def _create_stream(self, device=None):
        if self.stream is not None:
            self.stream.close()
        self.stream = sd.InputStream(
            device=device, channels=1, callback=self._audio_callback)
        self.stream.start()

    def _audio_callback(self, indata, frames, time, status):
        """This is called (from a separate thread) for each audio block."""
        if status.input_overflow:
            # NB: This increment operation is not atomic, but this doesn't
            #     matter since no other thread is writing to the attribute.
            self.input_overflows += 1
        # NB: self.recording is accessed from different threads.
        #     This is safe because here we are only accessing it once (with a
        #     single bytecode instruction).
        if self.recording:
            self.audio_q.put(indata.copy())
            self.previously_recording = True
        else:
            if self.previously_recording:
                self.audio_q.put(None)
                self.previously_recording = False

    def _wait_for_thread(self):
        '''blocking'''
        self.thread.join()

    def __del__(self):
        self.stop()

