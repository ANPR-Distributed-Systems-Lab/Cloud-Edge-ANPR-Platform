import json

import cv2
import numpy as np
import pytest

from anpr_ml.analysis import from_env
from anpr_ml.detector.predict import Prediction
from anpr_ml.ocr.dataset import CropSettings, build_dataset, jitter_corners, plate_rng, record_crops
from anpr_ml.ocr.metrics import edit_distance, evaluate
from anpr_ml.ocr.predict import Reading
from anpr_ml.pipeline import Read, match_detections, read_category, readable_plates, summarize
from samples import FAR, PLATE, SMALL, H, W, record

OTHER = [[0.10, 0.60], [0.30, 0.60], [0.30, 0.66], [0.10, 0.66]]  # a second 80 px plate
EMPTY = [[0.60, 0.10], [0.80, 0.10], [0.80, 0.16], [0.60, 0.16]]  # where there is no plate at all
REJECTS = CropSettings(jitter_copies=0, reject_sources=("unreadable", "ignore"))


def labeled(image="b/session_a__0000__img_000001.jpg", wide_ignore=False):
    """A frame with a readable plate (PLATE), an unreadable one (OTHER) and a 20 px ignore region (FAR);
    wide_ignore adds an 80 px ignore region (EMPTY) as the second one."""
    r = record(image, plates=(PLATE, OTHER))
    r["plates"][0].update(readable=True, text="WA12345")
    if wide_ignore:
        r["ignore"].append({"corners": EMPTY})
    return r


def write_batch(tmp_path, recs):
    """The records as a label file, with a plain gray frame for each; returns the file and the image folder."""
    images = tmp_path / "batches"
    (images / "b").mkdir(parents=True)
    for r in recs:
        cv2.imwrite(str(images / r["image"]), np.full((H, W, 3), 90, np.uint8))
    export = tmp_path / "b.jsonl"
    export.write_text("".join(json.dumps(r) + "\n" for r in recs))
    return export, images


def reading(text, conf=0.99):
    return Reading(text, np.full(10, conf))


def test_jitter_is_reproducible_per_plate_and_scaled_by_width():
    corners = np.array(PLATE) * [W, H]
    a = jitter_corners(corners, 0.05, plate_rng(1, "f.jpg", 0))
    b = jitter_corners(corners, 0.05, plate_rng(1, "f.jpg", 0))
    c = jitter_corners(corners, 0.05, plate_rng(1, "f.jpg", 1))
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert 0 < np.abs(a - corners).max() < 0.05 * 80 * 5  # within 5 sigma of 5 % of the 80 px width


def test_record_crops_only_readable_plates_with_copies_for_train():
    frame = np.full((H, W, 3), 120, np.uint8)
    settings = CropSettings(jitter_copies=3)
    train = record_crops(labeled(), frame, settings, jitter=True)
    val = record_crops(labeled(), frame, settings, jitter=False)
    assert [name for name, _, _ in train] == [f"session_a__0000__img_000001__p0__j{j}.png" for j in range(3)]
    assert [name for name, _, _ in val] == ["session_a__0000__img_000001__p0.png"]
    _, crop, row = val[0]
    assert crop.shape == (64, 128, 3)
    assert row["text"] == "WA12345" and row["kind"] == "readable" and row["jitter"] == 0
    assert row["width_px"] == pytest.approx(80)


def test_record_crops_adds_wide_rejects_without_changing_the_readable_crops():
    frame = np.random.default_rng(0).integers(0, 256, (H, W, 3), dtype=np.uint8)
    plain = record_crops(labeled(wide_ignore=True), frame, CropSettings(jitter_copies=2), jitter=True)
    settings = CropSettings(jitter_copies=2, reject_sources=("unreadable", "ignore"))
    crops = record_crops(labeled(wide_ignore=True), frame, settings, jitter=True)
    # FAR, the 20 px ignore region, is below reject_min_px
    assert [name for name, _, _ in crops] == [f"session_a__0000__img_000001__{q}__j{j}.png"
                                              for q in ("p0", "p1", "i1") for j in range(2)]
    assert [(row["kind"], row["text"]) for _, _, row in crops[::2]] == [
        ("readable", "WA12345"), ("unreadable", ""), ("ignore", "")]
    assert all(np.array_equal(a, b) for (_, a, _), (_, b, _) in zip(plain, crops[:2], strict=True))
    only_unreadable = CropSettings(jitter_copies=0, reject_sources=("unreadable",))
    assert [row["kind"] for _, _, row in record_crops(labeled(wide_ignore=True), frame, only_unreadable,
                                                     jitter=False)] == ["readable", "unreadable"]


def test_crop_settings_record_rejects_only_when_used():
    assert CropSettings().as_manifest()["reject"] is None  # as in the manifests written before rejects
    assert REJECTS.as_manifest()["reject"] == {"sources": ["unreadable", "ignore"], "min_px": 70}
    with pytest.raises(ValueError, match="unknown reject sources"):
        CropSettings(reject_sources=("blurry",))


def test_build_dataset_writes_fast_plate_ocr_csvs_and_skips_test(tmp_path):
    recs = [labeled(f"b/session_{s}__0000__img_00000{i}.jpg") for i, s in enumerate("abc")]
    export, images = write_batch(tmp_path, recs)
    splits = {"train": ["session_a"], "val": ["session_b"], "test": ["session_c"]}

    out = tmp_path / "ds"
    manifest = build_dataset([export], out, CropSettings(jitter_copies=2), images_dir=images, splits=splits)
    assert manifest["counts"]["train"]["crops"] == 2 and manifest["counts"]["val"]["crops"] == 1
    assert manifest["jitter_copies"] == 2 and manifest["size"] == [128, 64]
    assert not (out / "test").exists()
    assert (out / "val" / "annotations.csv").read_text().splitlines() == [
        "image_path,plate_text,plate_region", "images/session_b__0000__img_000001__p0.png,WA12345,Poland"]
    assert (out / "train" / "images" / "session_a__0000__img_000000__p0__j1.png").is_file()
    with pytest.raises(FileExistsError):
        build_dataset([export], out, images_dir=images, splits=splits)


def test_build_dataset_writes_rejects_with_empty_text_and_unknown_region(tmp_path):
    export, images = write_batch(tmp_path, [labeled("b/session_b__0000__img_000001.jpg", wide_ignore=True)])
    out = tmp_path / "ds"
    manifest = build_dataset([export], out, REJECTS, images_dir=images,
                             splits={"train": [], "val": ["session_b"], "test": []})
    assert manifest["reject"] == {"sources": ["unreadable", "ignore"], "min_px": 70}
    counts = manifest["counts"]["val"]
    assert (counts["plates"], counts["crops"], counts["unreadable_crops"], counts["ignore_crops"]) == (1, 3, 1, 1)
    stem = "images/session_b__0000__img_000001"
    assert (out / "val" / "annotations.csv").read_text().splitlines() == [
        "image_path,plate_text,plate_region", f"{stem}__p0.png,WA12345,Poland", f"{stem}__p1.png,,Unknown",
        f"{stem}__i1.png,,Unknown"]


def test_export_names_the_outputs_like_fast_plate_ocr(tmp_path):
    import onnx
    from onnx import TensorProto, helper

    from anpr_ml.ocr.export import name_outputs

    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 10, 37])
    outputs = [helper.make_tensor_value_info("softmax_11", TensorProto.FLOAT, [1, 66]),
               helper.make_tensor_value_info("softmax_12", TensorProto.FLOAT, [1, 10, 37])]
    nodes = [helper.make_node("ReduceMax", ["input"], ["pooled"], axes=[2], keepdims=0),
             helper.make_node("Pad", ["pooled", "pads"], ["softmax_11"]),
             helper.make_node("Identity", ["input"], ["softmax_12"])]
    pads = helper.make_tensor("pads", TensorProto.INT64, [4], [0, 0, 0, 56])
    graph = helper.make_graph(nodes, "g", [x], outputs, initializer=[pads])
    path = tmp_path / "m.onnx"
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)]), str(path))

    name_outputs(path)
    assert [o.name for o in onnx.load(str(path)).graph.output] == ["region", "plate"]


def test_edit_distance():
    assert edit_distance("WA12345", "WA12345") == 0
    assert edit_distance("WA1234", "WA12345") == 1
    assert edit_distance("WB12845", "WA12345") == 2


def test_ocr_metrics_exact_cer_positions_and_coverage():
    texts = ["WA12345", "KR9876C", "GD1111A"]
    reads = [reading("WA12345"), reading("KR9B76C", 0.6), reading("GD111A", 0.4)]
    res = evaluate(texts, reads, [80, 150, 60])
    assert res["exact"] == pytest.approx(1 / 3)
    assert res["cer"] == pytest.approx(2 / 21)
    assert res["wrong_length"] == 1
    assert res["positions"][3]["errors"] == 1 and res["positions"][3]["reads"] == 2  # same-length reads only
    assert res["confusions"] == [{"true": "8", "read": "B", "count": 1}]
    assert [b["width_px"] for b in res["by_width"]] == ["<70", "70-90", "140-200"]
    cov = {c["conf"]: c for c in res["coverage"]}
    assert cov[0.5]["n_kept"] == 2 and cov[0.5]["exact"] == pytest.approx(0.5)
    assert cov[0.95]["n_kept"] == 1 and cov[0.95]["exact"] == 1.0
    assert res["reject_crops"] == 0 and np.isnan(res["reject_rate"])


def test_ocr_metrics_count_rejects_apart_from_the_readable_crops():
    texts = ["WA12345", "KR9876C", "", "", ""]
    reads = [reading("WA12345"), reading("", 0.9), reading(""), reading("GD1A", 0.6), reading("X", 0.97)]
    res = evaluate(texts, reads, [80, 150, 90, 100, 120])
    assert (res["crops"], res["exact"], res["false_rejects"]) == (2, 0.5, 1)
    assert res["reject_crops"] == 3 and res["reject_rate"] == pytest.approx(1 / 3)
    cov = {c["conf"]: c for c in res["coverage"]}
    assert (cov[0.0]["n_kept"], cov[0.0]["rejects_sent"]) == (1, 2)  # an empty reading is never sent
    assert cov[0.95]["rejects_sent"] == 1


def test_pipeline_matches_every_detection_to_a_target():
    r = labeled()
    r["plates"].insert(0, {"corners": SMALL, "text": "", "readable": False, "occlusion": "none",
                           "type": "standard"})  # below the threshold, and shifts the other plates' indices
    dets = [Prediction(c, np.array(q)) for c, q in ((0.9, PLATE), (0.8, OTHER), (0.7, SMALL), (0.6, FAR),
                                                     (0.5, EMPTY))]
    matched = [(target, i) for _, target, i in match_detections(r, dets, 70)]
    assert matched == [("readable", 1), ("unreadable", 2), ("dont_care", None), ("dont_care", None),
                       ("background", None)]
    assert read_category("readable", "WA12345", "WA12345") == "correct"
    assert read_category("readable", "WA12346", "WA12345") == "wrong"
    assert read_category("background", "X1", None) == "background"
    rows = readable_plates(r, 70, {1: True})
    assert [(row["detected"], row["read_correct"], row["bucket"]) for row in rows] == [(True, True, "70-90")]


def test_pipeline_summary_traces_precision_over_the_threshold():
    det = Prediction(0.9, np.array(PLATE))
    reads = [Read("f", "correct", reading("A", 0.99), det), Read("f", "wrong", reading("B", 0.5), det),
             Read("f", "unreadable", reading("C", 0.95), det)]
    plates = [{"bucket": "70-90", "detected": True, "read_correct": True},
              {"bucket": "70-90", "detected": True, "read_correct": False}]
    res = summarize(reads, plates)
    curve = {c["conf"]: c for c in res["curve"]}
    assert curve[0.0]["sent"] == 3 and curve[0.0]["precision"] == pytest.approx(1 / 3)
    assert curve[0.9]["sent"] == 2 and curve[0.9]["unreadable"] == 1
    assert res["recall"] == 0.5 and res["by_width"][0]["read_correct"] == 1
    assert not any(res["rejected"].values())


def test_pipeline_never_sends_a_rejected_read():
    det = Prediction(0.9, np.array(PLATE))
    reads = [Read("f", "correct", reading("A"), det), Read("f", "wrong", reading(""), det),
             Read("f", "unreadable", reading(""), det)]
    res = summarize(reads, [{"bucket": "70-90", "detected": True, "read_correct": True},
                            {"bucket": "70-90", "detected": True, "read_correct": False}])
    curve = {c["conf"]: c for c in res["curve"]}
    assert curve[0.0]["sent"] == 1 and curve[0.0]["precision"] == 1.0
    assert res["rejected"] == {"correct": 0, "wrong": 1, "unreadable": 1, "dont_care": 0, "background": 0}


def test_from_env_overrides_the_notebook_value(monkeypatch):
    monkeypatch.delenv("ANPR_TEST_VERSION", raising=False)
    assert from_env("ANPR_TEST_VERSION", "v1") == "v1"
    monkeypatch.setenv("ANPR_TEST_VERSION", "v2")
    assert from_env("ANPR_TEST_VERSION", "v1") == "v2"
    monkeypatch.setenv("ANPR_TEST_VERSION", "none")
    assert from_env("ANPR_TEST_VERSION", "v1") is None
