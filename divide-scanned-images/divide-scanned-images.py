#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Divide Scanned Images for GIMP 3.x
# Port based on DivideScannedImages.scm by Francois Malan.
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait
import multiprocessing
import os
import sys
import traceback

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")

from gi.repository import Gegl
from gi.repository import Gio
from gi.repository import Gimp
from gi.repository import GObject
from gi.repository import GLib

try:
    gi.require_version("Babl", "0.1")
    from gi.repository import Babl
except (ImportError, ValueError):
    Babl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from divide_scanned_images_core import (  # noqa: E402
    detect_crops,
    extract_crop_rgba,
    iter_supported_files,
    normalize_rgba,
    postprocess_crop_item,
    rotate_rgba_clockwise,
    sample_background,
)
from divide_scanned_images_openai import enhance_png_with_openai  # noqa: E402
from divide_scanned_images_openai import enhanced_output_path  # noqa: E402
from divide_scanned_images_openai import rgba_to_png_bytes  # noqa: E402


PLUGIN_BINARY = "divide-scanned-images"
PROC_IMAGE = "python-fu-divide-scanned-images"
PROC_BATCH = "python-fu-batch-divide-scanned-images"
RGBA_FORMAT = "R'G'B'A u8"
OPENAI_KEY_ENV = "OPENAI_API_KEY"

CORNER_LABELS = {
    "top-left": "Top Left",
    "top-right": "Top Right",
    "bottom-left": "Bottom Left",
    "bottom-right": "Bottom Right",
}
LOAD_TYPES = {
    "jpg": ("jpg",),
    "jpeg": ("jpeg",),
    "bmp": ("bmp",),
    "png": ("png",),
    "tif": ("tif",),
    "tiff": ("tiff",),
    "all": ("jpg", "jpeg", "bmp", "png", "tif", "tiff"),
}


def _choice(items):
    choice = Gimp.Choice.new()
    for nick, label in items:
        choice.add(nick, 0, label, "")
    return choice


def _run_dialog(procedure, config, title, fields):
    gi.require_version("GimpUi", "3.0")
    from gi.repository import GimpUi

    GimpUi.init(PLUGIN_BINARY)
    dialog = GimpUi.ProcedureDialog.new(procedure, config, title)
    dialog.fill(fields)
    accepted = dialog.run()
    dialog.destroy()
    return accepted


def _pixbuf_from_rgba(rgba_bytes, width, height):
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(rgba_bytes),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        width,
        height,
        width * 4,
    )


def _detection_fingerprint(settings):
    keys = (
        "square",
        "padding",
        "limit",
        "threshold",
        "min_size",
        "deskew",
        "deskew_max_angle",
        "deskew_crop_padding",
        "manual_bg",
        "manual_bg_color",
        "corner",
        "sample_x",
        "sample_y",
    )
    return tuple((key, settings[key]) for key in keys)


def _process_ui_events():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


def _drain_gtk_events(Gtk):
    _process_ui_events()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def _run_image_dialog(procedure, config, image, drawable):
    gi.require_version("GimpUi", "3.0")
    gi.require_version("Gtk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    from gi.repository import GimpUi
    from gi.repository import Gtk

    GimpUi.init(PLUGIN_BINARY)
    fields = [
        "square-crop",
        "padding",
        "limit",
        "auto-close",
        "threshold",
        "min-size",
        "deskew",
        "deskew-max-angle",
        "deskew-crop-padding",
        "enhance-openai",
        "manual-background",
        "background-color",
        "sample-corner",
        "sample-x",
        "sample-y",
        "save-in-source",
        "target-dir",
        "save-type",
        "file-base",
        "start-number",
    ]

    dialog = GimpUi.ProcedureDialog.new(procedure, config, "Divide Scanned Images")
    dialog.set_ok_label("_Split")
    dialog.set_default_size(1400, 820)
    preview_response = 1001
    dialog.add_button("_Preview", preview_response)

    options_box = dialog.fill_box("options-box", fields)
    options_box.set_margin_top(6)
    options_box.set_margin_bottom(6)
    options_box.set_margin_start(6)
    options_box.set_margin_end(6)

    options_scroll = Gtk.ScrolledWindow()
    options_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    options_scroll.set_min_content_width(360)
    options_scroll.add(options_box)

    preview_label = Gtk.Label(label="Click Preview to inspect detected crops before splitting.")
    preview_label.set_xalign(0.0)
    progress_bar = Gtk.ProgressBar()
    progress_bar.set_show_text(True)
    progress_bar.set_text("Ready")

    preview_flow = Gtk.FlowBox()
    preview_flow.set_selection_mode(Gtk.SelectionMode.NONE)
    preview_flow.set_min_children_per_line(1)
    preview_flow.set_max_children_per_line(6)
    preview_flow.set_row_spacing(10)
    preview_flow.set_column_spacing(10)
    preview_flow.set_margin_top(8)
    preview_flow.set_margin_bottom(8)
    preview_flow.set_margin_start(8)
    preview_flow.set_margin_end(8)

    preview_scroll = Gtk.ScrolledWindow()
    preview_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    preview_scroll.add(preview_flow)

    preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    preview_box.set_margin_top(6)
    preview_box.set_margin_bottom(6)
    preview_box.set_margin_start(6)
    preview_box.set_margin_end(6)
    preview_box.pack_start(preview_label, False, False, 0)
    preview_box.pack_start(progress_bar, False, False, 0)
    preview_box.pack_start(preview_scroll, True, True, 0)

    main_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    main_paned.pack1(options_scroll, resize=False, shrink=False)
    main_paned.pack2(preview_box, resize=True, shrink=False)
    main_paned.set_position(330)

    dialog.get_content_area().pack_start(main_paned, True, True, 0)
    preview_cache = {"fingerprint": None, "items": []}

    def clear_preview():
        for child in preview_flow.get_children():
            preview_flow.remove(child)

    def set_dialog_progress(fraction, text):
        progress_bar.set_fraction(max(0.0, min(1.0, fraction)))
        progress_bar.set_text(text)
        _drain_gtk_events(Gtk)

    def detection_progress(fraction, text):
        set_dialog_progress(0.15 + 0.7 * fraction, text)

    def update_preview_tile(item, image_widget, label_widget):
        pixbuf = _pixbuf_from_rgba(item["bytes"], item["width"], item["height"])
        scale = min(170 / item["width"], 170 / item["height"], 1.0)
        thumb_width = max(1, int(item["width"] * scale))
        thumb_height = max(1, int(item["height"] * scale))
        thumb = pixbuf.scale_simple(thumb_width, thumb_height, GdkPixbuf.InterpType.BILINEAR)
        image_widget.set_from_pixbuf(thumb)
        label_widget.set_text(
            f"{item['index'] + 1}: {item['width']} x {item['height']} "
            f"({item['rotation']} deg, deskew {item['deskew_angle']:.1f} deg)"
        )

    def rotate_preview_item(button, item, image_widget, label_widget):
        item["bytes"], item["width"], item["height"] = rotate_rgba_clockwise(
            item["bytes"],
            item["width"],
            item["height"],
        )
        item["rotation"] = (item["rotation"] + 90) % 360
        update_preview_tile(item, image_widget, label_widget)

    def update_keep_selection(button, item):
        item["keep"] = button.get_active()

    def update_enhance_selection(button, item):
        item["enhance"] = button.get_active()

    def render_preview():
        clear_preview()
        set_dialog_progress(0.0, "Detecting crops...")
        settings = _settings_from_config(config)
        fingerprint = _detection_fingerprint(settings)
        rgba, width, height = _read_drawable_rgba(drawable)
        if settings["manual_bg"]:
            background = settings["manual_bg_color"]
        else:
            background = sample_background(
                rgba,
                width,
                height,
                settings["corner"],
                settings["sample_x"],
                settings["sample_y"],
            )

        set_dialog_progress(0.15, "Finding foreground regions...")
        crops = detect_crops(
            rgba,
            width,
            height,
            background,
            threshold=settings["threshold"],
            min_size=settings["min_size"],
            limit=settings["limit"],
            padding=settings["padding"],
            square=settings["square"],
            progress_callback=detection_progress,
        )
        preview_label.set_text(f"{len(crops)} crop(s) detected. Preview is in-memory and does not save files.")

        def crop_progress(fraction, text):
            set_dialog_progress(0.85 + 0.15 * fraction, text)

        preview_cache["fingerprint"] = fingerprint
        preview_cache["items"] = _prepare_crop_items_parallel(
            crops,
            rgba,
            width,
            height,
            background,
            settings,
            progress_callback=crop_progress,
        )
        for item in preview_cache["items"]:
            item["keep"] = True
            item["enhance"] = True

        for index, item in enumerate(preview_cache["items"]):
            crop_image = Gtk.Image()
            crop_label = Gtk.Label()
            crop_label.set_xalign(0.5)
            rotate_button = Gtk.Button(label="Rotate")
            rotate_button.connect("clicked", rotate_preview_item, item, crop_image, crop_label)
            keep_check = Gtk.CheckButton(label="Keep")
            keep_check.set_active(True)
            keep_check.connect("toggled", update_keep_selection, item)
            enhance_check = Gtk.CheckButton(label="Enhance")
            enhance_check.set_active(True)
            enhance_check.connect("toggled", update_enhance_selection, item)
            update_preview_tile(item, crop_image, crop_label)

            control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            control_box.pack_start(keep_check, False, False, 0)
            control_box.pack_start(enhance_check, False, False, 0)
            control_box.pack_start(rotate_button, False, False, 0)

            crop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            crop_box.pack_start(crop_image, False, False, 0)
            crop_box.pack_start(crop_label, False, False, 0)
            crop_box.pack_start(control_box, False, False, 0)

            frame = Gtk.Frame()
            frame.add(crop_box)
            preview_flow.add(frame)
            set_dialog_progress(
                0.15 + (0.85 * (index + 1) / max(1, len(crops))),
                f"Prepared preview {index + 1} of {len(crops)}",
            )

        preview_flow.show_all()
        set_dialog_progress(1.0, "Preview ready")

    dialog.show_all()
    accepted = False
    cached_items = None
    try:
        while True:
            response = Gtk.Dialog.run(dialog)
            if response == preview_response:
                render_preview()
                continue
            accepted = response in (
                Gtk.ResponseType.OK,
                Gtk.ResponseType.ACCEPT,
                Gtk.ResponseType.APPLY,
            )
            if accepted:
                settings = _settings_from_config(config)
                if preview_cache["fingerprint"] != _detection_fingerprint(settings):
                    render_preview()
                cached_items = list(preview_cache["items"])
            break
    finally:
        dialog.destroy()

    return accepted, cached_items


def _error_return(procedure, exc):
    Gimp.message(f"Divide Scanned Images failed: {exc}")
    traceback.print_exc()
    return procedure.new_return_values(
        Gimp.PDBStatusType.EXECUTION_ERROR,
        GLib.Error(str(exc)),
    )


def _rgba_from_gegl_color(color):
    if color is None:
        return (255, 255, 255, 255)

    if Babl is not None:
        try:
            data = color.get_bytes(Babl.format(RGBA_FORMAT))
            if hasattr(data, "get_data"):
                raw = data.get_data()
            else:
                raw = bytes(data)
            return normalize_rgba(raw[:4])
        except Exception:
            pass

    red, green, blue, alpha = color.get_rgba()
    return normalize_rgba(
        (
            round(red * 255),
            round(green * 255),
            round(blue * 255),
            round(alpha * 255),
        )
    )


def _read_drawable_rgba(drawable):
    width = drawable.get_width()
    height = drawable.get_height()
    rect = Gegl.Rectangle.new(0, 0, width, height)
    return drawable.get_buffer().get(rect, 1.0, RGBA_FORMAT, Gegl.AbyssPolicy.NONE), width, height


def _new_crop_image(rgba_bytes, width, height, source_image, name):
    image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
    try:
        ok, xres, yres = source_image.get_resolution()
        if ok:
            image.set_resolution(xres, yres)
    except Exception:
        pass

    layer = Gimp.Layer.new(
        image,
        name,
        width,
        height,
        Gimp.ImageType.RGBA_IMAGE,
        100.0,
        Gimp.LayerMode.NORMAL,
    )
    image.insert_layer(layer, None, 0)
    layer.get_buffer().set(Gegl.Rectangle.new(0, 0, width, height), RGBA_FORMAT, rgba_bytes)
    layer.get_buffer().flush()
    layer.update(0, 0, width, height)
    return image, layer


def _save_image(image, path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, Gio.File.new_for_path(path), None)


def _write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def _gimp_progress(fraction, text=None):
    if text:
        try:
            Gimp.progress_set_text(text)
        except Exception:
            pass
    try:
        Gimp.progress_update(max(0.0, min(1.0, fraction)))
    except Exception:
        pass
    _process_ui_events()


def _run_background_call(callable_obj, waiting_text):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callable_obj)
        while not future.done():
            _gimp_progress(0.0, waiting_text)
            future.result(timeout=0.25) if future.done() else _process_ui_events()
        return future.result()


def _source_directory(image):
    file_obj = image.get_file()
    if file_obj is None:
        return None
    path = file_obj.get_path()
    if not path:
        return None
    return os.path.dirname(path)


def _settings_from_config(config):
    return {
        "square": config.get_property("square-crop"),
        "padding": config.get_property("padding"),
        "limit": config.get_property("limit"),
        "auto_close": config.get_property("auto-close"),
        "threshold": config.get_property("threshold"),
        "min_size": config.get_property("min-size"),
        "deskew": config.get_property("deskew"),
        "deskew_max_angle": config.get_property("deskew-max-angle"),
        "deskew_crop_padding": config.get_property("deskew-crop-padding"),
        "enhance_openai": config.get_property("enhance-openai"),
        "manual_bg": config.get_property("manual-background"),
        "manual_bg_color": _rgba_from_gegl_color(config.get_property("background-color")),
        "corner": config.get_property("sample-corner"),
        "sample_x": config.get_property("sample-x"),
        "sample_y": config.get_property("sample-y"),
        "save_in_source": config.get_property("save-in-source"),
        "target_dir": _file_path(config.get_property("target-dir")),
        "save_type": config.get_property("save-type"),
        "file_base": config.get_property("file-base"),
        "start_number": config.get_property("start-number"),
    }


def _file_path(file_obj):
    if file_obj is None:
        return ""
    return file_obj.get_path() or ""


def _output_path(settings, source_image, ordinal):
    save_type = settings["save_type"]
    extension = ".jpg" if save_type == "jpg" else ".png"
    target_dir = settings["target_dir"]
    if settings["save_in_source"]:
        source_dir = _source_directory(source_image)
        if source_dir:
            target_dir = source_dir
    if not target_dir:
        raise RuntimeError("Choose a target directory or save the source image before splitting.")
    file_number = settings["start_number"] + ordinal
    filename = f"{settings['file_base']}{file_number:05d}{extension}"
    return os.path.join(target_dir, filename)


def _openai_api_key():
    key = os.environ.get(OPENAI_KEY_ENV, "")
    if not key:
        raise RuntimeError(f"{OPENAI_KEY_ENV} is not set. Disable OpenAI enhancement or set the environment variable.")
    return key


def _selected_layer(image, drawables=None):
    if drawables:
        for drawable in drawables:
            if isinstance(drawable, Gimp.Layer):
                return drawable

    layers = image.get_selected_layers()
    if layers:
        return layers[0]

    layers = image.get_layers()
    if layers:
        return layers[0]

    raise RuntimeError("No usable layer found.")


def _worker_count(task_count):
    if task_count <= 0:
        return 1
    return min(task_count, max(1, (os.cpu_count() or 2) - 1))


def _prepare_crop_items_sequential(crops, rgba, width, height, background, settings, progress_callback=None):
    items = _extract_crop_items(crops, rgba, width, height, background, progress_callback)
    total = len(items)
    processed = []
    for index, item in enumerate(items):
        processed.append(postprocess_crop_item(item, background, settings))
        if progress_callback is not None:
            progress_callback((index + 1) / max(1, total), f"Processed crop {index + 1} of {total}")
    return processed


def _extract_crop_items(crops, rgba, width, height, background, progress_callback=None):
    items = []
    for index, crop in enumerate(crops):
        crop_bytes, crop_width, crop_height = extract_crop_rgba(rgba, width, height, crop, background)
        items.append(
            {
                "index": index,
                "bytes": crop_bytes,
                "width": crop_width,
                "height": crop_height,
                "rotation": 0,
                "deskew_angle": 0.0,
            }
        )
        if progress_callback is not None:
            progress_callback(0.2 * ((index + 1) / max(1, len(crops))), f"Extracted crop {index + 1} of {len(crops)}")
    return items


def _prepare_crop_items_parallel(crops, rgba, width, height, background, settings, progress_callback=None):
    total = len(crops)
    if total == 0:
        return []
    background_rgba = tuple(background)
    worker_settings = dict(settings)
    extracted_items = _extract_crop_items(crops, rgba, width, height, background_rgba, progress_callback)
    max_workers = _worker_count(total)
    if max_workers == 1:
        processed = []
        for index, item in enumerate(extracted_items):
            processed.append(postprocess_crop_item(item, background_rgba, worker_settings))
            if progress_callback is not None:
                progress_callback(0.2 + 0.8 * ((index + 1) / total), f"Processed crop {index + 1} of {total}")
        return processed

    items = [None] * total
    completed = 0
    if progress_callback is not None:
        progress_callback(0.2, f"Processing {total} crop(s) with {max_workers} process worker(s)...")

    try:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=max_workers, mp_context=context) as executor:
            pending = {
                executor.submit(postprocess_crop_item, item, background_rgba, worker_settings)
                for item in extracted_items
            }
            while pending:
                done, pending = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                if not done:
                    if progress_callback is not None:
                        progress_callback(0.2 + 0.8 * (completed / total), f"Processing crops... {completed} of {total} complete")
                    continue
                for future in done:
                    item = future.result()
                    items[item["index"]] = item
                    completed += 1
                    if progress_callback is not None:
                        progress_callback(0.2 + 0.8 * (completed / total), f"Processed crop {completed} of {total}")
    except Exception as exc:
        if progress_callback is not None:
            progress_callback(0.0, f"Process workers unavailable; falling back to sequential processing ({exc})")
        processed = []
        for index, item in enumerate(extracted_items):
            processed.append(postprocess_crop_item(item, background_rgba, worker_settings))
            if progress_callback is not None:
                progress_callback((index + 1) / total, f"Processed crop {index + 1} of {total}")
        return processed

    return items


def _save_crop_items(image, settings, crop_items):
    selected_items = [item for item in crop_items if item.get("keep", True)]
    outputs = []
    total = len(selected_items)
    if total == 0:
        raise RuntimeError("No preview crops are selected. Select at least one Keep checkbox before splitting.")
    api_key = _openai_api_key() if settings["enhance_openai"] else None
    for index, item in enumerate(selected_items):
        _gimp_progress(index / max(1, total), f"Saving crop {index + 1} of {total}...")
        out_image, _out_layer = _new_crop_image(
            item["bytes"],
            item["width"],
            item["height"],
            image,
            f"Crop {index + 1}",
        )
        path = _output_path(settings, image, index)
        _gimp_progress(index / max(1, total), f"Saving {os.path.basename(path)}...")
        _save_image(out_image, path)
        outputs.append(path)
        if api_key and item.get("enhance", True):
            enhanced_path = enhanced_output_path(path)
            _gimp_progress(
                index / max(1, total),
                f"Enhancing crop {index + 1} of {total} with OpenAI...",
            )
            png_bytes = rgba_to_png_bytes(item["bytes"], item["width"], item["height"])
            enhanced_bytes = _run_background_call(
                lambda data=png_bytes, width=item["width"], height=item["height"]: enhance_png_with_openai(
                    data,
                    api_key,
                    width,
                    height,
                ),
                f"Waiting for OpenAI enhancement {index + 1} of {total}...",
            )
            _write_bytes(enhanced_path, enhanced_bytes)
            outputs.append(enhanced_path)
            _gimp_progress(
                (index + 0.5) / max(1, total),
                f"Saved enhanced crop {index + 1} of {total}",
            )
        if settings["auto_close"]:
            out_image.delete()
        else:
            Gimp.Display.new(out_image)
        _gimp_progress((index + 1) / max(1, total), f"Saved crop {index + 1} of {total}")

    Gimp.displays_flush()
    return outputs


def _detect_crop_items(image, drawable, settings):
    _gimp_progress(0.0, "Reading source image...")
    rgba, width, height = _read_drawable_rgba(drawable)
    if settings["manual_bg"]:
        background = settings["manual_bg_color"]
    else:
        background = sample_background(
            rgba,
            width,
            height,
            settings["corner"],
            settings["sample_x"],
            settings["sample_y"],
        )

    _gimp_progress(0.15, "Detecting crops...")
    def detection_progress(fraction, text):
        _gimp_progress(0.15 + 0.55 * fraction, text)

    crops = detect_crops(
        rgba,
        width,
        height,
        background,
        threshold=settings["threshold"],
        min_size=settings["min_size"],
        limit=settings["limit"],
        padding=settings["padding"],
        square=settings["square"],
        progress_callback=detection_progress,
    )

    def crop_progress(fraction, text):
        _gimp_progress(0.70 + 0.20 * fraction, text)

    return _prepare_crop_items_parallel(
        crops,
        rgba,
        width,
        height,
        background,
        settings,
        progress_callback=crop_progress,
    )


def _divide_image(image, drawable, settings, cached_items=None):
    try:
        Gimp.progress_init("Divide Scanned Images")
    except Exception:
        pass

    try:
        if cached_items is None:
            crop_items = _detect_crop_items(image, drawable, settings)
        else:
            crop_items = cached_items
            _gimp_progress(0.0, "Using previewed crops...")

        outputs = _save_crop_items(image, settings, crop_items)
        _gimp_progress(1.0, "Done")
        return outputs
    finally:
        try:
            Gimp.progress_end()
        except Exception:
            pass


def divide_run(procedure, run_mode, image, drawables, config, data):
    try:
        drawable = _selected_layer(image, drawables)
        cached_items = None
        if run_mode == Gimp.RunMode.INTERACTIVE:
            accepted, cached_items = _run_image_dialog(procedure, config, image, drawable)
            if not accepted:
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)

        settings = _settings_from_config(config)
        image.undo_group_start()
        try:
            outputs = _divide_image(image, drawable, settings, cached_items)
        finally:
            image.undo_group_end()

        Gimp.message(f"Divide Scanned Images: saved {len(outputs)} file(s).")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    except Exception as exc:
        return _error_return(procedure, exc)


def batch_run(procedure, config, data):
    try:
        if config.get_property("run-mode") == Gimp.RunMode.INTERACTIVE:
            fields = [
                "source-dir",
                "load-type",
                "square-crop",
                "padding",
                "limit",
                "auto-close",
                "threshold",
                "min-size",
                "deskew",
                "deskew-max-angle",
                "deskew-crop-padding",
                "enhance-openai",
                "manual-background",
                "background-color",
                "sample-corner",
                "sample-x",
                "sample-y",
                "save-in-source",
                "target-dir",
                "save-type",
                "file-base",
                "start-number",
            ]
            if not _run_dialog(procedure, config, "Batch Divide Scanned Images", fields):
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)

        settings = _settings_from_config(config)
        source_dir = _file_path(config.get_property("source-dir"))
        load_type = config.get_property("load-type")
        extensions = LOAD_TYPES.get(load_type, LOAD_TYPES["all"])
        if not source_dir:
            raise RuntimeError("Source directory is required.")

        files = iter_supported_files(source_dir, extensions)
        total_outputs = 0
        current_number = settings["start_number"]

        for path in files:
            Gimp.progress_init(f"Dividing {os.path.basename(path)}")
            image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(path))
            try:
                drawable = _selected_layer(image)
                settings["start_number"] = current_number
                outputs = _divide_image(image, drawable, settings)
                total_outputs += len(outputs)
                current_number += len(outputs)
            finally:
                image.delete()

        Gimp.message(f"Batch Divide Scanned Images: saved {total_outputs} file(s) from {len(files)} source file(s).")
        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)
    except Exception as exc:
        return _error_return(procedure, exc)


def _add_common_arguments(procedure, include_target=True):
    flags = GObject.ParamFlags.READWRITE
    procedure.add_boolean_argument("square-crop", "Force square crop", None, False, flags)
    procedure.add_int_argument("padding", "Border padding (pixels)", None, 0, 1000, 0, flags)
    procedure.add_int_argument("limit", "Max number of items", None, 1, 100, 10, flags)
    procedure.add_boolean_argument("auto-close", "Auto-close sub-images after saving", None, True, flags)
    procedure.add_int_argument("threshold", "Selection threshold", None, 0, 255, 25, flags)
    procedure.add_int_argument("min-size", "Size threshold", None, 0, 5000, 100, flags)
    procedure.add_boolean_argument("deskew", "Deskew after splitting", None, False, flags)
    procedure.add_int_argument("deskew-max-angle", "Max deskew angle", None, 0, 45, 15, flags)
    procedure.add_int_argument("deskew-crop-padding", "Whitespace crop padding after deskew", None, 0, 1000, 0, flags)
    procedure.add_boolean_argument("enhance-openai", "Enhance with OpenAI after split", None, False, flags)
    procedure.add_boolean_argument("manual-background", "Manually define background color", None, False, flags)
    procedure.add_color_argument("background-color", "Manual background color", None, False, Gegl.Color.new("white"), flags)
    procedure.add_choice_argument(
        "sample-corner",
        "Auto-background sample corner",
        None,
        _choice(CORNER_LABELS.items()),
        "top-left",
        flags,
    )
    procedure.add_int_argument("sample-x", "Auto-background sample x-offset", None, 0, 10000, 25, flags)
    procedure.add_int_argument("sample-y", "Auto-background sample y-offset", None, 0, 10000, 25, flags)
    procedure.add_boolean_argument("save-in-source", "Save output to source directory", None, True, flags)
    if include_target:
        procedure.add_file_argument(
            "target-dir",
            "Target directory",
            "Used when not saving output to the source directory.",
            Gimp.FileChooserAction.SELECT_FOLDER,
            True,
            None,
            flags,
        )
    procedure.add_choice_argument(
        "save-type",
        "Save file type",
        None,
        _choice((("jpg", "jpg"), ("png", "png"))),
        "jpg",
        flags,
    )
    procedure.add_string_argument("file-base", "Save file base name", None, "Crop", flags)
    procedure.add_int_argument("start-number", "Save file start number", None, 0, 999999, 1, flags)


class DivideScannedImages(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROC_IMAGE, PROC_BATCH]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        flags = GObject.ParamFlags.READWRITE
        if name == PROC_IMAGE:
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, divide_run, None)
            procedure.set_image_types("RGB*, GRAY*")
            procedure.set_sensitivity_mask(
                Gimp.ProcedureSensitivityMask.DRAWABLE
                | Gimp.ProcedureSensitivityMask.DRAWABLES
            )
            procedure.set_menu_label("Divide Scanned Images...")
            procedure.add_menu_path("<Image>/Filters/")
            procedure.set_documentation(
                "Divide scanned images",
                "Detects separate foreground items on a mostly uniform scan background, creates one image per item, and saves each crop.",
                None,
            )
            procedure.set_attribution("Francois Malan; GIMP 3 port", "Francois Malan; GIMP 3 port", "2016, 2026")
            _add_common_arguments(procedure)
            return procedure

        if name == PROC_BATCH:
            procedure = Gimp.Procedure.new(self, name, Gimp.PDBProcType.PLUGIN, batch_run, None)
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)
            procedure.set_menu_label("Batch Divide Scanned Images...")
            procedure.add_menu_path("<Image>/Filters/Batch Tools/")
            procedure.set_documentation(
                "Batch divide scanned images",
                "Loads supported images from a folder and applies Divide Scanned Images to each file.",
                None,
            )
            procedure.set_attribution("Francois Malan; GIMP 3 port", "Francois Malan; GIMP 3 port", "2016, 2026")
            procedure.add_enum_argument("run-mode", "Run mode", None, Gimp.RunMode.__gtype__, Gimp.RunMode.INTERACTIVE, flags)
            procedure.add_file_argument(
                "source-dir",
                "Load from",
                None,
                Gimp.FileChooserAction.SELECT_FOLDER,
                False,
                Gio.File.new_for_path(GLib.get_home_dir()),
                flags,
            )
            procedure.add_choice_argument(
                "load-type",
                "Load file type",
                None,
                _choice((("all", "all"), ("jpg", "jpg"), ("jpeg", "jpeg"), ("bmp", "bmp"), ("png", "png"), ("tif", "tif"), ("tiff", "tiff"))),
                "all",
                flags,
            )
            _add_common_arguments(procedure)
            return procedure

        return None

if __name__ == "__main__":
    multiprocessing.freeze_support()
    Gimp.main(DivideScannedImages.__gtype__, sys.argv)
