"""Keras 3 on the torch backend.

Keras picks its backend once, at its first import, and defaults to TensorFlow, which is not installed here.
Every module that needs Keras goes through keras_torch(), so the backend is set before that first import.
"""
import os


def keras_torch():
    """The keras module, imported with the torch backend."""
    os.environ.setdefault("KERAS_BACKEND", "torch")
    import keras

    backend = keras.backend.backend()
    if backend != "torch":
        raise RuntimeError(f"Keras runs on {backend!r}; unset KERAS_BACKEND or set it to 'torch'")
    return keras
