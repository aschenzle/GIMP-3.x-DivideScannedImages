import base64
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "divide-scanned-images"))

from divide_scanned_images_openai import enhanced_output_path  # noqa: E402
from divide_scanned_images_openai import rgba_to_png_bytes  # noqa: E402
from divide_scanned_images_openai import _multipart_body  # noqa: E402


class OpenAIHelperTests(unittest.TestCase):
    def test_rgba_to_png_bytes_has_png_signature(self):
        png = rgba_to_png_bytes(bytes((255, 0, 0, 255)), 1, 1)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(b"IHDR", png)
        self.assertIn(b"IDAT", png)
        self.assertIn(b"IEND", png)

    def test_enhanced_output_path_forces_png_suffix(self):
        self.assertEqual(enhanced_output_path(r"C:\out\Crop00001.jpg"), r"C:\out\Crop00001-enhanced.png")

    def test_multipart_body_contains_fields_and_file(self):
        body, content_type = _multipart_body(
            {"model": "gpt-image-1.5", "prompt": "Improve detail"},
            [("image", "crop.png", "image/png", b"png-bytes")],
        )

        self.assertIn("multipart/form-data; boundary=", content_type)
        self.assertIn(b'name="model"', body)
        self.assertIn(b"gpt-image-1.5", body)
        self.assertIn(b'name="image"; filename="crop.png"', body)
        self.assertIn(b"png-bytes", body)

    def test_base64_shape_used_by_api_response(self):
        encoded = base64.b64encode(b"image").decode("ascii")
        payload = json.dumps({"data": [{"b64_json": encoded}]})

        self.assertEqual(json.loads(payload)["data"][0]["b64_json"], encoded)


if __name__ == "__main__":
    unittest.main()
