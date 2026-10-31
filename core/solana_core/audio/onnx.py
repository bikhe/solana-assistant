"""Small wrapper around onnxruntime so models can be swapped for numpy fakes in tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float32]
# One model call: named inputs in, outputs in declaration order out.
Runner = Callable[[dict[str, NDArray[Any]]], list[NDArray[Any]]]


class OnnxModel:
    """A CPU onnxruntime session limited to one thread, so idle listening stays cheap."""

    def __init__(self, path: Path | str, threads: int = 1) -> None:
        import onnxruntime as ort  # heavy import, only when a real model is used

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.log_severity_level = 3
        self.path = Path(path)
        self._session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        inputs = self._session.get_inputs()
        self.input_names: list[str] = [i.name for i in inputs]
        self.input_shapes: list[list[Any]] = [list(i.shape) for i in inputs]

    def __call__(self, feed: dict[str, NDArray[Any]]) -> list[NDArray[Any]]:
        return list(self._session.run(None, feed))
