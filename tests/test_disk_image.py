import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "divide-scanned-images"))

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None

SCRIPT = ROOT / "tools" / "process_disk_image.py"
RESOURCE_DIR = ROOT / "tests" / "resources"

from divide_scanned_images_core import sample_corner_background  # noqa: E402


@unittest.skipIf(Image is None, "Pillow is required for disk image tests")
class DiskImageTests(unittest.TestCase):
    def test_processes_synthetic_png_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "scan.png"
            output_dir = tmp_path / "out"

            image = Image.new("RGBA", (120, 80), (255, 255, 255, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 12, 45, 48), fill=(20, 20, 20, 255))
            draw.rectangle((70, 20, 105, 60), fill=(30, 30, 30, 255))
            image.save(input_path)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--threshold",
                    "25",
                    "--min-size",
                    "10",
                    "--limit",
                    "5",
                    "--sample-x",
                    "5",
                    "--sample-y",
                    "5",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = sorted(output_dir.glob("*.png"))
            self.assertEqual(len(outputs), 2, result.stdout)

    def test_sample_resource_matches_expected_outputs(self):
        input_path = RESOURCE_DIR / "Sample.png"
        expected_paths = [RESOURCE_DIR / f"Sample-output-{index:05d}.png" for index in range(1, 5)]
        if not input_path.exists() or not all(path.exists() for path in expected_paths):
            self.skipTest("Sample.png and expected Sample-output PNGs are required.")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(input_path),
                    "--output-dir",
                    str(output_dir),
                    "--prefix",
                    "Sample-output-",
                    "--deskew",
                    "--threshold",
                    "25",
                    "--min-size",
                    "100",
                    "--limit",
                    "10",
                    "--background",
                    "corners",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            actual_paths = [output_dir / f"Sample-output-{index:05d}.png" for index in range(1, 5)]
            self.assertTrue(all(path.exists() for path in actual_paths), result.stdout)

            with Image.open(input_path) as source:
                source_rgba = source.convert("RGBA")
                source_background = sample_corner_background(source_rgba.tobytes(), source_rgba.width, source_rgba.height)

            for expected_path, actual_path in zip(expected_paths, actual_paths):
                with Image.open(expected_path) as expected_image, Image.open(actual_path) as actual_image:
                    expected_rgba = expected_image.convert("RGBA")
                    actual_rgba = actual_image.convert("RGBA")
                    self.assertEqual(actual_rgba.size, expected_rgba.size, actual_path.name)
                    self.assertEqual(actual_rgba.tobytes(), expected_rgba.tobytes(), actual_path.name)
                    self.assert_no_edge_whitespace(actual_rgba, source_background, actual_path.name)

    def test_processes_env_image_when_provided(self):
        image_path = os.environ.get("DSI_TEST_IMAGE")
        if not image_path:
            self.skipTest("Set DSI_TEST_IMAGE to run a real disk-image regression.")

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    image_path,
                    "--output-dir",
                    str(output_dir),
                    "--threshold",
                    os.environ.get("DSI_THRESHOLD", "25"),
                    "--min-size",
                    os.environ.get("DSI_MIN_SIZE", "100"),
                    "--limit",
                    os.environ.get("DSI_LIMIT", "10"),
                    *(["--deskew"] if os.environ.get("DSI_DESKEW") == "1" else []),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(len(list(output_dir.glob("*.png"))), 0, result.stdout)

    def assert_no_edge_whitespace(self, image, background, label):
        pixels = image.load()
        width, height = image.size

        def is_foreground(pixel):
            return (
                pixel[3] != 0
                and max(
                    abs(pixel[0] - background[0]),
                    abs(pixel[1] - background[1]),
                    abs(pixel[2] - background[2]),
                )
                > 25
            )

        edge_ratios = {
            "top": sum(1 for x in range(width) if is_foreground(pixels[x, 0])) / width,
            "bottom": sum(1 for x in range(width) if is_foreground(pixels[x, height - 1])) / width,
            "left": sum(1 for y in range(height) if is_foreground(pixels[0, y])) / height,
            "right": sum(1 for y in range(height) if is_foreground(pixels[width - 1, y])) / height,
        }
        for edge, ratio in edge_ratios.items():
            self.assertGreaterEqual(ratio, 0.2, f"{label} {edge} edge foreground ratio {ratio:.3f}")


if __name__ == "__main__":
    unittest.main()
