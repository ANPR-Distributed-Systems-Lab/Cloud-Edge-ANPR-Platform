import onnxruntime as ort

THREADS = 4  # the Pi 5 has four cores


def session(model_path: str, threads: int = THREADS) -> ort.InferenceSession:
    """An ONNX Runtime session on the CPU, the only execution provider on the Pi."""
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    return ort.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
