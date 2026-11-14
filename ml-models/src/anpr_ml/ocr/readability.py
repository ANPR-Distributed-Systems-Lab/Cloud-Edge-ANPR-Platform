"""The readability head: the OCR's second output, turned from the plate's country into "can it be read".

fast-plate-ocr's model has a region head that classifies the plate's country (66 classes). This project reads
Polish plates only, so with `model.readability_head: true` in an OCR config that head gets two classes,
READABILITY_CLASSES, and learns readable plates against the rejects of the dataset (unreadable plates and
plate_ignore regions, see anpr_ml.ocr.dataset). Only the head's last layer is new; the rest starts from the
pretrained weights. The text head is trained on the readable crops only (rejects weigh 0 in its loss), so
learning to decline costs it no reading quality, unlike training rejects as an empty text.

The exported model keeps its two outputs, `plate` and `region`; plate_config.yaml next to model.onnx lists the
classes. On the edge node a reading is used when P(readable), the region output at READABLE's index, is at
least a threshold; READABLE_THRESHOLD is the head's own decision (the likelier of the two classes).

Keras is passed in by the callers, already imported with its backend (anpr_ml.ocr.backend), so the plain
functions here are testable without it.
"""
import math
from pathlib import Path

import numpy as np
import yaml

READABLE, UNREADABLE = "readable", "unreadable"
READABILITY_CLASSES = (READABLE, UNREADABLE)
READABLE_THRESHOLD = 0.5
HEAD_LAYER = "region"  # the head's last layer in fast-plate-ocr's model builder, and the output's name


def is_readability(plate_regions) -> bool:
    """Whether a plate config's region list is the readability head's."""
    return tuple(plate_regions or ()) == READABILITY_CLASSES


def readable_prob(region: str, region_prob: float) -> float:
    """P(readable) from fast-plate-ocr's prediction, which holds the likelier class and its probability."""
    return region_prob if region == READABLE else 1.0 - region_prob


def write_plate_config(pretrained: Path, out: Path) -> None:
    """The pretrained plate config (input size, alphabet, slots) with READABILITY_CLASSES as its regions."""
    cfg = yaml.safe_load(pretrained.read_text(encoding="utf-8"))
    cfg["plate_regions"] = list(READABILITY_CLASSES)
    header = "# fast-plate-ocr plate config with the region head turned into the readability head\n"
    out.write_text(header + yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def batch_targets(texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """One-hot readability targets and text-loss weights of one batch. A crop with an empty text is a reject.

    The readable crops share a weight of 1 evenly and the rejects weigh 0, so the text loss, summed over the
    batch, is its mean over the readable crops; a batch without readable crops contributes nothing.
    """
    readable = np.array([bool(t) for t in texts])
    targets = np.stack([readable, ~readable], axis=1).astype(np.float32)
    weights = readable / max(int(readable.sum()), 1)
    return targets, weights.astype(np.float32)


def transfer_weights(source, target) -> None:
    """Copies every layer's weights from the pretrained model into the readability model, except HEAD_LAYER,
    which has a different shape. Both come from the same builder, so layers pair up by position (Keras
    numbers unnamed layers per session, so their names differ). Raises when the layers do not pair up, so a
    changed architecture cannot silently start from random weights."""
    if [type(s) for s in source.layers] != [type(t) for t in target.layers]:
        raise ValueError("the pretrained and the readability model have different layers")
    for src, dst in zip(source.layers, target.layers, strict=True):
        if dst.name == HEAD_LAYER or not dst.weights:
            continue
        weights = src.get_weights()
        if [w.shape for w in weights] != [tuple(w.shape) for w in dst.weights]:
            raise ValueError(f"layer {dst.name}: pretrained weights do not fit")
        dst.set_weights(weights)


def training_data(keras, annotations_file: Path, plate_config, batch_size: int, transform=None,
                  shuffle=False, seed: int = 0):
    """A Keras dataset over a split's annotations.csv yielding (images, targets, sample weights) for the
    `plate` and `region` outputs. Images, augmentation and text targets are prepared as fast-plate-ocr's own
    dataset does; the readability targets and weights come from batch_targets()."""
    from fast_plate_ocr.core.process import read_and_resize_plate_image
    from fast_plate_ocr.train.data.annotations import read_annotations_csv
    from fast_plate_ocr.train.utilities.utils import target_transform

    class ReadabilityDataset(keras.utils.PyDataset):
        def __init__(self):
            super().__init__()
            annotations = read_annotations_csv(annotations_file)
            self.paths = [str(annotations_file.parent / p) for p in annotations["image_path"]]
            self.texts = annotations["plate_text"].tolist()
            self.order = np.arange(len(self.texts))
            self.rng = np.random.default_rng(seed)
            self.on_epoch_begin()

        def __len__(self):
            return math.ceil(len(self.texts) / batch_size)

        def __getitem__(self, idx):
            rows = self.order[idx * batch_size:(idx + 1) * batch_size]
            texts = [self.texts[i] for i in rows]
            images = np.array([self.image(i) for i in rows])
            plates = np.array([target_transform(t, plate_config.max_plate_slots, plate_config.alphabet,
                                                plate_config.pad_char) for t in texts])
            targets, weights = batch_targets(texts)
            return (images, {"plate": plates, "region": targets},
                    {"plate": weights, "region": np.ones(len(rows), np.float32)})

        def image(self, i):
            x = read_and_resize_plate_image(
                self.paths[i], img_height=plate_config.img_height, img_width=plate_config.img_width,
                image_color_mode=plate_config.image_color_mode,
                keep_aspect_ratio=plate_config.keep_aspect_ratio,
                interpolation_method=plate_config.interpolation, padding_color=plate_config.padding_color)
            return transform(image=x)["image"] if transform else x

        def on_epoch_begin(self):
            if shuffle:
                self.rng.shuffle(self.order)

    return ReadabilityDataset()


def text_loss(keras, label_smoothing: float):
    """Cross-entropy over the text slots, averaged per crop and summed over the batch: with the weights of
    batch_targets(), the mean over the readable crops. (fast-plate-ocr's loss averages the whole batch into
    one number, which sample weights cannot mask.)"""
    ops = keras.ops

    class TextLoss(keras.losses.Loss):
        def __init__(self):
            super().__init__(reduction="sum", name="text_loss")

        def call(self, y_true, y_pred):
            y_true = ops.cast(y_true, y_pred.dtype)
            per_slot = keras.losses.categorical_crossentropy(y_true, y_pred, label_smoothing=label_smoothing)
            return ops.mean(per_slot, axis=-1)

    return TextLoss()


def text_metrics(keras) -> list:
    """Per-crop exact match and character accuracy; given as weighted metrics, they count readable crops only.
    Named like fast-plate-ocr's metrics, so training logs keep the columns plate_acc and plate_char_acc."""
    ops = keras.ops

    def acc(y_true, y_pred):
        same = ops.equal(ops.argmax(y_true, axis=-1), ops.argmax(y_pred, axis=-1))
        return ops.cast(ops.all(same, axis=-1), "float32")

    def char_acc(y_true, y_pred):
        same = ops.equal(ops.argmax(y_true, axis=-1), ops.argmax(y_pred, axis=-1))
        return ops.mean(ops.cast(same, "float32"), axis=-1)

    return [acc, char_acc]
