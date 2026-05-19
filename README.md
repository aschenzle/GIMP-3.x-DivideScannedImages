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
- `Save output to source directory`: uses the opened file's folder when available.

If the source image has not been saved and no target directory is selected, the plug-in stops and asks for an explicit output directory instead of silently writing into the process working folder.

The split/save operation reports progress through GIMP's progress UI. Preview generation also has a progress bar inside the dialog.

The optional external `deskew.exe` step from the original Script-Fu is not bundled here. This port focuses on GIMP 3's Python plug-in API and portable crop extraction.

## Development

The image detection logic lives in `divide-scanned-images/divide_scanned_images_core.py` and is testable without GIMP. The GIMP wrapper lives in `divide-scanned-images/divide-scanned-images.py`.

Run the available local checks:

```powershell
python -m unittest discover -s tests
python -m py_compile .\divide-scanned-images\divide_scanned_images_core.py .\divide-scanned-images\divide-scanned-images.py
```

The GIMP runtime itself is not available from this workspace unless `gimp` is on `PATH`, so final plug-in loading needs to be checked inside GIMP.

## Upstream

Port source: <https://github.com/FrancoisMalan/DivideScannedImages>

This port was based on upstream commit `51e8f3983feeeeec4e2e3b3b00c5a06020e3e22b`.

License: GPL-2.0-or-later, following the upstream Script-Fu license.
