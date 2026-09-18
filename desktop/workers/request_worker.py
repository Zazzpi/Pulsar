"""All network I/O executes here; Qt delivers completion on the GUI thread."""

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    finished = pyqtSignal()


class RequestWorker(QRunnable):
    def __init__(self, function: Callable):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            self.signals.succeeded.emit(self.function())
        except Exception as exc:
            logger.warning("Background request failed (%s)", type(exc).__name__)
            self.signals.failed.emit(exc)
        finally:
            self.function = lambda: None
            self.signals.finished.emit()


class WorkerPool(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self._workers: dict[int, RequestWorker] = {}

    def submit(self, function: Callable, success: Callable, failure: Callable) -> None:
        worker = RequestWorker(function)
        identity = id(worker)
        self._workers[identity] = worker
        worker.signals.succeeded.connect(success)
        worker.signals.failed.connect(failure)
        worker.signals.finished.connect(lambda: self._workers.pop(identity, None))
        self.pool.start(worker)
