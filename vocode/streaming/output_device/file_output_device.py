import asyncio
import wave
from asyncio import Queue

import numpy as np

from vocode.streaming.output_device.rate_limit_interruptions_output_device import (
    RateLimitInterruptionsOutputDevice,
)

from vocode.streaming.models.audio import AudioEncoding
from vocode.streaming.utils.worker import ThreadAsyncWorker


class FileWriterWorker(ThreadAsyncWorker):
    def __init__(self, input_queue: Queue, wave) -> None:
        super().__init__(input_queue)
        self.wav = wave

    def _run_loop(self):
        while True:
            try:
                block = self.input_janus_queue.sync_q.get()
                self.wav.writeframes(block)
            except asyncio.CancelledError:
                return

    def terminate(self):
        super().terminate()
        self.wav.close()


class FileOutputDevice(RateLimitInterruptionsOutputDevice):
    DEFAULT_SAMPLING_RATE = 44100

    def __init__(
        self,
        file_path: str,
        sampling_rate: int = DEFAULT_SAMPLING_RATE,
        audio_encoding: AudioEncoding = AudioEncoding.LINEAR16,
    ):
        super().__init__(sampling_rate, audio_encoding)
        self.blocksize = self.sampling_rate
        self.queue: Queue[np.ndarray] = Queue()

        wav = wave.open(file_path, "wb")
        wav.setnchannels(1)  # Mono channel
        wav.setsampwidth(2)  # 16-bit samples
        wav.setframerate(self.sampling_rate)
        self.wav = wav

        self.thread_worker = FileWriterWorker(self.queue, wav)

    def start(self) -> asyncio.Task:
        self.thread_worker.start()
        return super().start()

    async def play(self, chunk: bytes):
        # TODO: just dispatch out into a thread to write to the file per block, doesn't need a worker
        chunk_arr = np.frombuffer(chunk, dtype=np.int16)
        for i in range(0, chunk_arr.shape[0], self.blocksize):
            block = np.zeros(self.blocksize, dtype=np.int16)
            size = min(self.blocksize, chunk_arr.shape[0] - i)
            block[:size] = chunk_arr[i : i + size]
            self.queue.put_nowait(block)

    def terminate(self):
        self.thread_worker.terminate()
        super().terminate()
