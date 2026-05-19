import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "divide-scanned-images"))

from divide_scanned_images_core import (  # noqa: E402
    Component,
    detect_crops,
    extract_crop_rgba,
    iter_supported_files,
    plan_crop,
    rotate_rgba_clockwise,
    sample_background,
)


def canvas(width, height, color=(255, 255, 255, 255)):
    return bytearray(color * (width * height))


def rect(rgba, width, x0, y0, x1, y1, color):
    for y in range(y0, y1):
        for x in range(x0, x1):
            i = (y * width + x) * 4
            rgba[i : i + 4] = bytes(color)


class CoreTests(unittest.TestCase):
    def test_samples_background_from_corner(self):
        rgba = canvas(20, 20, (250, 251, 252, 255))
        rect(rgba, 20, 10, 10, 15, 15, (0, 0, 0, 255))

        self.assertEqual(sample_background(rgba, 20, 20, "top-left", 2, 2, radius=1), (250, 251, 252, 255))

    def test_detects_separate_components(self):
        rgba = canvas(30, 20)
        rect(rgba, 30, 2, 3, 8, 10, (20, 20, 20, 255))
        rect(rgba, 30, 18, 5, 27, 16, (30, 30, 30, 255))

        crops = detect_crops(rgba, 30, 20, (255, 255, 255, 255), threshold=25, min_size=2, limit=10)

        self.assertEqual([crop.component.bbox for crop in crops], [(2, 3, 8, 10), (18, 5, 27, 16)])

    def test_square_crop_uses_padding(self):
        crop = plan_crop(Component((10, 20, 30, 30), area=200), padding=4, square=True)

        self.assertEqual(crop.width, crop.height)
        self.assertEqual(crop.rect, (6, 11, 34, 39))

    def test_extract_crop_fills_outside_canvas(self):
        rgba = canvas(4, 4, (10, 20, 30, 255))
        crop = Component((0, 0, 2, 2), area=4)
        planned = plan_crop(crop, padding=1, square=False)

        extracted, width, height = extract_crop_rgba(rgba, 4, 4, planned, (255, 255, 255, 255))

        self.assertEqual((width, height), (4, 4))
        self.assertEqual(tuple(extracted[:4]), (255, 255, 255, 255))
        center = (1 * width + 1) * 4
        self.assertEqual(tuple(extracted[center : center + 4]), (10, 20, 30, 255))

    def test_iter_supported_files_sorted_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["b.PNG", "a.jpg", "ignored.txt"]:
                open(os.path.join(tmp, name), "wb").close()

            files = iter_supported_files(tmp, ["png", "jpg"])

        self.assertEqual([os.path.basename(path) for path in files], ["a.jpg", "b.PNG"])

    def test_rotate_rgba_clockwise(self):
        rgba = bytes(
            (
                1, 0, 0, 255,
                2, 0, 0, 255,
                3, 0, 0, 255,
                4, 0, 0, 255,
                5, 0, 0, 255,
                6, 0, 0, 255,
            )
        )

        rotated, width, height = rotate_rgba_clockwise(rgba, 3, 2)

        self.assertEqual((width, height), (2, 3))
        self.assertEqual(list(rotated[0::4]), [4, 1, 5, 2, 6, 3])


if __name__ == "__main__":
    unittest.main()
