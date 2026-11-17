"""The plate detector: YOLO-pose with the 4 plate corners as keypoints.

config (configs/*.yaml) -> dataset (anpr-yolo-dataset) -> train (anpr-train-detector)
-> predict + metrics -> evaluate (anpr-eval-detector) -> report (W&B)
"""
