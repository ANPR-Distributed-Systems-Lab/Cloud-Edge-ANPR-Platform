"""Synthetic label records shared by the tests: a 400x300 "original" frame with normalized corners."""
W, H = 400, 300
PLATE = [[0.40, 0.40], [0.60, 0.40], [0.60, 0.46], [0.40, 0.46]]  # 80 px wide on the 400 px frame
SMALL = [[0.10, 0.10], [0.15, 0.10], [0.15, 0.12], [0.10, 0.12]]  # 20 px wide: below the small-plate threshold
FAR = [[0.80, 0.80], [0.85, 0.80], [0.85, 0.82], [0.80, 0.82]]  # used as a plate_ignore region


def record(image="b/session_a__0000__img_000001.jpg", plates=(PLATE,), ignore=(FAR,)):
    return {
        "image": image, "width": W, "height": H,
        "plates": [{"corners": c, "text": "", "readable": False, "occlusion": "none", "type": "standard"}
                   for c in plates],
        "ignore": [{"corners": c} for c in ignore],
    }
