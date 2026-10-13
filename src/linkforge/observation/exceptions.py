"""观察层异常。"""


class ObservationError(RuntimeError):
    """观察失败的基础异常。"""


class ObservationCaptureError(ObservationError):
    """当观察源无法被捕获时抛出。"""
