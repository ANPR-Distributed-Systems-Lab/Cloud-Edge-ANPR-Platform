"""ONNX export of an OCR model with Keras 3 on the torch backend, without TensorFlow.

fast-plate-ocr's own export does not work here: it writes through a NamedTemporaryFile, which Windows cannot
reopen, and it exports with a dynamic batch size, for which Keras falls back to the TorchScript exporter,
which cannot convert the model's blur pooling. The model is exported with batch size 1 instead, through Keras'
default TorchDynamo path; the edge node reads one plate per call anyway. The result matches fast-plate-ocr's
own ONNX models (uint8 RGB input, channels last, outputs `plate` and `region`), so its ONNX Runtime inference
loads it unchanged.
"""
from pathlib import Path

from .backend import keras_torch

OUTPUT_BY_RANK = {3: "plate", 2: "region"}  # (batch, slots, alphabet) and (batch, regions)


def name_outputs(path: Path) -> None:
    """Renames the outputs to `plate` and `region`. The torch exporter names them after internal layers, and
    fast-plate-ocr's inference would then pick the plate output by position instead of by name."""
    import onnx

    model = onnx.load(str(path))
    renames = {o.name: OUTPUT_BY_RANK.get(len(o.type.tensor_type.shape.dim)) for o in model.graph.output}
    if sorted(map(str, renames.values())) != ["plate", "region"]:
        raise ValueError(f"unexpected outputs of {path}: {list(renames)}")
    for node in model.graph.node:
        node.output[:] = [renames.get(n, n) for n in node.output]
        node.input[:] = [renames.get(n, n) for n in node.input]
    for out in model.graph.output:
        out.name = renames[out.name]
    onnx.checker.check_model(model)
    onnx.save(model, str(path))


def export_onnx(keras_path: Path, plate_config_path: Path, out: Path) -> Path:
    keras = keras_torch()
    # Internal helpers of fast-plate-ocr (version pinned in pyproject.toml): the loader that registers its
    # custom layers, and the wrapper that puts the uint8 input handling in front of the model.
    from fast_plate_ocr.cli.export import _prepare_model_for_onnx_export
    from fast_plate_ocr.train.model.config import load_plate_config_from_yaml
    from fast_plate_ocr.train.utilities.utils import load_keras_model

    plate_config = load_plate_config_from_yaml(plate_config_path)
    model = load_keras_model(keras_path, plate_config)
    export_model, input_shape, _ = _prepare_model_for_onnx_export(
        model, plate_config, dynamic_batch=False, input_dtype="uint8", data_format="channels_last")
    partial = out.with_name(out.name + ".partial")
    export_model.export(str(partial), format="onnx", verbose=False,
                        input_signature=[keras.InputSpec(name="input", shape=input_shape, dtype="uint8")])
    name_outputs(partial)
    partial.replace(out)  # model.onnx marks a finished run, so it only appears complete
    return out
