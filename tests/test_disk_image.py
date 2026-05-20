import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "process_disk_image.py"


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


if __name__ == "__main__":
    unittest.main()
