# Divide Scanned Images for GIMP 3.x

This workspace contains a Python 3 port of Francois Malan's `DivideScannedImages.scm` Script-Fu plug-in for GIMP 3.x.

The plug-in detects foreground items on a mostly uniform scan background, creates one new image per detected item, and saves the crops as JPG or PNG.

## Install

For a normal Windows GIMP 3 install:

```powershell
.\install.ps1
```

The installer targets the highest existing `%APPDATA%\GIMP\3.x` profile folder. To force a specific profile:

```powershell
.\install.ps1 -GimpVersion 3.2
```

Or copy the `divide-scanned-images` folder into your GIMP 3 user plug-ins folder:

```text
%APPDATA%\GIMP\3.2\plug-ins\divide-scanned-images\
```

The installed folder must contain `divide-scanned-images.py` with the same base name as the folder. Restart GIMP after installing.

## Use

Open a scanned page in GIMP, select the layer to process, then run:

```text
Filters > Divide Scanned Images...
```

The interactive dialog includes a `Preview` button. Preview runs crop detection in memory and shows the detected split images in the same dialog without writing files. Each preview has a `Rotate` button; rotations are applied to the cached in-memory crop and are preserved when you click `Split`.

The batch entry is registered as:

```text
Filters > Batch Tools > Batch Divide Scanned Images...
```

Important options match the original plug-in:

- `Selection threshold`: how far a pixel may differ from the background before it is considered foreground.
- `Size threshold`: rejects small detected components as dust/noise.
- `Force square crop`: creates square output around each detected item.
- `Border padding`: adds background-colored padding around crops.
- `Deskew after splitting`: estimates each crop's skew from the detected photo footprint, rotates it in memory, samples the rotated crop corners as the local background, then trims leftover background whitespace.
- `Max deskew angle`: ignores larger estimated angles so badly detected crops are not accidentally rotated.
- `Whitespace crop padding after deskew`: keeps a small background border after deskew whitespace trimming.
- `Enhance with OpenAI after split`: after `Split`, saves the normal crop and then saves an additional `-enhanced.png` copy generated with OpenAI's image edit endpoint. Preview does not call OpenAI.
- `Save output to source directory`: uses the opened file's folder when available.

If the source image has not been saved and no target directory is selected, the plug-in stops and asks for an explicit output directory instead of silently writing into the process working folder.

The split/save operation reports progress through GIMP's progress UI. Preview generation also has a progress bar inside the dialog.

After the source scan has been analyzed, crop extraction and in-memory post-processing run in a process pool with up to one fewer worker than the number of CPU cores. If the embedded GIMP Python runtime cannot spawn process workers, the plug-in falls back to sequential processing.

OpenAI enhancement requires `OPENAI_API_KEY` in the environment visible to GIMP. It uses `gpt-image-1`, `quality=high`, and orientation-aware output size (`1024x1536` for portrait crops, `1536x1024` for landscape/square crops). The prompt is:

```text
Restore and improve this scanned vintage family photo while preserving the original composition, people, clothing, expressions, pose, and background. Correct fading, haze, low contrast, color cast, dust, scratches, and scan artifacts. Improve sharpness and facial clarity naturally, without making the image look modern, artificial, airbrushed, or like a new photo. Keep the film-photo look, realistic grain, realistic lighting, and the same framing. Do not change identities, do not add or remove people, do not invent new objects, and do not alter clothing designs or text except to make existing details clearer.
```

The OpenAI image edit API is generative, so exact preservation cannot be guaranteed. Keep the normal crop files as the source of truth.

The optional external `deskew.exe` step from the original Script-Fu is not bundled here. This port focuses on GIMP 3's Python plug-in API and portable crop extraction.

## Development

The image detection logic lives in `divide-scanned-images/divide_scanned_images_core.py` and is testable without GIMP. The GIMP wrapper lives in `divide-scanned-images/divide-scanned-images.py`.

Run the available local checks:

```powershell
python -m unittest discover -s tests
python -m py_compile .\divide-scanned-images\divide_scanned_images_core.py .\divide-scanned-images\divide-scanned-images.py
```

To iterate on a real image without launching GIMP, run the core pipeline from disk. This uses Pillow only for image file loading/saving; detection, deskew, rotation, and cropping still use the same plug-in core code:

```powershell
python .\tools\process_disk_image.py C:\path\to\scan.jpg --output-dir .\disk-test-output --deskew --threshold 25 --min-size 100
```

You can also wire one real image into unittest:

```powershell
$env:DSI_TEST_IMAGE='C:\path\to\scan.jpg'
$env:DSI_DESKEW='1'
python -m unittest tests.test_disk_image
```

The repository also includes a hardwired disk regression:

```powershell
python -m unittest tests.test_disk_image.DiskImageTests.test_sample_resource_matches_expected_outputs
```

That test processes `tests/resources/Sample.png`, compares the generated crops to `tests/resources/Sample-output-*.png`, and verifies each crop edge has at least 20% foreground density against the sampled source background. It is intentionally slower than the unit-only tests because it runs the full disk pipeline.

The GIMP runtime itself is not available from this workspace unless `gimp` is on `PATH`, so final plug-in loading needs to be checked inside GIMP.

## Upstream

Port source: <https://github.com/FrancoisMalan/DivideScannedImages>

This port was based on upstream commit `51e8f3983feeeeec4e2e3b3b00c5a06020e3e22b`.

License: GPL-2.0-or-later, following the upstream Script-Fu license.
