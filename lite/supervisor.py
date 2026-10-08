"""Keep Gmail transport current; never invent an event or directly book.

The runtime's durable cursor and transport lock are shared with push delivery.
Readiness is transport readiness, not proof of a working provider booking flow.
"""

import math
import threading
import time

from .runtime import classified


class TransportSupervisor:
    def __init__(self, runtime, poll_seconds=300, renew_seconds=86400, clock=time.monotonic):
        for value, minimum, maximum in ((poll_seconds, 60, 3600),
                                        (renew_seconds, 60, 86400)):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not minimum <= value <= maximum):
                raise ValueError("invalid_transport_interval")
        self.runtime = runtime
        self.poll_seconds, self.renew_seconds, self.clock = poll_seconds, renew_seconds, clock
        self._lock = threading.Lock()
        self._next = {"poll": 0, "renew": 0}
        self._success = {"poll": None, "renew": None}
        self._errors = {}
        self.stopped = threading.Event()

    def tick(self):
        # Called only by this supervisor's single worker. Runtime locks also
        # serialize requests against concurrent Pub/Sub handlers/processes.
        for name, interval, action in (
            ("renew", self.renew_seconds, self.runtime.renew_watch),
            ("poll", self.poll_seconds, self.runtime.poll_once),
        ):
            if self.stopped.is_set() or self.clock() < self._next[name]:
                continue
            try:
                action()
            except Exception as error:
                with self._lock:
                    self._errors[name] = classified(error, "transport_maintenance_failed")
                    self._next[name] = self.clock() + 60
            else:
                with self._lock:
                    self._success[name] = self.clock()
                    self._errors.pop(name, None)
                    self._next[name] = self.clock() + interval

    def readiness(self):
        with self._lock:
            now = self.clock()
            ready = not self._errors and not self.stopped.is_set()
            for name, interval in (("poll", self.poll_seconds), ("renew", self.renew_seconds)):
                stamp = self._success[name]
                ready = ready and stamp is not None and 0 <= now - stamp <= interval + 60
            return {"transport_ready": bool(ready),
                    "booking_readiness": "not_assessed",
                    "error_classes": sorted(set(self._errors.values()))}

    def run(self):
        while not self.stopped.is_set():
            self.tick()
            self.stopped.wait(1)
