import bpy
import bpy.utils.previews
import json
import math
import os
import re
import time
import struct
import zlib
import hashlib
import uuid
from . import heightmap_analysis as heightmap_tools
from . import test_output as test_output_tools
import tempfile
from pathlib import Path
from bpy_extras.io_utils import ExportHelper, ImportHelper
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList, FileHandler
from mathutils import Vector, Matrix

try:
    import numpy as np
except Exception:
    np = None

ADDON_VERSION = (1, 18, 43)
bl_info = {"name": "Lenticulizer", "author": "Independent", "version": ADDON_VERSION, "blender": (5, 0, 0), "location": "3D View > Sidebar > Lenticulizer", "description": "Lenticular print processing and shared heightmap preview", "category": "3D View"}
COLLECTION_NAME = "Lenticular Simulation"
REFERENCE_COLLECTION_NAME = "Lenticular Heightmap Reference"
OBJECT_PREFIX = "LT_"
_SYNC_INTERVAL = 0.25
_state = {
    "dirty": False,
    "applying": False,
    "last_mtime": 0.0,
    "last_revision": 0,
    "last_change_time": 0.0,
    "dirty_scope": "geometry",
    "pending_interlace": False,
    "pending_heightmap": False,
    "pending_lens": False,
    "heightmap_due_time": 0.0,
    "pending_texture": False,
    "reactive_busy": False,
    "reactive_origin": "local",
    "mode_rebuild_timer_registered": False,
    "mode_rebuild_serial": 0,
    "mode_rebuild_consumed_serial": 0,
    "mode_rebuild_requested_mode": "",
    "mode_transaction_active": False,
    "mode_transaction_started": 0.0,
    "optics_initialized": False,
    "viewport_tracker_running": False,
    "viewport_tracker_stop": False,
    "viewport_picker_running": False,
    "explicit_target_view3d_area_ptr": 0,
    "viewport_layout_signature": None,
    "last_view3d_area_ptr": 0,
    "project_closed_at": 0.0,
    "app_rebuild_pair_requested": False,
    "app_rebuild_heightmap_requested": False,
    "panel_area_ptr": 0,
    "workspace_layout_busy": False,
    "workspace_layout_timer_registered": False,
    "source_image_area_ptr": 0,
    "interlaced_image_area_ptr": 0,
    "heightmap_image_area_ptr": 0,
    "vertical_inspection_area_ptr": 0,
    "primary_view_area_ptr": 0,
    "horizontal_inspection_area_ptr": 0,
    "source_viewer_key": "",
    "interlaced_viewer_key": "",
    "heightmap_viewer_key": "",
    "inspection_fit_timer_registered": False,
    "source_selector_items": [],
}

_preview_collection = None
_reference_axis_cache = {}
_reference_cross_section_meta_cache = {}


RELIEF_BASELINE_VIEWS = 2


def _relief_supported_view_count():
    return RELIEF_BASELINE_VIEWS


def _recommended_relief_prism_height_mm(settings, lpi=None):
    # Conservative automatic baseline: two opposing facets centered around +/-30 degrees.
    # For a triangular two-view prism, tan(angle) = height / half_pitch.
    lpi_value = max(0.001, float(settings.lpi if lpi is None else lpi))
    pitch_mm = 25.4 / lpi_value
    half_pitch_mm = pitch_mm * 0.5
    height = half_pitch_mm * math.tan(math.radians(30.0))
    return max(MIN_NONZERO_PEAK_MM, min(MAX_PEAK_MM, height))


def _safe_float(value, default=0.0):
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except Exception:
        pass
    return default


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _project_path(settings):
    text = bpy.path.abspath(settings.project_file or "").strip()
    return Path(text) if text else None


def _project_dir(settings):
    path = _project_path(settings)
    return path.parent if path else None


def _set_status(settings, text):
    settings.status = text[:250]


def _reference_collection(scene):
    return bpy.data.collections.get(REFERENCE_COLLECTION_NAME)


def _remove_reference_collection():
    collection = bpy.data.collections.get(REFERENCE_COLLECTION_NAME)
    if collection is None:
        return
    for obj in list(collection.objects):
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except Exception:
            pass
    try:
        bpy.data.collections.remove(collection)
    except Exception:
        pass


def _ensure_reference_collection(scene):
    collection = _reference_collection(scene)
    if collection is not None:
        return collection
    collection = bpy.data.collections.new(REFERENCE_COLLECTION_NAME)
    scene.collection.children.link(collection)
    return collection


def _read_png_size_metadata(path):
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with path.open('rb') as fh:
            sig = fh.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None
            x_ppm = y_ppm = None
            while True:
                raw_len = fh.read(4)
                if len(raw_len) != 4:
                    break
                length = struct.unpack('>I', raw_len)[0]
                ctype = fh.read(4)
                data = fh.read(length)
                fh.read(4)
                if ctype == b'pHYs' and length >= 9:
                    x_ppm, y_ppm, unit = struct.unpack('>IIB', data[:9])
                    if unit == 1 and x_ppm > 0 and y_ppm > 0:
                        return {
                            'width_mm_per_px': 1000.0 / float(x_ppm),
                            'height_mm_per_px': 1000.0 / float(y_ppm),
                            'x_ppm': x_ppm,
                            'y_ppm': y_ppm,
                        }
                if ctype == b'IEND':
                    break
    except Exception:
        return None
    return None


def _read_png_lenticular_metadata(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".png":
        return None
    values = {}
    try:
        with path.open("rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            while True:
                raw_len = fh.read(4)
                if len(raw_len) != 4:
                    break
                length = struct.unpack(">I", raw_len)[0]
                ctype = fh.read(4)
                data = fh.read(length)
                fh.read(4)
                if ctype == b"tEXt" and b"\x00" in data:
                    key_b, value_b = data.split(b"\x00", 1)
                    key = key_b.decode("latin-1", errors="ignore")
                    if key.startswith("Lenticular"):
                        values[key] = value_b.decode("utf-8", errors="ignore")
                if ctype == b"IEND":
                    break
    except Exception:
        return None
    if not values:
        return None
    result = {}
    try:
        if "LenticularLPI" in values:
            result["lpi"] = float(values["LenticularLPI"])
    except Exception:
        pass
    try:
        if "LenticularViews" in values:
            result["views"] = int(values["LenticularViews"])
    except Exception:
        pass
    try:
        if "LenticularWidthIn" in values:
            result["width_mm"] = float(values["LenticularWidthIn"]) * 25.4
        if "LenticularHeightIn" in values:
            result["height_mm"] = float(values["LenticularHeightIn"]) * 25.4
    except Exception:
        pass
    if "LenticularOrientation" in values:
        result["orientation"] = "HORIZONTAL" if values["LenticularOrientation"].lower().startswith("h") else "VERTICAL"
    return result or None


def _infer_views_from_filename(path):
    name = Path(path).stem
    match = re.search(r"(?:^|[_\-\s])(\d{1,2})\s*(?:views?|frames?)(?:$|[_\-\s])", name, re.IGNORECASE)
    if match:
        value = _safe_int(match.group(1), 0)
        if 2 <= value <= 8:
            return value
    match = re.search(r"(?:views?|frames?)[_\-\s]*(\d{1,2})", name, re.IGNORECASE)
    if match:
        value = _safe_int(match.group(1), 0)
        if 2 <= value <= 8:
            return value
    return 0


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _is_supported_image(path):
    try:
        return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    except Exception:
        return False


def _source_frame_paths(settings):
    return [item.path for item in settings.source_frames if item.path]


def _resolve_preview_path(settings, path_str):
    try:
        raw = str(path_str).strip()
        if not raw:
            return None
        if raw.startswith("//"):
            candidate = Path(bpy.path.abspath(raw))
        else:
            candidate = Path(raw)
        if not candidate.is_absolute():
            project_dir = _project_dir(settings)
            if project_dir:
                candidate = project_dir / candidate
        return candidate
    except Exception:
        return None


def _image_for_path(settings, path_str):
    candidate = _resolve_preview_path(settings, path_str)
    if candidate is None or not candidate.is_file():
        return None
    try:
        resolved = str(candidate.resolve())
        image = bpy.data.images.load(resolved, check_existing=True)
        try:
            image.reload()
        except Exception:
            pass
        return image
    except Exception:
        return None


def _ensure_preview_collection():
    global _preview_collection
    if _preview_collection is None:
        try:
            _preview_collection = bpy.utils.previews.new()
        except Exception:
            _preview_collection = None
    return _preview_collection


def _preview_icon_for_file(path, namespace="image"):
    candidate = Path(path) if path else None
    if candidate is None or not candidate.is_file():
        return 0
    previews = _ensure_preview_collection()
    if previews is None:
        return 0
    try:
        resolved = candidate.resolve()
        mtime = resolved.stat().st_mtime_ns
        key = namespace + "|" + str(resolved) + "|" + str(mtime)
        if key not in previews:
            previews.load(key, str(resolved), 'IMAGE')
        return previews[key].icon_id
    except Exception:
        return 0


def _image_icon_id(settings, path_str):
    candidate = _resolve_preview_path(settings, path_str)
    return _preview_icon_for_file(candidate, "asset") if candidate is not None else 0


def _draw_image_thumbnail(layout, settings, path_str, title, scale=6.0, build_controls=False, show_title=True, show_viewer=True):
    box = layout.box()
    if show_title:
        box.label(text=title)
    resolved = _resolve_preview_path(settings, path_str)
    display_name = resolved.name if resolved is not None else Path(str(path_str)).name
    icon_id = _preview_icon_for_file(resolved, "asset") if resolved is not None else 0
    effective_scale = float(scale)
    if build_controls:
        effective_scale *= max(0.5, min(2.0, float(getattr(settings, "build_preview_zoom", 1.0))))
    if icon_id:
        row = box.row()
        row.alignment = 'CENTER'
        try:
            row.template_icon(icon_value=icon_id, scale=effective_scale)
        except Exception:
            row.label(text=display_name, icon_value=icon_id)
        box.label(text=display_name)
    else:
        box.label(text="No preview available", icon="IMAGE_DATA")
        if resolved is not None:
            box.label(text=str(resolved))

    if build_controls and resolved is not None and resolved.is_file():
        controls = box.row(align=True)
        minus = controls.operator("lenticular.preview_zoom", text="", icon="ZOOM_OUT")
        minus.delta = -0.25
        controls.label(text=f"{int(round(float(settings.build_preview_zoom) * 100.0))}%")
        plus = controls.operator("lenticular.preview_zoom", text="", icon="ZOOM_IN")
        plus.delta = 0.25
        reset = controls.operator("lenticular.preview_zoom", text="100%")
        reset.reset = True
        if show_viewer:
            viewer = controls.operator("lenticular.open_image_viewer", text="Open Viewer", icon="IMAGE_DATA")
            viewer.filepath = str(resolved)
            viewer.viewer_title = title


def _snap_pixels_per_lenticule(value, views):
    value = _safe_float(value, 48.0)
    if value <= 0:
        value = 48.0
    step = max(1, int(views))
    rounded = int(round(value / step) * step)
    if rounded < step * 4:
        rounded = step * 4
    if rounded < 24:
        rounded = 24
    if rounded > 256:
        rounded = 256
    return rounded


def _recommended_pixels_per_lenticule(settings):
    views = max(1, int(settings.views))
    mode = str(getattr(settings, "build_detail_mode", "BALANCED") or "BALANCED")
    if mode == "CUSTOM":
        return _snap_pixels_per_lenticule(getattr(settings, "pixels_per_lenticule", 48), views)
    if mode == "QUICK":
        return _snap_pixels_per_lenticule(max(24, views * 6), views)
    if mode == "FINE":
        return _snap_pixels_per_lenticule(max(72, views * 10), views)
    if mode == "RECOMMENDED":
        dpi = max(1, int(getattr(settings, "printer_dpi", 1440)))
        lpi = max(0.001, float(settings.lpi))
        return _snap_pixels_per_lenticule(float(dpi) / lpi, views)
    return _snap_pixels_per_lenticule(max(48, views * 8), views)


def _exact_lpi_from_ppl(dpi, ppl):
    dpi = max(1, int(dpi))
    ppl = max(1, int(ppl))
    return float(dpi) / float(ppl)


def _recommended_lpi_targets(settings):
    relief = _lens_free_mode(settings)
    views = _relief_supported_view_count() if relief else max(1, int(getattr(settings, "views", 3)))
    dpi = max(1, int(getattr(settings, "printer_dpi", 1440)))
    if relief:
        easier_ppl = _snap_pixels_per_lenticule(112, views)
        balanced_ppl = _snap_pixels_per_lenticule(84, views)
        finer_ppl = _snap_pixels_per_lenticule(56, views)
    else:
        easier_ppl = _snap_pixels_per_lenticule(60, views)
        balanced_ppl = _snap_pixels_per_lenticule(40, views)
        finer_ppl = _snap_pixels_per_lenticule(24, views)
    return {
        "EASIER": (_exact_lpi_from_ppl(dpi, easier_ppl), easier_ppl),
        "BALANCED": (_exact_lpi_from_ppl(dpi, balanced_ppl), balanced_ppl),
        "FINER": (_exact_lpi_from_ppl(dpi, finer_ppl), finer_ppl),
    }


def _apply_lpi_helper(settings):
    if settings.workflow == "HEIGHTMAP":
        return
    if _state["applying"] or getattr(settings, "lpi_helper_mode", "RECOMMENDED") != "RECOMMENDED":
        return
    targets = _recommended_lpi_targets(settings)
    key = getattr(settings, "lpi_helper_preset", "BALANCED")
    if key not in targets:
        key = "BALANCED"
    lpi = float(targets[key][0])
    if abs(float(settings.lpi) - lpi) > 1e-6:
        previous = _state["applying"]
        _state["applying"] = True
        try:
            settings.lpi = lpi
        finally:
            _state["applying"] = previous


def _lpi_helper_mode_changed(self, context):
    if _state["applying"]:
        return
    _apply_lpi_helper(self)
    _mark_lpi_interlace(self, context)


def _lpi_helper_preset_changed(self, context):
    if _state["applying"]:
        return
    _apply_lpi_helper(self)
    _mark_lpi_interlace(self, context)

def _build_target_canvas_size(settings):
    width_in = float(settings.width_mm) / 25.4
    height_in = float(settings.height_mm) / 25.4
    lpi = max(0.001, float(settings.lpi))
    ppl = _recommended_pixels_per_lenticule(settings)
    vertical = settings.orientation == "VERTICAL"
    axis_in = width_in if vertical else height_in
    cross_in = height_in if vertical else width_in
    axis_px = max(1, int(round(axis_in * lpi * ppl)))
    cross_px = max(1, int(round(axis_px * (cross_in / max(axis_in, 1e-9)))))
    return (axis_px, cross_px) if vertical else (cross_px, axis_px)


def _crop_rect_for_aspect(src_w, src_h, dst_w, dst_h):
    src_aspect = float(src_w) / float(max(1, src_h))
    dst_aspect = float(dst_w) / float(max(1, dst_h))
    if src_aspect > dst_aspect:
        crop_h = float(src_h)
        crop_w = crop_h * dst_aspect
        crop_x = (src_w - crop_w) * 0.5
        crop_y = 0.0
    else:
        crop_w = float(src_w)
        crop_h = crop_w / dst_aspect
        crop_x = 0.0
        crop_y = (src_h - crop_h) * 0.5
    return crop_x, crop_y, crop_w, crop_h


def _sample_rgba(pixels, width, height, crop_rect, x, y, out_w, out_h):
    crop_x, crop_y, crop_w, crop_h = crop_rect
    sx = crop_x + ((x + 0.5) / float(out_w)) * crop_w
    sy = crop_y + ((y + 0.5) / float(out_h)) * crop_h
    ix = max(0, min(width - 1, int(sx)))
    iy = max(0, min(height - 1, int(sy)))
    idx = (iy * width + ix) * 4
    return pixels[idx], pixels[idx + 1], pixels[idx + 2], pixels[idx + 3]


def _build_interlaced_image(settings, live_preview=False):
    project_dir = _workspace_dir(settings)
    if not project_dir:
        raise RuntimeError("Could not create a lenticular working folder")
    frame_paths = [Path(p) for p in _source_frame_paths(settings) if Path(p).is_file()]
    if len(frame_paths) < 2:
        raise RuntimeError("Add at least 2 source images to build an interlaced image")
    if len(frame_paths) > 8:
        frame_paths = frame_paths[:8]
    views = len(frame_paths)
    if _lens_free_mode(settings) and views != _relief_supported_view_count():
        raise RuntimeError(f"Lens-Free Relief requires exactly {_relief_supported_view_count()} source images in the current production baseline; found {views}.")
    _state["applying"] = True
    try:
        settings.views = views
    finally:
        _state["applying"] = False

    imported = settings.workflow == "HEIGHTMAP"
    if imported:
        info = _analyze_reference_heightmap(settings)
        _apply_imported_heightmap_settings(settings)
        _validate_heightmap_build(settings, info)
        out_w, out_h = int(info["width_px"]), int(info["height_px"])
    else:
        out_w, out_h = _build_target_canvas_size(settings)
    if live_preview and not imported:
        max_dim = 4096
        largest = max(out_w, out_h)
        if largest > max_dim:
            scale = max_dim / float(largest)
            out_w = max(8, int(round(out_w * scale)))
            out_h = max(8, int(round(out_h * scale)))
    elif not imported:
        max_dim = 12000
        largest = max(out_w, out_h)
        if largest > max_dim:
            scale = max_dim / float(largest)
            out_w = max(8, int(round(out_w * scale)))
            out_h = max(8, int(round(out_h * scale)))
            _set_status(settings, "Build resolution capped for Blender stability; the Windows app can generate the full production raster")

    vertical = settings.orientation == "VERTICAL"
    axis_mm = float(settings.width_mm) if vertical else float(settings.height_mm)
    axis_in = axis_mm / 25.4
    axis_px = out_w if vertical else out_h
    pitch_px = (float(axis_px) / max(axis_in, 1e-9)) / max(0.001, float(settings.lpi))
    if imported: pitch_px = float(settings.reference_heightmap_pitch_px)
    if pitch_px < 2.0:
        raise RuntimeError("The requested LPI is too high for the chosen print size. It would produce fewer than 2 pixels per lenticule.")

    if np is None:
        raise RuntimeError("Blender NumPy support is required for live interlaced-image building")

    output = np.zeros((out_h, out_w, 4), dtype=np.float32)
    output[:, :, 3] = 1.0
    axis_count = out_w if vertical else out_h
    axis_positions = np.arange(axis_count, dtype=np.float64)
    phases = np.mod(axis_positions / pitch_px, 1.0)
    stripe_map = np.floor(phases * views).astype(np.int32)
    stripe_map = np.clip(stripe_map, 0, views - 1)

    if _lens_free_mode(settings):
        # Use the same phase origin as the relief geometry. The horizontal case
        # is just the vertical calculation transposed to the Y axis. Do not flip
        # raster rows or add a phase offset. Only reverse the view INDEX because
        # the app defines horizontal source order as Top -> Bottom while the
        # physical facet sequence along +Y is Bottom -> Top.
        if not vertical:
            stripe_map = (views - 1) - stripe_map
    else:
        # Match the native app exactly for lenticular mode in both orientations.
        # Horizontal lenticules use the same phase-to-view assignment as the app,
        # with no extra row reversal or phase shift.
        stripe_map = (views - 1) - stripe_map

    if imported:
        stripe_map = heightmap_tools.stripe_indices(axis_count, pitch_px, float(settings.reference_heightmap_phase_pitch)+float(settings.phase_pitch), views, _lens_free_mode(settings), not vertical)

    for frame_index, frame in enumerate(frame_paths):
        img = bpy.data.images.load(str(frame), check_existing=True)
        width, height = int(img.size[0]), int(img.size[1])
        if width <= 0 or height <= 0:
            continue
        raw = np.empty(width * height * 4, dtype=np.float32)
        img.pixels.foreach_get(raw)
        source = raw.reshape((height, width, 4))
        # A heightmap may use unequal X/Y DPI. Crop artwork for the physical
        # print aspect, then sample it at the authoritative map dimensions.
        crop_x, crop_y, crop_w, crop_h = _crop_rect_for_aspect(width, height, (float(settings.width_mm)/max(1e-9,float(settings.height_mm)))*1000.0 if imported else out_w, 1000.0 if imported else out_h)
        x_idx = np.floor(crop_x + ((np.arange(out_w, dtype=np.float64) + 0.5) / out_w) * crop_w).astype(np.int32)
        y_idx = np.floor(crop_y + ((np.arange(out_h, dtype=np.float64) + 0.5) / out_h) * crop_h).astype(np.int32)
        x_idx = np.clip(x_idx, 0, width - 1)
        y_idx = np.clip(y_idx, 0, height - 1)
        if vertical:
            columns = np.where(stripe_map == frame_index)[0]
            if columns.size:
                output[:, columns, :] = source[y_idx[:, None], x_idx[columns][None, :], :]
        else:
            rows = np.where(stripe_map == frame_index)[0]
            if rows.size:
                output[rows, :, :] = source[y_idx[rows][:, None], x_idx[None, :], :]

    image_name = "LT_GeneratedInterlaced"
    old = bpy.data.images.get(image_name)
    if old is not None:
        try:
            bpy.data.images.remove(old)
        except Exception:
            pass
    image = bpy.data.images.new(image_name, width=out_w, height=out_h, alpha=True, float_buffer=False)
    image.pixels.foreach_set(output.ravel())
    out_path = project_dir / ("interlaced_from_heightmap_" + uuid.uuid4().hex + ".png" if imported else "interlaced_image.png")
    image.filepath_raw = str(out_path)
    image.file_format = 'PNG'
    image.save()
    rgba_u8 = np.clip(np.rint(output * 255.0), 0, 255).astype(np.uint8).ravel().tobytes()
    ppm = _pixels_per_meter(out_w, out_h, settings.width_mm, settings.height_mm)
    metadata = {
        "LenticularLPI": f"{float(settings.lpi):.6f}",
        "LenticularViews": str(int(views)),
        "LenticularWidthIn": f"{float(settings.width_mm) / 25.4:.6f}",
        "LenticularHeightIn": f"{float(settings.height_mm) / 25.4:.6f}",
        "LenticularOrientation": "Vertical" if settings.orientation == "VERTICAL" else "Horizontal",
        "LenticulizerOutputMode": "Lens-Free Relief" if _lens_free_mode(settings) else "Lenticular Lens",
        "LenticulizerReliefSpreadDeg": f"{_relief_view_spread_deg(settings):.6f}" if _lens_free_mode(settings) else "",
        "LenticulizerPrismHeightMm": f"{_relief_prism_height_mm(settings):.6f}" if _lens_free_mode(settings) else "",
    }
    _write_rgba_png(out_path, out_w, out_h, rgba_u8, ppm, metadata)
    settings.interlaced_image = _project_relative_path(settings, out_path)
    return out_path, out_w, out_h, int(round(pitch_px))


def _project_relative_path(settings, path):
    if not path:
        return ""
    p = Path(path)
    base = _project_dir(settings)
    if base:
        try:
            return str(p.resolve().relative_to(base.resolve())).replace("\\", "/")
        except Exception:
            pass
    return str(p)


def _resolve_project_relative(settings, value):
    if not value:
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    base = _project_dir(settings)
    return (base / p) if base else p


def _unique_copy_name(folder, source_path):
    folder.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    stem = source.stem or "image"
    suffix = source.suffix.lower() or ".png"
    candidate = folder / (stem + suffix)
    counter = 2
    while candidate.exists():
        try:
            if source.resolve() == candidate.resolve():
                return candidate
        except Exception:
            pass
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _copy_asset_into_project(settings, source_path, subfolder=None, preferred_name=None):
    source = Path(source_path)
    if not source.is_file():
        return source
    base = _project_dir(settings)
    if not base:
        return source
    target_dir = base / subfolder if subfolder else base
    target_dir.mkdir(parents=True, exist_ok=True)
    if preferred_name:
        target = target_dir / preferred_name
    else:
        target = _unique_copy_name(target_dir, source)
    try:
        if source.resolve() != target.resolve():
            import shutil
            shutil.copy2(source, target)
    except Exception:
        import shutil
        shutil.copy2(source, target)
    return target


def _consolidate_assets_into_project(settings):
    base = _project_dir(settings)
    if not base:
        return
    for item in settings.source_frames:
        if item.path and Path(item.path).is_file():
            stored = _copy_asset_into_project(settings, item.path, "source_frames")
            item.path = str(stored)
            item.display_name = stored.name
    if settings.interlaced_image:
        resolved = _resolve_project_relative(settings, settings.interlaced_image)
        if resolved and resolved.is_file():
            stored = _copy_asset_into_project(settings, resolved, None, "interlaced_image" + resolved.suffix.lower())
            settings.interlaced_image = _project_relative_path(settings, stored)


def _camera_objects():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if not collection:
        return []
    cams = [
        obj for obj in collection.objects
        if obj.type == "CAMERA" and (
            bool(obj.get("lenticular_view_camera", False))
            or obj.name.startswith(OBJECT_PREFIX + "View_")
            or obj.name in {OBJECT_PREFIX + "Left", OBJECT_PREFIX + "Front", OBJECT_PREFIX + "Center", OBJECT_PREFIX + "Right", OBJECT_PREFIX + "Down", OBJECT_PREFIX + "Up"}
        )
    ]
    return sorted(cams, key=lambda cam: float(cam.get("lenticular_angle_deg", 0.0)))


def _camera_position_label(index, count, vertical=True):
    if vertical:
        if count <= 1:
            return "Front"
        if count == 2:
            return ["Left", "Right"][index]
        if count == 3:
            return ["Left", "Front", "Right"][index]
        if count == 4:
            return ["Far Left", "Center Left", "Center Right", "Far Right"][index]
        if count == 5:
            return ["Far Left", "Left", "Front", "Right", "Far Right"][index]
        if count == 6:
            return ["Far Left", "Left", "Center Left", "Center Right", "Right", "Far Right"][index]
        if count == 7:
            return ["Far Left", "Left", "Center Left", "Front", "Center Right", "Right", "Far Right"][index]
        if count == 8:
            return ["Far Left", "Left", "Center Left", "Slight Left", "Slight Right", "Center Right", "Right", "Far Right"][index]
        midpoint = (count - 1) / 2.0
        if abs(index - midpoint) < 0.25:
            return "Front"
        return "Left" if index < midpoint else "Right"
    else:
        if count <= 1:
            return "Front"
        if count == 2:
            return ["Down", "Up"][index]
        if count == 3:
            return ["Down", "Front", "Up"][index]
        if count == 4:
            return ["Far Down", "Center Down", "Center Up", "Far Up"][index]
        if count == 5:
            return ["Far Down", "Down", "Front", "Up", "Far Up"][index]
        if count == 6:
            return ["Far Down", "Down", "Center Down", "Center Up", "Up", "Far Up"][index]
        if count == 7:
            return ["Far Down", "Down", "Center Down", "Front", "Center Up", "Up", "Far Up"][index]
        if count == 8:
            return ["Far Down", "Down", "Center Down", "Slight Down", "Slight Up", "Center Up", "Up", "Far Up"][index]
        midpoint = (count - 1) / 2.0
        if abs(index - midpoint) < 0.25:
            return "Front"
        return "Down" if index < midpoint else "Up"


def _camera_label(camera, cameras=None):
    cams = cameras or _camera_objects()
    try:
        index = cams.index(camera)
    except Exception:
        return "Camera"
    settings = getattr(bpy.context.scene, "lenticular_sync", None)
    vertical = True if settings is None else settings.orientation == "VERTICAL"
    return _camera_position_label(index, len(cams), vertical)


def _camera_control_area(context):
    """Return the explicitly selected target 3D viewport.

    Camera View and Viewport Match intentionally share the same Target Viewport
    selector. The Lenticulizer sidebar may live in a different split viewport; the
    selected target, not the panel location, decides which RegionView3D is changed.
    """
    try:
        return _selected_view3d_area(context)
    except Exception:
        return None


def _camera_used_by_area(scene, area):
    if area is None or area.type != "VIEW_3D":
        return scene.camera
    try:
        space = area.spaces.active
        if bool(getattr(space, "use_local_camera", False)):
            local_camera = getattr(space, "camera", None)
            if local_camera is not None:
                return local_camera
    except Exception:
        pass
    return scene.camera


def _area_is_camera_view(scene, area, camera=None):
    if area is None or area.type != "VIEW_3D":
        return False
    try:
        space = area.spaces.active
        region_3d = getattr(space, "region_3d", None)
        if region_3d is None or region_3d.view_perspective != "CAMERA":
            return False
        if camera is None:
            return True
        return _camera_used_by_area(scene, area) == camera
    except Exception:
        return False


def _pin_other_camera_viewports(context, target_area, previous_scene_camera):
    """Keep other camera-view viewports visually unchanged when scene.camera changes.

    A normal Blender camera-view viewport follows scene.camera. Before Camera View
    changes the render camera, convert every other camera-view area to a local camera
    using the camera it was already displaying. This prevents split viewports from
    jumping together while preserving their current view.
    """
    screen = context.window.screen if getattr(context, "window", None) else getattr(context, "screen", None)
    if screen is None:
        return

    for area in screen.areas:
        if area.type != "VIEW_3D" or area == target_area:
            continue
        try:
            space = area.spaces.active
            region_3d = getattr(space, "region_3d", None)
            if region_3d is None or region_3d.view_perspective != "CAMERA":
                continue

            if bool(getattr(space, "use_local_camera", False)):
                # It is already isolated from the scene camera. Leave it alone.
                continue

            if previous_scene_camera is not None:
                space.use_local_camera = True
                space.camera = previous_scene_camera
        except Exception:
            pass


def _activate_camera(context, camera):
    """Activate one generated camera in the explicitly selected target viewport only.

    The scene/render camera is updated so renders use the selected view. Only the
    Target Viewport is put into CAMERA mode. Other camera-view viewports are pinned
    to their existing local camera before the global render camera changes, preventing
    simultaneous viewport switching.
    """
    if not camera or camera.type != "CAMERA":
        return False

    target_area = _camera_control_area(context)
    previous_scene_camera = context.scene.camera
    _pin_other_camera_viewports(context, target_area, previous_scene_camera)

    context.scene.camera = camera

    if target_area is not None:
        try:
            space = target_area.spaces.active
            region_3d = getattr(space, "region_3d", None)
            region = _view3d_window_region(target_area)
            if region_3d is not None:
                # Use a viewport-local camera even though the render camera is also
                # changed. This keeps Camera View isolated from every other viewport.
                space.use_local_camera = True
                space.camera = camera
                region_3d.view_perspective = "CAMERA"
                region_3d.view_camera_offset = (0.0, 0.0)

                # Recenter the camera frame in this viewport when Blender permits the
                # operator override. Failure is harmless because CAMERA mode is already set.
                if region is not None:
                    try:
                        with context.temp_override(area=target_area, region=region, space_data=space):
                            bpy.ops.view3d.view_center_camera()
                        # Preserve the historical Lenticulizer camera presentation:
                        # after Blender centers/fits the full camera frame, enlarge it
                        # until the camera frame fills the selected viewport vertically.
                        # This is viewport-local because view_camera_zoom belongs to this
                        # RegionView3D, so other split viewports remain unchanged.
                        _fill_camera_view_top_to_bottom(context, target_area, region, region_3d)
                    except Exception:
                        pass
        except Exception:
            pass

    settings = context.scene.lenticular_sync
    settings.active_camera_name = camera.name
    if target_area is not None:
        _set_status(settings, "Camera view: " + _target_viewport_label(context) + " - " + _camera_label(camera))
    else:
        _set_status(settings, "Render camera: " + _camera_label(camera))
    return True


def _view3d_window_region(area):
    if area is None or area.type != "VIEW_3D":
        return None
    return next((region for region in area.regions if region.type == "WINDOW"), None)


def _area_from_pointer(screen, pointer):
    if not screen or not pointer:
        return None
    for area in screen.areas:
        try:
            if area.as_pointer() == pointer:
                return area
        except Exception:
            pass
    return None



def _area_rect(area):
    try:
        return (int(area.x), int(area.y), int(area.x + area.width), int(area.y + area.height))
    except Exception:
        return (0, 0, 0, 0)


def _rect_overlap_ratio(area_a, area_b):
    ax0, ay0, ax1, ay1 = _area_rect(area_a)
    bx0, by0, bx1, by1 = _area_rect(area_b)
    iw = max(0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    area_a_px = max(1, ax1 - ax0) * max(1, ay1 - ay0)
    area_b_px = max(1, bx1 - bx0) * max(1, by1 - by0)
    return float(inter) / float(max(1, min(area_a_px, area_b_px)))


def _capture_view3d_state(area):
    if area is None or area.type != "VIEW_3D":
        return None
    try:
        space = area.spaces.active
        region_3d = space.region_3d
        return {
            "view_rotation": region_3d.view_rotation.copy(),
            "view_location": region_3d.view_location.copy(),
            "view_distance": float(region_3d.view_distance),
            "view_perspective": str(region_3d.view_perspective),
            "view_camera_zoom": float(region_3d.view_camera_zoom),
            "shading_type": str(space.shading.type),
            "show_overlays": bool(space.overlay.show_overlays),
        }
    except Exception:
        return None


def _apply_view3d_state(area, state):
    if area is None or area.type != "VIEW_3D" or not state:
        return
    try:
        space = area.spaces.active
        region_3d = space.region_3d
        region_3d.view_rotation = state["view_rotation"].copy()
        region_3d.view_location = state["view_location"].copy()
        region_3d.view_distance = float(state["view_distance"])
        if state.get("view_perspective") in {"PERSP", "ORTHO", "CAMERA"}:
            region_3d.view_perspective = state["view_perspective"]
        region_3d.view_camera_zoom = float(state.get("view_camera_zoom", region_3d.view_camera_zoom))
        if state.get("shading_type"):
            space.shading.type = state["shading_type"]
        space.overlay.show_overlays = bool(state.get("show_overlays", True))
    except Exception:
        pass


def _split_screen_area(window, area, direction, factor):
    if window is None or area is None:
        return []
    screen = window.screen
    before = {a.as_pointer() for a in screen.areas}
    x0, y0, x1, y1 = _area_rect(area)
    try:
        with bpy.context.temp_override(window=window, screen=screen, area=area):
            bpy.ops.screen.area_split(direction=direction, factor=max(0.1, min(0.9, float(factor))))
    except Exception:
        return []
    children = []
    for candidate in screen.areas:
        cx0, cy0, cx1, cy1 = _area_rect(candidate)
        if cx0 >= x0 - 3 and cy0 >= y0 - 3 and cx1 <= x1 + 3 and cy1 <= y1 + 3:
            children.append(candidate)
    if len(children) < 2:
        children = [area] + [a for a in screen.areas if a.as_pointer() not in before]
    return children


def _configure_image_editor_area(area):
    if area is None:
        return
    try:
        area.type = "IMAGE_EDITOR"
        space = area.spaces.active
        try:
            space.mode = "VIEW"
        except Exception:
            pass
        try:
            space.show_region_toolbar = False
        except Exception:
            pass
        try:
            space.show_region_ui = False
        except Exception:
            pass
    except Exception:
        pass


def _find_window_for_area_ptr(area_ptr):
    if not area_ptr:
        return (None, None)
    try:
        for window in bpy.context.window_manager.windows:
            area = _area_from_pointer(window.screen, area_ptr)
            if area is not None:
                return (window, area)
    except Exception:
        pass
    return (None, None)


def _infer_dedicated_layout_areas(window, panel_area):
    """Bind roles to the existing editors in the supplied Blender baseline.

    The add-on no longer creates, converts, or splits areas.  The .blend file is
    the layout authority.  Of the three largest Image Editors, the upper editor
    is Selected Source, the lower-left editor is Interlaced, and the lower-right
    editor is Height/Depth Map.
    """
    if window is None:
        return {}
    screen = window.screen
    result = {"panel": panel_area} if panel_area is not None else {}

    image_areas = [a for a in screen.areas if a.type == "IMAGE_EDITOR"]
    if len(image_areas) >= 3:
        # Ignore tiny utility Image Editors if the user has added any.  The three
        # baseline viewers are the largest image-editor areas in this workspace.
        selected = sorted(
            image_areas,
            key=lambda a: max(1, int(a.width)) * max(1, int(a.height)),
            reverse=True,
        )[:3]
        top = max(selected, key=lambda a: (int(a.y) + int(a.height) * 0.5, int(a.height)))
        lower = [a for a in selected if a != top]
        lower.sort(key=lambda a: int(a.x) + int(a.width) * 0.5)
        result["source_image"] = top
        if len(lower) >= 1:
            result["interlaced_image"] = lower[0]
        if len(lower) >= 2:
            result["heightmap_image"] = lower[-1]

    # Preserve the supplied 3D layout.  These bindings are advisory only; no
    # screen areas are modified.  The largest VIEW_3D remains the primary view.
    view_areas = [a for a in screen.areas if a.type == "VIEW_3D"]
    if view_areas:
        primary = max(view_areas, key=lambda a: max(1, int(a.width)) * max(1, int(a.height)))
        result["primary"] = primary
        others = [a for a in view_areas if a != primary and a != panel_area]
        below = [a for a in others if int(a.y) < int(primary.y) and int(a.width) > int(a.height)]
        if below:
            result["horizontal"] = max(below, key=lambda a: int(a.width))
        left = [a for a in others if int(a.x) < int(primary.x) and int(a.height) >= int(a.width)]
        if left:
            result["vertical"] = max(left, key=lambda a: int(a.height))
    return result


def _bind_layout_area_roles(window, panel_area):
    roles = _infer_dedicated_layout_areas(window, panel_area)
    mapping = {
        "source_image": "source_image_area_ptr",
        "interlaced_image": "interlaced_image_area_ptr",
        "heightmap_image": "heightmap_image_area_ptr",
        "vertical": "vertical_inspection_area_ptr",
        "primary": "primary_view_area_ptr",
        "horizontal": "horizontal_inspection_area_ptr",
    }
    for key, state_key in mapping.items():
        area = roles.get(key)
        _state[state_key] = area.as_pointer() if area is not None else 0
    return roles


def _image_viewer_source_path(settings):
    try:
        index = int(settings.source_frame_index)
        if 0 <= index < len(settings.source_frames):
            return _resolve_preview_path(settings, settings.source_frames[index].path)
    except Exception:
        pass
    return None


def _set_dedicated_image_area(window, area, path, cache_key_name, reload_image=True, force_fit=False):
    if area is None or area.type != "IMAGE_EDITOR":
        return
    candidate = Path(path) if path else None
    key = ""
    if candidate is not None and candidate.is_file():
        try:
            key = str(candidate.resolve()) + "|" + str(candidate.stat().st_mtime_ns)
        except Exception:
            key = str(candidate)
    same_key = key == _state.get(cache_key_name, "")
    if same_key and not force_fit:
        return
    _state[cache_key_name] = key
    try:
        space = area.spaces.active
        if not key:
            space.image = None
            return
        image = bpy.data.images.load(str(candidate), check_existing=True)
        if reload_image and not same_key:
            try:
                image.reload()
            except Exception:
                pass
        space.image = image
        try:
            space.mode = "VIEW"
        except Exception:
            pass
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            try:
                with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region, space_data=space):
                    bpy.ops.image.view_all(fit_view=True)
            except Exception:
                pass
    except Exception:
        pass


def _sync_dedicated_image_editors(context=None, force=False):
    settings = getattr(getattr(bpy.context, "scene", None), "lenticular_sync", None)
    if settings is None:
        return

    window = getattr(context, "window", None) if context is not None else None
    panel_area = getattr(context, "area", None) if context is not None else None
    if window is None:
        panel_ptr = int(_state.get("panel_area_ptr", 0) or 0)
        window, panel_area = _find_window_for_area_ptr(panel_ptr)
    if window is None:
        try:
            window = bpy.context.window
        except Exception:
            window = None
    if window is None:
        return

    roles = _bind_layout_area_roles(window, panel_area)
    source_area = roles.get("source_image") or _area_from_pointer(window.screen, int(_state.get("source_image_area_ptr", 0) or 0))
    interlace_area = roles.get("interlaced_image") or _area_from_pointer(window.screen, int(_state.get("interlaced_image_area_ptr", 0) or 0))
    heightmap_area = roles.get("heightmap_image") or _area_from_pointer(window.screen, int(_state.get("heightmap_image_area_ptr", 0) or 0))

    source_path = _image_viewer_source_path(settings)
    interlaced_path = _resolve_preview_path(settings, settings.interlaced_image) if settings.interlaced_image else None
    heightmap_path = _resolve_preview_path(settings, settings.heightmap_image) if settings.heightmap_image else None

    if force:
        _state["source_viewer_key"] = ""
        _state["interlaced_viewer_key"] = ""
        _state["heightmap_viewer_key"] = ""

    _set_dedicated_image_area(window, source_area, source_path, "source_viewer_key", force_fit=force)
    _set_dedicated_image_area(window, interlace_area, interlaced_path, "interlaced_viewer_key", force_fit=force)
    _set_dedicated_image_area(window, heightmap_area, heightmap_path, "heightmap_viewer_key", force_fit=force)


def _apply_lenticulizer_workspace_layout(window, panel_area, force=False):
    """Bind the current supplied baseline layout without modifying any areas."""
    if window is None:
        return False
    roles = _bind_layout_area_roles(window, panel_area)
    ready = all(roles.get(key) is not None for key in ("source_image", "interlaced_image", "heightmap_image"))
    if ready:
        try:
            bpy.context.scene["lenticulizer_workspace_layout_version"] = 2
        except Exception:
            pass
        _sync_dedicated_image_editors(force=True)
        _schedule_inspection_viewer_fit()
    return ready


def _run_workspace_layout_once():
    _state["workspace_layout_timer_registered"] = False
    panel_ptr = int(_state.get("panel_area_ptr", 0) or 0)
    window, panel_area = _find_window_for_area_ptr(panel_ptr)
    if window is None or panel_area is None:
        return None
    try:
        _apply_lenticulizer_workspace_layout(window, panel_area, force=False)
    except Exception as exc:
        print("Lenticulizer workspace layout error:", exc)
    return None


def _schedule_workspace_layout():
    if _state.get("workspace_layout_timer_registered", False):
        return
    _state["workspace_layout_timer_registered"] = True
    try:
        bpy.app.timers.register(_run_workspace_layout_once, first_interval=0.35)
    except Exception:
        _state["workspace_layout_timer_registered"] = False


def _sync_selected_source_image_editor(context=None, force_fit=True):
    """Update only the selected-source viewer.

    Source selection should feel immediate. Older builds forced all three Image
    Editors to reload and refit on every click, including the large generated
    interlaced and 16-bit height/depth images. That unnecessary work caused the
    visible selection delay.
    """
    settings = getattr(getattr(bpy.context, "scene", None), "lenticular_sync", None)
    if settings is None:
        return
    window = getattr(context, "window", None) if context is not None else None
    panel_area = getattr(context, "area", None) if context is not None else None
    if window is None:
        panel_ptr = int(_state.get("panel_area_ptr", 0) or 0)
        window, panel_area = _find_window_for_area_ptr(panel_ptr)
    if window is None:
        try:
            window = bpy.context.window
        except Exception:
            window = None
    if window is None:
        return
    roles = _bind_layout_area_roles(window, panel_area)
    source_area = roles.get("source_image") or _area_from_pointer(window.screen, int(_state.get("source_image_area_ptr", 0) or 0))
    source_path = _image_viewer_source_path(settings)
    _set_dedicated_image_area(
        window,
        source_area,
        source_path,
        "source_viewer_key",
        reload_image=False,
        force_fit=force_fit,
    )


def _source_frame_selection_changed(self, context):
    if _state.get("applying", False):
        return
    try:
        _sync_selected_source_image_editor(context, force_fit=True)
    except Exception:
        pass


def _source_frame_selector_items(settings, context):
    """Dynamic thumbnail enum used by Blender's native icon-view selector."""
    items = []
    try:
        count = len(settings.source_frames)
        vertical = getattr(settings, "orientation", "VERTICAL") == "VERTICAL"
        for index, item in enumerate(settings.source_frames):
            identifier = f"FRAME_{index}"
            slot = _source_frame_position_label(index, count, vertical)
            filename = item.display_name or Path(item.path).name or f"Image {index + 1}"
            icon_id = _image_icon_id(settings, item.path)
            items.append((identifier, f"{slot}: {filename}", filename, int(icon_id or 0), index))
    except Exception:
        items = []
    if not items:
        items = [("NONE", "No source images", "Add source images to begin", 0, 0)]
    _state["source_selector_items"] = items
    return _state["source_selector_items"]


def _source_frame_selector_changed(self, context):
    if _state.get("applying", False):
        return
    value = str(getattr(self, "source_frame_selector", "") or "")
    if not value.startswith("FRAME_"):
        return
    try:
        index = int(value.split("_", 1)[1])
    except Exception:
        return
    if index < 0 or index >= len(self.source_frames):
        return
    previous = _state.get("applying", False)
    _state["applying"] = True
    try:
        self.source_frame_index = index
    finally:
        _state["applying"] = previous
    try:
        _sync_selected_source_image_editor(context, force_fit=True)
    except Exception:
        pass


def _sync_source_frame_selector(settings):
    if len(settings.source_frames) <= 0:
        return
    index = max(0, min(int(settings.source_frame_index), len(settings.source_frames) - 1))
    desired = f"FRAME_{index}"
    try:
        current = str(settings.source_frame_selector or "")
    except Exception:
        current = ""
    if current == desired:
        return
    previous = _state.get("applying", False)
    _state["applying"] = True
    try:
        settings.source_frame_selector = desired
    except Exception:
        pass
    finally:
        _state["applying"] = previous


class LENTICULAR_OT_apply_workspace_layout(Operator):
    bl_idname = "lenticular.apply_workspace_layout"
    bl_label = "Bind Lenticulizer Image Viewers"
    bl_description = "Bind the three Image Editors in the supplied Lenticulizer workspace without changing the layout"

    def execute(self, context):
        if context.window is None or context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "Run this from the Lenticulizer sidebar viewport")
            return {"CANCELLED"}
        _state["panel_area_ptr"] = context.area.as_pointer()
        try:
            ok = _apply_lenticulizer_workspace_layout(context.window, context.area, force=False)
            if not ok:
                raise RuntimeError("The current workspace does not match the expected Lenticulizer baseline layout")
            _set_status(context.scene.lenticular_sync, "Lenticulizer viewer layout ready")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


def _fit_inspection_area_to_lens_profile(window, area, settings, target_cells=5.0, safety_margin=1.08):
    """Center and scale one inspection viewport by the *visible pitch*.

    Earlier builds tried to infer a useful zoom from object bounds and
    ``view_selected``.  In the authored Lenticulizer workspace the inspection
    view rotations do not necessarily line up with the lens object's local
    axes, so a physically small temporary box could project as mostly depth.
    Blender would then choose a much wider view than intended.  This is also
    why the baseline appeared correctly zoomed for a moment and then jumped
    outward when the delayed auto-fit timer ran.

    This version leaves the authored inspection orientation untouched.  It
    projects one real lenticule/prism pitch into the actual viewport, measures
    that pitch in screen pixels, and adjusts only view_location/view_distance
    until the requested number of repeated cells fills the useful viewport
    dimension.  A final projected-bounds check adds only enough margin to keep
    the lens/prism profile itself from clipping.
    """
    if window is None or area is None or area.type != "VIEW_3D":
        return False
    region = _view3d_window_region(area)
    if region is None or int(region.width) < 8 or int(region.height) < 8:
        return False
    surface_name = "DirectionalRelief" if _lens_free_mode(settings) else "LenticularLens"
    surface = bpy.data.objects.get(OBJECT_PREFIX + surface_name)
    if surface is None:
        return False

    try:
        space = area.spaces.active
        region_3d = getattr(space, "region_3d", None)
        if region_3d is None:
            return False

        lpi = max(0.001, float(getattr(settings, "lpi", 24.0)))
        pitch_m = (25.4 / lpi) / 1000.0
        orientation = getattr(settings, "orientation", "VERTICAL")

        # Use the generated optical surface's real local center and transform
        # both the center and pitch direction into world space.  matrix_world
        # already includes the upright print-root rotation used by Lenticulizer.
        bbox = [Vector(corner) for corner in surface.bound_box]
        local_min = Vector((min(v.x for v in bbox), min(v.y for v in bbox), min(v.z for v in bbox)))
        local_max = Vector((max(v.x for v in bbox), max(v.y for v in bbox), max(v.z for v in bbox)))
        local_center = (local_min + local_max) * 0.5
        world_center = surface.matrix_world @ local_center

        local_axis = Vector((1.0, 0.0, 0.0)) if orientation == "VERTICAL" else Vector((0.0, 1.0, 0.0))
        world_axis = surface.matrix_world.to_3x3() @ local_axis
        if world_axis.length <= 1.0e-12:
            return False
        world_axis.normalize()

        # Keep the inspection viewer centered on the optical surface, without
        # changing its authored rotation/perspective mode.
        region_3d.view_location = world_center
        try:
            region_3d.update()
        except Exception:
            pass

        def project(point):
            try:
                return location_3d_to_region_2d(region, region_3d, point)
            except Exception:
                return None

        def pitch_pixels():
            half = world_axis * (pitch_m * 0.5)
            a = project(world_center - half)
            b = project(world_center + half)
            if a is None or b is None:
                return (0.0, None)
            delta = b - a
            px = float(delta.length)
            if px <= 1.0e-6:
                return (0.0, None)
            return (px, delta.normalized())

        # Two short correction passes are stable for both ORTHO and the authored
        # perspective inspection views.  For orthographic views the first pass
        # is effectively exact.
        desired_cells = max(1.0, float(target_cells)) * max(1.0, float(safety_margin))
        for _ in range(2):
            px, screen_axis = pitch_pixels()
            if px <= 1.0e-6 or screen_axis is None:
                return False
            # Project the rectangular region onto the visible pitch direction.
            # This works whether the profile appears horizontal, vertical, or
            # slightly diagonal in the authored viewport.
            available = abs(float(screen_axis.x)) * float(region.width) + abs(float(screen_axis.y)) * float(region.height)
            available = max(8.0, available)
            desired_pitch_px = available / desired_cells
            if desired_pitch_px <= 1.0e-6:
                return False
            scale = max(0.03, min(30.0, px / desired_pitch_px))
            region_3d.view_distance = max(1.0e-7, float(region_3d.view_distance) * scale)
            try:
                region_3d.update()
            except Exception:
                pass

        # Anti-clipping check: project a compact box containing exactly the
        # desired central profile span and the full peak/valley height.  If it
        # reaches an edge, zoom out only enough to restore a small margin.
        local_perp = Vector((0.0, 1.0, 0.0)) if orientation == "VERTICAL" else Vector((1.0, 0.0, 0.0))
        half_profile = pitch_m * max(1.0, float(target_cells)) * 0.5
        thin_span = max(pitch_m * 0.10, 1.0e-6)
        half_thin = thin_span * 0.5
        z_pad = max((local_max.z - local_min.z) * 0.03, pitch_m * 0.01)
        z0 = local_min.z - z_pad
        z1 = local_max.z + z_pad
        projected = []
        for ap in (-half_profile, half_profile):
            for pp in (-half_thin, half_thin):
                for zz in (z0, z1):
                    local = local_center + local_axis * ap + local_perp * pp
                    local.z = zz
                    screen = project(surface.matrix_world @ local)
                    if screen is not None:
                        projected.append(screen)
        if projected:
            min_x = min(float(v.x) for v in projected)
            max_x = max(float(v.x) for v in projected)
            min_y = min(float(v.y) for v in projected)
            max_y = max(float(v.y) for v in projected)
            width_px = max(1.0, max_x - min_x)
            height_px = max(1.0, max_y - min_y)
            allowed_w = max(8.0, float(region.width) * 0.94)
            allowed_h = max(8.0, float(region.height) * 0.94)
            overflow = max(width_px / allowed_w, height_px / allowed_h, 1.0)
            if overflow > 1.0:
                region_3d.view_distance = max(1.0e-7, float(region_3d.view_distance) * overflow)
                try:
                    region_3d.update()
                except Exception:
                    pass

        try:
            area.tag_redraw()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _run_inspection_viewer_fit_once():
    _state["inspection_fit_timer_registered"] = False
    settings = getattr(getattr(bpy.context, "scene", None), "lenticular_sync", None)
    if settings is None:
        return None
    panel_ptr = int(_state.get("panel_area_ptr", 0) or 0)
    window, panel_area = _find_window_for_area_ptr(panel_ptr)
    if window is None:
        try:
            window = bpy.context.window
        except Exception:
            window = None
    if window is None:
        return None
    roles = _bind_layout_area_roles(window, panel_area)
    vertical_area = roles.get("vertical") or _area_from_pointer(window.screen, int(_state.get("vertical_inspection_area_ptr", 0) or 0))
    horizontal_area = roles.get("horizontal") or _area_from_pointer(window.screen, int(_state.get("horizontal_inspection_area_ptr", 0) or 0))

    # Show a useful number of repeated profiles rather than the entire print.
    # The tall viewer needs fewer cells; the wide viewer can show more while
    # retaining enough profile detail for inspection.
    _fit_inspection_area_to_lens_profile(window, vertical_area, settings, target_cells=5.0, safety_margin=1.08)
    _fit_inspection_area_to_lens_profile(window, horizontal_area, settings, target_cells=6.0, safety_margin=1.08)
    return None


def _schedule_inspection_viewer_fit():
    if _state.get("inspection_fit_timer_registered", False):
        return
    _state["inspection_fit_timer_registered"] = True
    try:
        bpy.app.timers.register(_run_inspection_viewer_fit_once, first_interval=0.12)
    except Exception:
        _state["inspection_fit_timer_registered"] = False


def _region_screen_bounds(area, region):
    """Return region bounds in window coordinates for Blender split-view layouts."""
    if area is None or region is None:
        return (0, 0, 0, 0)
    # In Blender 5 Region.x/y are normally area-local. Keep a defensive fallback
    # for contexts/builds that expose window-relative values.
    try:
        local_x = 0 <= int(region.x) <= int(area.width) and int(region.x) + int(region.width) <= int(area.width) + 4
        local_y = 0 <= int(region.y) <= int(area.height) and int(region.y) + int(region.height) <= int(area.height) + 4
        x0 = int(area.x) + int(region.x) if local_x else int(region.x)
        y0 = int(area.y) + int(region.y) if local_y else int(region.y)
        return (x0, y0, x0 + int(region.width), y0 + int(region.height))
    except Exception:
        return (0, 0, 0, 0)


def _area_at_window_xy(screen, mouse_x, mouse_y):
    if not screen:
        return (None, None)
    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = _view3d_window_region(area)
        if region is None:
            continue
        x0, y0, x1, y1 = _region_screen_bounds(area, region)
        if x0 <= mouse_x < x1 and y0 <= mouse_y < y1:
            return area, region
    return (None, None)


def _remember_viewport_target(window, area, region):
    if window is None or area is None or region is None:
        return False
    try:
        _state["last_view3d_area_ptr"] = area.as_pointer()
        _state["last_view3d_region_ptr"] = region.as_pointer()
        _state["last_view3d_window_ptr"] = window.as_pointer()
        return True
    except Exception:
        return False


def _view3d_areas_sorted(context):
    screen = context.window.screen if context and context.window else (context.screen if context else None)
    if not screen:
        return []
    areas = [a for a in screen.areas if a.type == "VIEW_3D" and _view3d_window_region(a) is not None]
    # Stable visual order: top-to-bottom, then left-to-right.
    areas.sort(key=lambda a: (-int(a.y), int(a.x)))
    return areas


def _selected_view3d_area(context):
    settings = context.scene.lenticular_sync
    areas = _view3d_areas_sorted(context)
    if not areas:
        return None

    # Preserve the exact explicitly selected viewport even if the user later
    # splits/joins other viewports and the visual numbering changes.
    target_ptr = int(_state.get("explicit_target_view3d_area_ptr", 0) or 0)
    if target_ptr:
        for index, area in enumerate(areas, 1):
            try:
                if area.as_pointer() == target_ptr:
                    if int(getattr(settings, "target_viewport_index", 1)) != index:
                        previous = _state.get("applying", False)
                        _state["applying"] = True
                        try:
                            settings.target_viewport_index = index
                        finally:
                            _state["applying"] = previous
                    return area
            except Exception:
                pass

    index = max(1, int(getattr(settings, "target_viewport_index", 1)))
    if index > len(areas):
        index = len(areas)
    area = areas[index - 1]
    try:
        _state["explicit_target_view3d_area_ptr"] = area.as_pointer()
    except Exception:
        pass
    return area


def _target_viewport_label(context):
    areas = _view3d_areas_sorted(context)
    if not areas:
        return "No viewport selected"
    area = _selected_view3d_area(context)
    if area is None:
        return "No viewport selected"
    index = 1
    for i, candidate in enumerate(areas, 1):
        try:
            if candidate.as_pointer() == area.as_pointer():
                index = i
                break
        except Exception:
            pass
    try:
        panel_marker = " (This Panel)" if context.area and context.area.type == "VIEW_3D" and context.area.as_pointer() == area.as_pointer() else ""
    except Exception:
        panel_marker = ""
    return f"Viewport {index}{panel_marker}"


def _active_view3d_area(context):
    """Return only the explicitly selected target viewport."""
    return _selected_view3d_area(context)


def _camera_zoom_to_factor(camzoom):
    """Python equivalent of Blender's camera-view zoom-factor conversion."""
    return ((math.sqrt(2.0) + float(camzoom) / 50.0) ** 2) / 4.0


def _camera_zoom_from_factor(factor):
    factor = max(0.1657359312880715, min(44.98528137423857, float(factor)))
    return max(-30.0, min(600.0, 50.0 * (2.0 * math.sqrt(factor) - math.sqrt(2.0))))


def _fill_camera_view_top_to_bottom(context, area, region, region_3d):
    """Scale camera view until the camera frame fills the viewport vertically."""
    if area is None or region is None or region_3d is None:
        return False
    scene = context.scene
    render = scene.render

    render_w = max(1.0, float(render.resolution_x) * float(render.pixel_aspect_x))
    render_h = max(1.0, float(render.resolution_y) * float(render.pixel_aspect_y))
    camera_aspect = render_w / render_h
    viewport_aspect = max(1.0, float(region.width)) / max(1.0, float(region.height))

    # view_center_camera fits the WHOLE camera frame, which means a wide camera
    # gets width-limited and remains short vertically. Scale only the extra amount
    # required to make its height equal the viewport height.
    height_scale = max(1.0, camera_aspect / viewport_aspect)

    current_factor = _camera_zoom_to_factor(region_3d.view_camera_zoom)
    region_3d.view_camera_zoom = _camera_zoom_from_factor(current_factor * height_scale * 1.005)
    region_3d.view_camera_offset = (0.0, 0.0)
    return True


def _match_viewport_to_camera(context, camera):
    """Match only the explicitly selected normal 3D viewport to a generated view camera.

    This deliberately does not set scene.camera and does not enter CAMERA view. Camera
    view is scene/global state in Blender unless local-camera mode is used, so using it
    here causes split viewports to follow the same camera. Viewport Match instead copies
    the generated camera orientation into one RegionView3D and frames the generated
    surface in that area only.
    """
    if not camera or camera.type != "CAMERA":
        return False

    area = _active_view3d_area(context)
    if area is None:
        return False
    region = _view3d_window_region(area)
    if region is None:
        return False
    space = area.spaces.active
    region_3d = getattr(space, "region_3d", None)
    if region_3d is None:
        return False

    try:
        evaluated = camera.evaluated_get(context.evaluated_depsgraph_get())
        matrix_world = evaluated.matrix_world.copy()
    except Exception:
        matrix_world = camera.matrix_world.copy()

    settings = context.scene.lenticular_sync
    scene_camera_before = context.scene.camera

    try:
        # A normal viewport must be used here. Staying in CAMERA mode would make
        # the viewport follow scene.camera and therefore appear to change together
        # with every other camera-view viewport.
        region_3d.view_perspective = "PERSP"

        # Match the camera's evaluated world-space orientation. The generated
        # cameras may use tracking constraints, so evaluated matrix_world is
        # required rather than the object's raw rotation channels.
        region_3d.view_rotation = matrix_world.to_quaternion().normalized()

        # Match the camera focal length in this viewport without touching other
        # VIEW_3D areas. This keeps the perspective character close to the chosen
        # generated camera while the object framing is handled below.
        try:
            if getattr(camera, "data", None) is not None and hasattr(camera.data, "lens"):
                space.lens = float(camera.data.lens)
        except Exception:
            pass

        try:
            region_3d.update()
        except Exception:
            pass

        fitted = _fit_selected_viewport_to_lens(context)
        settings.active_viewport_camera_name = camera.name
        _set_status(
            settings,
            "Viewport match: " + _target_viewport_label(context) + " - " + _camera_label(camera)
            + (" - fit to output" if fitted else ""),
        )

        # Viewport Match must never alter the scene/render camera.
        if context.scene.camera is not scene_camera_before:
            context.scene.camera = scene_camera_before

        try:
            area.tag_redraw()
        except Exception:
            pass
        return True
    except Exception as exc:
        if context.scene.camera is not scene_camera_before:
            try:
                context.scene.camera = scene_camera_before
            except Exception:
                pass
        _set_status(settings, "Could not match viewport: " + str(exc))
        return False

def _fit_selected_viewport_to_lens(context):
    """Frame the generated lenticular lens in the explicitly selected target viewport."""
    area = _active_view3d_area(context)
    if area is None:
        return False
    region = _view3d_window_region(area)
    if region is None:
        return False
    surface_name = "DirectionalRelief" if _lens_free_mode(context.scene.lenticular_sync) else "LenticularLens"
    lens = bpy.data.objects.get(OBJECT_PREFIX + surface_name)
    if lens is None:
        return False

    # view_selected preserves the viewport's current viewing orientation while
    # updating its center/distance to frame the lens. Temporarily select only
    # the lens, then restore the user's selection and active object.
    view_layer = context.view_layer
    previous_selected = list(context.selected_objects)
    previous_active = view_layer.objects.active
    try:
        for obj in previous_selected:
            try:
                obj.select_set(False)
            except Exception:
                pass
        lens.hide_set(False)
        lens.select_set(True)
        view_layer.objects.active = lens
        with context.temp_override(
            window=context.window,
            screen=context.window.screen,
            area=area,
            region=region,
            space_data=area.spaces.active,
        ):
            bpy.ops.view3d.view_selected(use_all_regions=False)
        try:
            area.tag_redraw()
        except Exception:
            pass
        return True
    except Exception:
        return False
    finally:
        try:
            lens.select_set(False)
        except Exception:
            pass
        for obj in previous_selected:
            try:
                if obj.name in bpy.data.objects:
                    obj.select_set(True)
            except Exception:
                pass
        try:
            if previous_active is not None and previous_active.name in bpy.data.objects:
                view_layer.objects.active = previous_active
        except Exception:
            pass


REFERENCE_LPI = 15.0
REFERENCE_PEAK_MM = 1.86
REFERENCE_VALLEY_MM = 1.18
REFERENCE_RISE_MM = REFERENCE_PEAK_MM - REFERENCE_VALLEY_MM
REFERENCE_BASE_FRACTION = REFERENCE_VALLEY_MM / REFERENCE_PEAK_MM
REFERENCE_RISE_FRACTION = REFERENCE_RISE_MM / REFERENCE_PEAK_MM
MAX_PEAK_MM = 5.0
MIN_NONZERO_BASE_MM = 0.30
MIN_NONZERO_PEAK_MM = 0.30


def _workspace_dir(settings):
    project_dir = _project_dir(settings)
    if project_dir:
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    try:
        if bpy.data.filepath:
            folder = Path(bpy.data.filepath).parent / (Path(bpy.data.filepath).stem + "_lenticular")
        else:
            folder = Path(tempfile.gettempdir()) / "LenticularLensToolkit"
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except Exception:
        return None


def _set_priority_silent(settings, priority):
    if not priority:
        return
    previous = _state["applying"]
    _state["applying"] = True
    try:
        settings.priority = priority
    finally:
        _state["applying"] = previous


def _reference_scale(lpi):
    lpi = max(0.001, float(lpi))
    return REFERENCE_LPI / lpi


def _reference_scaled_peak(lpi):
    return REFERENCE_PEAK_MM * _reference_scale(lpi)


def _reference_scaled_valley(lpi):
    return REFERENCE_VALLEY_MM * _reference_scale(lpi)


def _reference_scaled_rise(lpi):
    return REFERENCE_RISE_MM * _reference_scale(lpi)


def _recommended_peak(lpi):
    # Legacy/reference recommendation retained for compatibility.
    peak = _reference_scaled_peak(lpi)
    peak = min(MAX_PEAK_MM, peak)
    if 0.0 < peak < MIN_NONZERO_PEAK_MM:
        peak = MIN_NONZERO_PEAK_MM
    return peak


def _recommended_base_for_peak(lpi, peak_mm):
    peak_mm = max(0.0, min(MAX_PEAK_MM, float(peak_mm)))
    valley = peak_mm * REFERENCE_BASE_FRACTION
    if 0.0 < valley < MIN_NONZERO_BASE_MM:
        valley = MIN_NONZERO_BASE_MM if peak_mm >= MIN_NONZERO_BASE_MM else 0.0
    return max(0.0, min(peak_mm, valley))


def _recommended_geometry(lpi):
    peak = _recommended_peak(lpi)
    base = _recommended_base_for_peak(lpi, peak)
    rise = max(0.0, peak - base)
    return peak, base, rise


def _lens_free_mode(settings):
    return str(getattr(settings, "output_mode", "LENTICULAR")).upper().strip() == "RELIEF"


def _relief_prism_height_mm(settings):
    value = float(getattr(settings, "relief_prism_height_mm", 0.8))
    return max(MIN_NONZERO_PEAK_MM, min(MAX_PEAK_MM, value))


def _relief_normalized_boundaries(settings):
    # One equal-width planar facet per source view. Odd view counts include a
    # true flat center facet. The shape is normalized, then scaled by Prism Height.
    views = max(2, int(settings.views))
    center = (views - 1) * 0.5
    slopes = [center - i for i in range(views)]
    heights = [0.0]
    for slope in slopes:
        heights.append(heights[-1] + slope)
    drift = heights[-1] - heights[0]
    if abs(drift) > 1e-12:
        for i in range(len(heights)):
            heights[i] -= drift * (i / float(max(1, len(heights) - 1)))
    lo = min(heights)
    hi = max(heights)
    span = hi - lo
    if span <= 1e-12:
        return [0.0 for _ in heights]
    return [(h - lo) / span for h in heights]


def _relief_boundary_heights_mm(settings, prism_height_mm=None):
    height = _relief_prism_height_mm(settings) if prism_height_mm is None else max(0.0, float(prism_height_mm))
    return [v * height for v in _relief_normalized_boundaries(settings)]


def _relief_facet_angles(settings, prism_height_mm=None):
    lpi = max(0.001, float(settings.lpi))
    pitch_mm = 25.4 / lpi
    views = max(2, int(settings.views))
    facet_width_mm = pitch_mm / float(views)
    heights = _relief_boundary_heights_mm(settings, prism_height_mm)
    angles = []
    for i in range(views):
        dz = heights[i + 1] - heights[i]
        slope = dz / max(1e-12, facet_width_mm)
        # Surface normal points opposite the signed z(x) slope.
        angles.append(-math.degrees(math.atan(slope)))
    return angles


def _relief_view_spread_deg(settings, prism_height_mm=None):
    angles = _relief_facet_angles(settings, prism_height_mm)
    return max(angles) - min(angles) if angles else 0.0


def _relief_adjacent_view_deg(settings, prism_height_mm=None):
    angles = sorted(_relief_facet_angles(settings, prism_height_mm))
    if len(angles) < 2:
        return 0.0
    gaps = [angles[i + 1] - angles[i] for i in range(len(angles) - 1)]
    return sum(gaps) / len(gaps)


def _relief_required_rise_mm(settings, prism_height_mm=None):
    return _relief_prism_height_mm(settings) if prism_height_mm is None else max(0.0, float(prism_height_mm))


def _relief_base_mm(settings):
    # Color Raised / naked-eye relief begins at the substrate. There is no clear
    # optical base layer in this mode.
    return 0.0


def _relief_required_geometry(settings, prism_height_mm=None):
    rise = _relief_required_rise_mm(settings, prism_height_mm)
    base = 0.0
    spread = _relief_view_spread_deg(settings, rise)
    return spread, base, rise, rise


def _relief_profile_value(settings, phase, prism_height_mm=None):
    phase = float(phase) % 1.0
    views = max(2, int(settings.views))
    heights = _relief_normalized_boundaries(settings)
    fp = phase * views
    facet = min(views - 1, int(math.floor(fp)))
    local = fp - facet
    z = heights[facet] + (heights[facet + 1] - heights[facet]) * local
    return max(0.0, min(1.0, z))


def _relief_viewing_angle_for_peak(settings, peak_mm):
    return _relief_view_spread_deg(settings, peak_mm)


def _relief_peak_for_viewing_angle(settings, angle_deg):
    target = max(0.0, min(179.0, float(angle_deg)))
    low = MIN_NONZERO_PEAK_MM
    high = MAX_PEAK_MM
    if _relief_view_spread_deg(settings, low) >= target:
        return low
    if _relief_view_spread_deg(settings, high) < target:
        return MAX_PEAK_MM + 1.0
    for _ in range(60):
        mid = (low + high) * 0.5
        if _relief_view_spread_deg(settings, mid) >= target:
            high = mid
        else:
            low = mid
    return high


def _uses_theoretical_optics(settings):
    # Lens Type is the authoritative optical basis. Print/Base can be independently
    # overridden in Semi-Automatic or Manual mode without silently changing the
    # actual lens surface family. Lens-free relief mode uses geometric faceting, not refractive optics.
    if _lens_free_mode(settings):
        return False
    return getattr(settings, "lens_profile", "AUTO") in {"AUTO_THEORETICAL", "THEORETICAL"}


def _theoretical_minimum_peak_mm(settings, lpi=None):
    lpi = max(0.001, float(settings.lpi if lpi is None else lpi))
    n = max(1.0001, float(settings.ior))
    a = (25.4 / lpi) * 0.5
    return a * math.sqrt((n + 1.0) / (n - 1.0))


def _theoretical_surface_height_mm(settings, lpi, peak_mm, x_mm):
    n = max(1.0001, float(settings.ior))
    c = (n - 1.0) * float(peak_mm)
    n2m1 = n * n - 1.0
    disc = c * c - n2m1 * float(x_mm) * float(x_mm)
    if disc < -1e-9:
        return -1.0
    disc = max(0.0, disc)
    return (c + n * math.sqrt(disc)) / n2m1


def _theoretical_base_for_peak_mm(settings, lpi, peak_mm):
    a = (25.4 / max(0.001, float(lpi))) * 0.5
    return _theoretical_surface_height_mm(settings, lpi, peak_mm, a)


def _theoretical_optimal_peak_mm(settings, lpi=None):
    lpi = max(0.001, float(settings.lpi if lpi is None else lpi))
    minimum = _theoretical_minimum_peak_mm(settings, lpi)
    if minimum > MAX_PEAK_MM:
        return minimum
    valley = _theoretical_base_for_peak_mm(settings, lpi, minimum)
    if valley < 0.0 or valley >= MIN_NONZERO_BASE_MM:
        return minimum
    high = MAX_PEAK_MM
    if _theoretical_base_for_peak_mm(settings, lpi, high) < MIN_NONZERO_BASE_MM:
        return high + 1.0
    low = minimum
    for _ in range(60):
        mid = (low + high) * 0.5
        if _theoretical_base_for_peak_mm(settings, lpi, mid) >= MIN_NONZERO_BASE_MM:
            high = mid
        else:
            low = mid
    return high


def _theoretical_base_for_selected_peak(settings, lpi, peak_mm):
    valley = _theoretical_base_for_peak_mm(settings, lpi, peak_mm)
    if valley < 0.0:
        return -1.0
    if 0.0 < valley < MIN_NONZERO_BASE_MM:
        valley = MIN_NONZERO_BASE_MM
    return max(0.0, min(float(peak_mm), valley))


def _reference_viewing_angle_for_peak(settings, peak_mm):
    peak = max(1e-9, float(peak_mm))
    lpi = max(0.001, float(settings.lpi))
    n = max(1.0001, float(settings.ior))
    a = (25.4 / lpi) * 0.5
    return 2.0 * math.atan((n * a) / peak) * 180.0 / math.pi


def _theoretical_viewing_angle_for_peak(settings, peak_mm):
    peak = max(1e-9, float(peak_mm))
    lpi = max(0.001, float(settings.lpi))
    n = max(1.0001, float(settings.ior))
    a = (25.4 / lpi) * 0.5
    sin_inside = a / math.sqrt(a * a + peak * peak)
    sin_outside = max(-0.999999999, min(0.999999999, n * sin_inside))
    return 2.0 * math.asin(sin_outside) * 180.0 / math.pi


def _profile_rms_surface_slope(settings, profile, peak_mm, base_mm):
    lpi = max(0.001, float(settings.lpi))
    pitch_mm = 25.4 / lpi
    rise_mm = max(1e-9, float(peak_mm) - float(base_mm))
    samples = 64
    last_phase = 0.02
    last_z = _profile_value_for_phase_overrides(settings, last_phase, profile_override=profile, peak_override=peak_mm, base_override=base_mm)
    sum_sq = 0.0
    count = 0
    for i in range(1, samples + 1):
        phase = 0.02 + 0.96 * i / float(samples)
        z = _profile_value_for_phase_overrides(settings, phase, profile_override=profile, peak_override=peak_mm, base_override=base_mm)
        dphase = max(1e-9, phase - last_phase)
        slope = ((z - last_z) * rise_mm) / (dphase * pitch_mm)
        sum_sq += slope * slope
        count += 1
        last_phase = phase
        last_z = z
    return math.sqrt(sum_sq / max(1, count))


def _profile_geometry_factor(settings):
    profile = _resolved_local_profile(settings)
    if profile in {"REFERENCE", "THEORETICAL"}:
        return 1.0
    lpi = max(0.001, float(settings.lpi))
    reference_peak = min(MAX_PEAK_MM, max(MIN_NONZERO_PEAK_MM, _reference_scaled_peak(lpi)))
    reference_base = _recommended_base_for_peak(lpi, reference_peak)
    reference_slope = _profile_rms_surface_slope(settings, "REFERENCE", reference_peak, reference_base)
    profile_slope = _profile_rms_surface_slope(settings, profile, reference_peak, reference_base)
    if reference_slope <= 1e-9 or profile_slope <= 1e-9:
        return 1.0
    # Match the profile's RMS optical surface slope to the calibrated reference.
    # A flatter profile needs more lens height; a steeper profile needs less.
    return max(0.65, min(1.60, reference_slope / profile_slope))

def _viewing_angle_for_peak(settings, peak_mm=None):
    peak = max(1e-9, float(settings.thickness_mm if peak_mm is None else peak_mm))
    if _lens_free_mode(settings):
        return _relief_viewing_angle_for_peak(settings, peak)
    if _uses_theoretical_optics(settings):
        return _theoretical_viewing_angle_for_peak(settings, peak)
    factor = _profile_geometry_factor(settings)
    effective_reference_peak = peak / max(1e-9, factor)
    return _reference_viewing_angle_for_peak(settings, effective_reference_peak)


def _viewing_angle_mode_key(settings):
    mode = str(getattr(settings, "viewing_angle_mode", "STANDARD")).upper().strip()
    if mode == "RECOMMENDED":
        mode = "STANDARD"
    return mode if mode in {"NARROW", "STANDARD", "WIDE", "EXTRA_WIDE", "CUSTOM"} else "STANDARD"


def _viewing_angle_mode_label(settings):
    mode = _viewing_angle_mode_key(settings)
    labels = {"NARROW": "Narrow", "STANDARD": "Standard", "WIDE": "Wide", "EXTRA_WIDE": "Extra Wide", "CUSTOM": "Custom"}
    return labels.get(mode, "Standard")


def _custom_viewing_angle_active(settings):
    return _viewing_angle_mode_key(settings) == "CUSTOM"


def _viewing_angle_factor(settings):
    mode = _viewing_angle_mode_key(settings)
    if _uses_theoretical_optics(settings):
        return {"NARROW": 0.70, "STANDARD": 0.82, "WIDE": 0.92, "EXTRA_WIDE": 0.98, "CUSTOM": 1.0}.get(mode, 0.82)
    return {"NARROW": 0.85, "STANDARD": 1.0, "WIDE": 1.10, "EXTRA_WIDE": 1.18, "CUSTOM": 1.0}.get(mode, 1.0)


def _peak_for_viewing_angle(settings, angle_deg):
    angle = max(0.001, min(178.999, float(angle_deg)))
    lpi = max(0.001, float(settings.lpi))
    n = max(1.0001, float(settings.ior))
    a = (25.4 / lpi) * 0.5
    half = math.radians(angle * 0.5)
    if _lens_free_mode(settings):
        return _relief_peak_for_viewing_angle(settings, angle_deg)
    if _uses_theoretical_optics(settings):
        s = math.sin(half) / n
        if s <= 1e-12:
            return MAX_PEAK_MM + 1.0
        s = min(0.999999999, s)
        return a * math.sqrt(max(0.0, 1.0 - s * s)) / s
    tangent = math.tan(half)
    if abs(tangent) <= 1e-12:
        return MAX_PEAK_MM + 1.0
    reference_peak = n * a / tangent
    return reference_peak * _profile_geometry_factor(settings)


def _mathematical_maximum_feasible_viewing_angle(settings):
    peak = _theoretical_optimal_peak_mm(settings)
    if peak > MAX_PEAK_MM:
        peak = MAX_PEAK_MM
    if peak <= 0.0:
        peak = MAX_PEAK_MM
    return max(1.0, min(178.9, _theoretical_viewing_angle_for_peak(settings, peak)))


def _mathematical_minimum_feasible_viewing_angle(settings):
    return max(1.0, min(178.9, _theoretical_viewing_angle_for_peak(settings, MAX_PEAK_MM)))


def _reference_standard_viewing_angle(settings):
    peak = _selected_peak_from_print_profile(settings, max(0.001, float(settings.lpi)))
    peak = max(MIN_NONZERO_PEAK_MM, min(MAX_PEAK_MM, peak))
    return max(1.0, min(178.9, _reference_viewing_angle_for_peak(settings, peak)))


def _reference_maximum_recommended_viewing_angle(settings):
    peak = _selected_peak_from_print_profile(settings, max(0.001, float(settings.lpi)))
    peak = max(MIN_NONZERO_PEAK_MM, peak * 0.75)
    return max(1.0, min(178.9, _reference_viewing_angle_for_peak(settings, peak)))


def _standard_recommended_viewing_angle(settings):
    if _uses_theoretical_optics(settings):
        return max(1.0, min(178.9, _mathematical_maximum_feasible_viewing_angle(settings) * 0.82))
    return _reference_standard_viewing_angle(settings)


def _recommended_viewing_angle(settings):
    if _lens_free_mode(settings):
        return _relief_view_spread_deg(settings)
    if _custom_viewing_angle_active(settings):
        return max(1.0, min(178.9, float(settings.custom_viewing_angle_deg)))
    if _uses_theoretical_optics(settings):
        maximum = _mathematical_maximum_feasible_viewing_angle(settings)
        minimum = _mathematical_minimum_feasible_viewing_angle(settings)
        angle = maximum * _viewing_angle_factor(settings)
        return max(minimum, min(maximum, angle))
    standard = _reference_standard_viewing_angle(settings)
    maximum = _reference_maximum_recommended_viewing_angle(settings)
    minimum = _reference_viewing_angle_for_peak(settings, MAX_PEAK_MM)
    angle = standard * _viewing_angle_factor(settings)
    return max(minimum, min(maximum, angle))


def _recommended_lens_profile(settings):
    if _uses_theoretical_optics(settings):
        return "THEORETICAL"
    views = max(1, int(settings.views))
    lpi = max(0.001, float(settings.lpi))
    ppl = max(1.0, float(_recommended_pixels_per_lenticule(settings)))
    if views == 3 and 12.0 <= lpi <= 40.0:
        return "REFERENCE"
    vertical = settings.orientation == "VERTICAL"
    axis_mm = float(settings.width_mm) if vertical else float(settings.height_mm)
    lens_count = max(0.0, (axis_mm / 25.4) * lpi)
    if views <= 2:
        result = "PRISMATIC" if ppl >= 40.0 and lpi <= 75.0 else "CIRCULAR"
    elif views <= 5:
        result = "ASPHERIC" if ppl >= 22.0 else "CIRCULAR"
    else:
        result = "ASPHERIC" if ppl >= max(32.0, views * 5.0) else "CIRCULAR"
    if lpi >= 100.0 and ppl < 20.0:
        result = "CIRCULAR"
    if 0.0 < lens_count < 12.0 and views <= 2 and ppl >= 40.0:
        result = "PRISMATIC"
    return result


def _resolved_profile_label(settings):
    if _lens_free_mode(settings):
        return "Faceted Directional Relief"
    value = settings.lens_profile
    if value == "AUTO":
        value = _recommended_lens_profile(settings)
    elif value == "AUTO_THEORETICAL":
        value = "THEORETICAL"
    return _enum_to_profile(value)


def _clamp_manual_base(value, peak_limit=MAX_PEAK_MM):
    base = max(0.0, min(float(peak_limit), float(value)))
    if 0.0 < base < MIN_NONZERO_BASE_MM:
        base = MIN_NONZERO_BASE_MM
    return min(base, float(peak_limit))


def _manual_thickness_mm(settings):
    value = max(0.0, float(getattr(settings, "manual_thickness_value", 0.0)))
    if getattr(settings, "manual_thickness_unit", "MM") == "UM":
        value /= 1000.0
    return value


def _set_manual_thickness_display_from_mm(settings, value_mm):
    value_mm = max(0.0, float(value_mm))
    if getattr(settings, "manual_thickness_unit", "MM") == "UM":
        settings.manual_thickness_value = value_mm * 1000.0
    else:
        settings.manual_thickness_value = value_mm


def _selected_peak_from_print_profile(settings, lpi):
    selection = getattr(settings, "print_profile", "RECOMMENDED")
    if selection == "THEORETICAL":
        peak = _theoretical_optimal_peak_mm(settings, lpi)
    elif selection == "MANUAL":
        peak = _manual_thickness_mm(settings)
        if peak <= 0.0:
            peak = _theoretical_optimal_peak_mm(settings, lpi) if _uses_theoretical_optics(settings) else _recommended_peak(lpi)
    else:
        factor = 0.90 if selection == "LOWER" else (1.10 if selection == "HIGHER" else 1.00)
        peak = _reference_scaled_peak(lpi) * factor
    # Blender's resolved geometry property is constrained to the printer's hard limit.
    peak = min(MAX_PEAK_MM, max(0.0, peak))
    if 0.0 < peak < MIN_NONZERO_PEAK_MM:
        peak = MIN_NONZERO_PEAK_MM
    return peak


def _selected_base_from_mode(settings, lpi, peak_mm):
    peak_mm = max(0.0, min(MAX_PEAK_MM, float(peak_mm)))
    selection = getattr(settings, "base_mode", "RECOMMENDED")
    reference = _recommended_base_for_peak(lpi, peak_mm)
    theoretical = _theoretical_base_for_selected_peak(settings, lpi, peak_mm)
    active_recommended = theoretical if _uses_theoretical_optics(settings) and theoretical >= 0.0 else reference
    if selection == "THEORETICAL":
        return max(0.0, theoretical) if theoretical >= 0.0 else min(peak_mm, MIN_NONZERO_BASE_MM)
    if selection == "NONE":
        return 0.0
    if selection == "MINIMUM":
        return min(peak_mm, MIN_NONZERO_BASE_MM)
    if selection == "RAISED":
        raised = active_recommended + max(0.10, (peak_mm - active_recommended) * 0.25)
        if 0.0 < raised < MIN_NONZERO_BASE_MM:
            raised = MIN_NONZERO_BASE_MM
        return max(0.0, min(peak_mm, raised))
    if selection == "MANUAL":
        return _clamp_manual_base(getattr(settings, "manual_base_mm", active_recommended), peak_mm)
    return reference


def _infer_print_profile(lpi, peak_mm, settings=None):
    peak_mm = max(0.0, float(peak_mm))
    candidates = {
        "LOWER": min(MAX_PEAK_MM, _reference_scaled_peak(lpi) * 0.90),
        "RECOMMENDED": min(MAX_PEAK_MM, _reference_scaled_peak(lpi)),
        "HIGHER": min(MAX_PEAK_MM, _reference_scaled_peak(lpi) * 1.10),
    }
    if settings is not None:
        candidates["THEORETICAL"] = min(MAX_PEAK_MM, _theoretical_optimal_peak_mm(settings, lpi))
    best = min(candidates, key=lambda key: abs(candidates[key] - peak_mm))
    tolerance = max(0.005, candidates[best] * 0.01)
    return best if abs(candidates[best] - peak_mm) <= tolerance else "MANUAL"


def _infer_base_mode(lpi, peak_mm, base_mm, settings=None):
    peak_mm = max(0.0, float(peak_mm))
    base_mm = max(0.0, min(peak_mm, float(base_mm)))
    reference = _recommended_base_for_peak(lpi, peak_mm)
    active = reference
    candidates = {
        "RECOMMENDED": reference,
        "NONE": 0.0,
        "MINIMUM": min(peak_mm, MIN_NONZERO_BASE_MM),
    }
    if settings is not None:
        theoretical = _theoretical_base_for_selected_peak(settings, lpi, peak_mm)
        if theoretical >= 0.0:
            candidates["THEORETICAL"] = theoretical
            if _uses_theoretical_optics(settings):
                active = theoretical
    candidates["RAISED"] = max(0.0, min(peak_mm, active + max(0.10, (peak_mm - active) * 0.25)))
    best = min(candidates, key=lambda key: abs(candidates[key] - base_mm))
    tolerance = max(0.005, max(peak_mm, 0.001) * 0.01)
    return best if abs(candidates[best] - base_mm) <= tolerance else "MANUAL"


def _apply_local_optical_rules(settings, changed_priority=None):
    if settings.workflow == "HEIGHTMAP":
        _apply_imported_heightmap_settings(settings)
        return
    if _state["applying"]:
        return
    mode = getattr(settings, "settings_mode", "AUTOMATIC")
    if changed_priority and mode == "SEMI":
        _set_priority_silent(settings, changed_priority)
    lpi = max(0.001, float(settings.lpi))
    previous = _state["applying"]
    _state["applying"] = True
    try:
        if _lens_free_mode(settings):
            if mode == "AUTOMATIC":
                settings.lpi_helper_mode = "RECOMMENDED"
                settings.lpi_helper_preset = "BALANCED"
            elif mode == "MANUAL":
                settings.lpi_helper_mode = "MANUAL"

            if settings.lpi_helper_mode == "RECOMMENDED":
                targets = _recommended_lpi_targets(settings)
                key = getattr(settings, "lpi_helper_preset", "BALANCED")
                if key not in targets:
                    key = "BALANCED"
                settings.lpi = float(targets[key][0])

            if mode == "AUTOMATIC":
                settings.relief_prism_height_mm = _recommended_relief_prism_height_mm(settings)

            spread, base, rise, peak = _relief_required_geometry(settings)
            settings.thickness_mm = max(0.0, min(MAX_PEAK_MM, peak))
            settings.base_mm = max(0.0, min(settings.thickness_mm, base))
            settings.rise_mm = max(0.0, settings.thickness_mm - settings.base_mm)
            settings.viewing_angle_deg = spread
            return
        if mode == "AUTOMATIC":
            # Automatic keeps Lens Type selectable so the user can choose the
            # calibrated automatic path or the mathematical automatic path.
            if getattr(settings, "lens_profile", "AUTO") in {"AUTO_THEORETICAL", "THEORETICAL"}:
                settings.print_profile = "THEORETICAL"
                settings.base_mode = "THEORETICAL"
            else:
                settings.print_profile = "RECOMMENDED"
                settings.base_mode = "RECOMMENDED"

        selected_peak = _peak_for_viewing_angle(settings, _recommended_viewing_angle(settings))

        if mode == "SEMI" and not _custom_viewing_angle_active(settings) and getattr(settings, "base_mode", "RECOMMENDED") == "MANUAL":
            if _uses_theoretical_optics(settings):
                normal_base = _theoretical_base_for_selected_peak(settings, lpi, selected_peak)
                if normal_base < 0.0:
                    normal_base = min(selected_peak, MIN_NONZERO_BASE_MM)
            else:
                normal_base = _recommended_base_for_peak(lpi, selected_peak)
            selected_rise = max(0.0, selected_peak - normal_base)
            manual_base = _clamp_manual_base(getattr(settings, "manual_base_mm", normal_base), MAX_PEAK_MM)
            peak = min(MAX_PEAK_MM, max(manual_base, manual_base + selected_rise))
            base = min(manual_base, peak)
        else:
            peak = selected_peak
            base = _selected_base_from_mode(settings, lpi, peak)

        settings.thickness_mm = max(0.0, min(MAX_PEAK_MM, peak))
        if 0.0 < settings.thickness_mm < MIN_NONZERO_PEAK_MM:
            settings.thickness_mm = MIN_NONZERO_PEAK_MM
        settings.base_mm = max(0.0, min(settings.thickness_mm, base))
        settings.rise_mm = max(0.0, settings.thickness_mm - settings.base_mm)

        # Keep the manual override fields seeded with the currently resolved geometry
        # whenever those fields are not authoritative. This makes the disabled fields
        # useful as current-value readouts and ensures switching to Manual starts from
        # the exact geometry that was already active.
        if getattr(settings, "print_profile", "RECOMMENDED") != "MANUAL":
            _set_manual_thickness_display_from_mm(settings, settings.thickness_mm)
        if getattr(settings, "base_mode", "RECOMMENDED") != "MANUAL":
            settings.manual_base_mm = settings.base_mm

        if _custom_viewing_angle_active(settings):
            settings.viewing_angle_deg = max(1.0, min(179.0, float(settings.custom_viewing_angle_deg)))
        else:
            settings.viewing_angle_deg = max(1.0, min(179.0, _viewing_angle_for_peak(settings)))
    finally:
        _state["applying"] = previous


def _validate_theoretical_printability(settings):
    if settings.workflow == "HEIGHTMAP":
        return  # Imported samples, not a procedural theoretical profile.
    if _lens_free_mode(settings):
        if int(settings.views) != _relief_supported_view_count():
            raise RuntimeError("Lens-Free Relief currently supports exactly 2 views using the corrected naked-eye prism baseline.")
        spread, base, rise, peak = _relief_required_geometry(settings)
        if 0.0 < base < MIN_NONZERO_BASE_MM - 1e-6:
            raise RuntimeError(f"Lens-Free Relief base must be 0.00 mm or at least {MIN_NONZERO_BASE_MM:.2f} mm.")
        if peak > MAX_PEAK_MM + 1e-6:
            raise RuntimeError(
                f"Lens-Free Relief requires {peak:.3f} mm total height for {int(settings.views)} views at "
                f"{float(settings.lpi):.3f} LPI and {spread:.1f} deg facet spread. This exceeds the {MAX_PEAK_MM:.2f} mm printer limit."
            )
        return
    if _custom_viewing_angle_active(settings):
        angle_required = _peak_for_viewing_angle(settings, settings.custom_viewing_angle_deg)
        if angle_required > MAX_PEAK_MM + 1e-6:
            raise RuntimeError(
                f"Custom viewing angle {settings.custom_viewing_angle_deg:.1f} deg requires {angle_required:.2f} mm Thickness, "
                f"which exceeds the {MAX_PEAK_MM:.2f} mm printer limit."
            )
        if 0.0 < angle_required < MIN_NONZERO_PEAK_MM - 1e-6:
            raise RuntimeError(
                f"Custom viewing angle {settings.custom_viewing_angle_deg:.1f} deg requires {angle_required:.2f} mm Thickness, "
                f"below the {MIN_NONZERO_PEAK_MM:.2f} mm minimum non-zero print height."
            )
        if _uses_theoretical_optics(settings):
            minimum = _theoretical_minimum_peak_mm(settings)
            if angle_required + 1e-6 < minimum:
                raise RuntimeError(
                    f"Custom viewing angle {settings.custom_viewing_angle_deg:.1f} deg requires {angle_required:.2f} mm Thickness, "
                    f"below the {minimum:.2f} mm full-aperture mathematical minimum at this LPI and IOR."
                )
            exact_valley = _theoretical_base_for_peak_mm(settings, settings.lpi, angle_required)
            if 0.0 < exact_valley < MIN_NONZERO_BASE_MM - 1e-6:
                raise RuntimeError(
                    f"Custom viewing angle {settings.custom_viewing_angle_deg:.1f} deg requires a {exact_valley:.2f} mm theoretical valley, "
                    f"below the {MIN_NONZERO_BASE_MM:.2f} mm printer minimum. Choose a narrower angle, higher LPI, or different optical mode."
                )
    if not _uses_theoretical_optics(settings):
        return
    required = _theoretical_optimal_peak_mm(settings)
    if required > MAX_PEAK_MM + 1e-6:
        raise RuntimeError(
            f"Mathematically Optimal requires {required:.2f} mm peak height at this LPI and IOR, "
            f"which exceeds the {MAX_PEAK_MM:.2f} mm printer limit. Choose a higher LPI, "
            "a different optical mode, or change the material IOR."
        )
    if _resolved_local_profile(settings) == "THEORETICAL":
        minimum = _theoretical_minimum_peak_mm(settings)
        if float(settings.thickness_mm) + 1e-6 < minimum:
            raise RuntimeError(
                f"The selected Thickness is below the full-aperture mathematical minimum of {minimum:.2f} mm "
                "for this LPI and IOR."
            )


def _optical_solver_summary(settings):
    mode = getattr(settings, "settings_mode", "AUTOMATIC")
    mathematical = _uses_theoretical_optics(settings)
    if mathematical:
        required = _theoretical_optimal_peak_mm(settings)
        if required > MAX_PEAK_MM + 1e-6:
            basis = f"MATHEMATICAL OPTICS. Ideal peak {required:.2f} mm exceeds the 5.00 mm printer limit."
        else:
            valley = _theoretical_base_for_selected_peak(settings, settings.lpi, required)
            basis = f"MATHEMATICAL OPTICS. First-principles optimum: {required:.2f} mm peak, {max(0.0, valley):.2f} mm valley."
    else:
        basis = "REFERENCE OPTICS. Uses the proven 15 LPI calibrated geometry."
    angle_basis = f" Viewing-angle target: {_viewing_angle_mode_label(settings)} - {_recommended_viewing_angle(settings):.1f} deg."
    if mode == "AUTOMATIC":
        return "AUTOMATIC MODE. " + basis + angle_basis
    if mode == "SEMI":
        return "SEMI-AUTOMATIC MODE. Dependent geometry is recalculated. " + basis + angle_basis
    return "MANUAL MODE. Selected choices are used directly. " + basis + angle_basis


def _lens_profile_changed(self, context):
    if _state["applying"]:
        return
    previous = _state["applying"]
    _state["applying"] = True
    try:
        if self.settings_mode in {"AUTOMATIC", "SEMI"}:
            if self.lens_profile in {"AUTO_THEORETICAL", "THEORETICAL"}:
                self.print_profile = "THEORETICAL"
                self.base_mode = "THEORETICAL"
            else:
                self.print_profile = "RECOMMENDED"
                self.base_mode = "RECOMMENDED"
    finally:
        _state["applying"] = previous
    if self.settings_mode == "SEMI":
        _set_priority_silent(self, "lens_profile")
    _apply_local_optical_rules(self, "lens_profile" if self.settings_mode == "SEMI" else None)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _print_profile_changed(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self, "thickness_mm" if self.settings_mode == "SEMI" else None)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _base_mode_changed(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self, "base_mm" if self.settings_mode == "SEMI" else None)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _manual_thickness_changed(self, context):
    if _state["applying"]:
        return
    if getattr(self, "print_profile", "RECOMMENDED") == "MANUAL":
        _apply_local_optical_rules(self, "thickness_mm" if self.settings_mode == "SEMI" else None)
        _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _manual_thickness_unit_changed(self, context):
    if _state["applying"]:
        return
    previous_unit = getattr(self, "manual_thickness_unit_last", "MM") or "MM"
    new_unit = getattr(self, "manual_thickness_unit", "MM") or "MM"
    previous_applying = _state["applying"]
    _state["applying"] = True
    try:
        if previous_unit != new_unit:
            value = max(0.0, float(getattr(self, "manual_thickness_value", 0.0)))
            if previous_unit == "MM" and new_unit == "UM":
                value *= 1000.0
            elif previous_unit == "UM" and new_unit == "MM":
                value /= 1000.0
            self.manual_thickness_value = value
        self.manual_thickness_unit_last = new_unit
    finally:
        _state["applying"] = previous_applying
    if getattr(self, "print_profile", "RECOMMENDED") == "MANUAL":
        _apply_local_optical_rules(self, "thickness_mm" if self.settings_mode == "SEMI" else None)
        _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _manual_base_changed(self, context):
    if _state["applying"]:
        return
    if getattr(self, "base_mode", "RECOMMENDED") == "MANUAL":
        _apply_local_optical_rules(self, "base_mm" if self.settings_mode == "SEMI" else None)
        _queue_reactive(self, context, "geometry", rebuild_lens=True)

def _relief_base_changed(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _relief_height_changed(self, context):
    if _state["applying"]:
        return
    priority = "relief_prism_height_mm" if self.settings_mode == "SEMI" else None
    if priority:
        _set_priority_silent(self, priority)
    _apply_local_optical_rules(self, priority)
    _queue_reactive(self, context, "geometry", priority=priority, rebuild_lens=True)


def _mode_changed(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _priority_selection_changed(self, context):
    if _state["applying"]:
        return
    if self.settings_mode == "SEMI":
        _apply_local_optical_rules(self)
        _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _mark_views_change(self, context):
    if _state["applying"]:
        return
    _apply_lpi_helper(self)
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "geometry", rebuild_interlace=(self.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}), rebuild_lens=True, refresh_texture=True)


def _run_output_mode_rebuild_once():
    """Deterministic first-pass rebuild for an Output Mode change.

    This timer is the authoritative first consumer of an output-mode request.
    It rebuilds the mode-dependent interlaced/color image before the ordinary
    reactive/sync loop is allowed to run, then rebuilds the visible scene from
    that just-generated settings asset rather than from the older project.json.
    """
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is None or not hasattr(scene, "lenticular_sync"):
            _state["mode_rebuild_timer_registered"] = False
            return None
        settings = scene.lenticular_sync

        # Blender property updates and sync application can briefly overlap this
        # callback. Keep this one timer alive until the current operation is done.
        if _state.get("applying", False) or _state.get("reactive_busy", False):
            return 0.02

        serial = int(_state.get("mode_rebuild_serial", 0))
        requested_mode = str(_state.get("mode_rebuild_requested_mode", "") or settings.output_mode)

        # If another mode was selected before this timer ran, consume only the
        # newest request. The serial and requested mode are updated by the RNA
        # callback before this timer receives control.
        if requested_mode and str(settings.output_mode) != requested_mode:
            _state["mode_rebuild_requested_mode"] = str(settings.output_mode)
            return 0.01

        if not settings.auto_rebuild:
            _state["mode_rebuild_timer_registered"] = False
            _state["mode_transaction_active"] = False
            return None

        _state["reactive_busy"] = True
        status_parts = []
        try:
            upstream_valid = True

            if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
                frame_count = len(_source_frame_paths(settings))
                required_ok = frame_count >= 2 and (not _lens_free_mode(settings) or frame_count == _relief_supported_view_count())
                if required_ok:
                    try:
                        # Rebuild unconditionally for every new Output Mode serial.
                        # Do not depend on the ordinary pending/debounce state.
                        out_path, out_w, out_h, ppl = _build_interlaced_image(settings)
                        _state["pending_interlace"] = False
                        _state["pending_heightmap"] = True
                        _state["pending_lens"] = True
                        _state["pending_texture"] = True
                        _state["mode_rebuild_consumed_serial"] = serial
                        status_parts.append(f"Mode change: rebuilt interlace {out_w}x{out_h}")
                    except Exception as exc:
                        upstream_valid = False
                        status_parts.append("Mode-change interlace blocked: " + str(exc))
                else:
                    upstream_valid = False
                    if _lens_free_mode(settings):
                        status_parts.append(f"Lens-Free Relief requires exactly {_relief_supported_view_count()} source images; found {frame_count}")
                    else:
                        status_parts.append("Add at least 2 source images for automatic interlacing")
            else:
                image_path = _resolve_project_relative(settings, settings.interlaced_image)
                upstream_valid = bool(image_path is not None and image_path.is_file())
                if not upstream_valid:
                    status_parts.append("Mode change is waiting for a valid existing interlaced image")

            # Rebuild from the current settings asset. Passing an empty project is
            # deliberate: _rebuild_scene must not reload the older interlaced asset
            # path from project.json before this local mode transaction is published.
            if upstream_valid and _state.get("pending_lens", False):
                image_path = _resolve_project_relative(settings, settings.interlaced_image)
                if image_path is not None and image_path.is_file():
                    try:
                        _rebuild_scene(bpy.context, project={})
                        bpy.context.view_layer.update()
                        _state["pending_lens"] = False
                        _state["pending_texture"] = False
                        _state["heightmap_due_time"] = time.time() + 0.20
                        status_parts.append("3D model rebuilt")
                    except Exception as exc:
                        status_parts.append("Mode-change 3D rebuild blocked: " + str(exc))
                else:
                    upstream_valid = False
                    status_parts.append("Mode-change 3D rebuild waiting for the regenerated image")

            _state["dirty"] = True
            _state["dirty_scope"] = "geometry"
            _state["reactive_origin"] = "local"
            _state["last_change_time"] = 0.0
            if status_parts:
                _set_status(settings, " | ".join(status_parts))
        finally:
            _state["reactive_busy"] = False
            _state["mode_rebuild_timer_registered"] = False

    except Exception as exc:
        _state["mode_rebuild_timer_registered"] = False
        try:
            settings = bpy.context.scene.lenticular_sync
            _set_status(settings, "Mode-change rebuild failed: " + str(exc))
        except Exception:
            print("Lenticulizer mode-change rebuild failed:", exc)
    return None

def _output_mode_rebuild_prerequisites_ready(settings):
    if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
        frame_count = len(_source_frame_paths(settings))
        return frame_count >= 2 and (not _lens_free_mode(settings) or frame_count == _relief_supported_view_count())
    image_path = _resolve_project_relative(settings, settings.interlaced_image)
    return bool(image_path is not None and image_path.is_file())


def _schedule_output_mode_rebuild(settings, context):
    """Invalidate old mode assets and guarantee one first-pass mode rebuild."""
    if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
        settings.interlaced_image = ""
        _state["pending_interlace"] = True
    else:
        _state["pending_interlace"] = False

    settings.heightmap_image = ""
    _state["pending_heightmap"] = True
    _state["pending_lens"] = True
    _state["pending_texture"] = True
    _state["heightmap_due_time"] = 0.0
    _state["dirty"] = True
    _state["dirty_scope"] = "geometry"
    _state["last_change_time"] = 0.0
    _state["mode_rebuild_serial"] = int(_state.get("mode_rebuild_serial", 0)) + 1
    _state["mode_rebuild_requested_mode"] = str(settings.output_mode)
    _state["mode_transaction_active"] = True
    _state["mode_transaction_started"] = time.time()
    _state["reactive_origin"] = "local"

    # Always replace any stale pending mode timer with a fresh timer for the exact
    # current selection. This removes the previous logical-registered state where
    # the first click could be invalidated but never actually consumed.
    try:
        if bpy.app.timers.is_registered(_run_output_mode_rebuild_once):
            bpy.app.timers.unregister(_run_output_mode_rebuild_once)
    except Exception:
        pass

    _state["mode_rebuild_timer_registered"] = True
    try:
        bpy.app.timers.register(_run_output_mode_rebuild_once, first_interval=0.01)
    except Exception:
        # The ordinary reactive timer remains a fallback if Blender refuses timer
        # registration for an unusual context.
        _state["mode_rebuild_timer_registered"] = False

def _output_mode_changed(self, context):
    if _state["applying"]:
        return
    _apply_lpi_helper(self)
    _apply_local_optical_rules(self)
    _schedule_output_mode_rebuild(self, context)

def _queue_reactive(settings, context, sync_scope="geometry", priority=None, rebuild_interlace=False, rebuild_lens=False, refresh_texture=False):
    if _state["applying"]:
        return
    if settings.workflow == "HEIGHTMAP" and rebuild_lens:
        rebuild_interlace = True
    if priority:
        settings.priority = priority
    _state["dirty"] = True
    _state["dirty_scope"] = sync_scope
    _state["reactive_origin"] = "local"
    _state["last_change_time"] = time.time()
    if rebuild_interlace:
        _state["pending_interlace"] = True
        _state["pending_heightmap"] = True
        if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
            _state["app_rebuild_pair_requested"] = True
    if rebuild_lens:
        _state["pending_heightmap"] = True
        _state["pending_lens"] = True
        if not _state.get("app_rebuild_pair_requested", False):
            _state["app_rebuild_heightmap_requested"] = True
    if refresh_texture:
        _state["pending_texture"] = True


def _mark_dirty_scope(scope):
    def callback(self, context):
        if _state["applying"]:
            return
        if scope == "images":
            _apply_local_optical_rules(self)
            _queue_reactive(self, context, "images", rebuild_interlace=(self.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}), rebuild_lens=True, refresh_texture=True)
        elif scope == "geometry":
            _apply_local_optical_rules(self)
            _queue_reactive(self, context, "geometry", rebuild_lens=True)
        else:
            _queue_reactive(self, context, scope)
    return callback


def _mark_dirty(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _mark_priority(priority):
    def callback(self, context):
        if _state["applying"]:
            return
        if self.settings_mode == "SEMI":
            _set_priority_silent(self, priority)
        _apply_local_optical_rules(self, priority if self.settings_mode == "SEMI" else None)
        _queue_reactive(self, context, "geometry", rebuild_lens=True)
    return callback


def _mark_interlace_geometry(self, context):
    if _state["applying"]:
        return
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "geometry", rebuild_interlace=(self.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}), rebuild_lens=True, refresh_texture=True)


def _mark_lpi_interlace(self, context):
    if _state["applying"]:
        return
    if self.settings_mode == "SEMI":
        _set_priority_silent(self, "lpi")
    _apply_local_optical_rules(self, "lpi" if self.settings_mode == "SEMI" else None)
    _queue_reactive(self, context, "geometry", rebuild_interlace=(self.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}), rebuild_lens=True, refresh_texture=True)


def _mark_interlace_setting(self, context):
    if _state["applying"]:
        return
    _apply_lpi_helper(self)
    _apply_local_optical_rules(self)
    _queue_reactive(self, context, "settings", rebuild_interlace=(self.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}), rebuild_lens=True, refresh_texture=True)


def _resolve_asset(project, key, settings):
    assets = project.get("assets", {}) if isinstance(project, dict) else {}
    name = assets.get(key, "")
    if not name:
        if key == "interlaced_image":
            name = settings.interlaced_image
        elif key == "heightmap":
            name = settings.heightmap_image
    if not name:
        return None
    path = Path(name)
    if path.is_absolute():
        return path
    base = _project_dir(settings)
    return (base / path) if base else path


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json_atomic(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)
        handle.write("\n")
    os.replace(temp, path)


def _app_handoff_dirs():
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return []
    root = Path(local_app_data)
    # Lenticulizer is the current application name. Keep the legacy folder in the
    # search/write set so existing installs and older shared projects continue to work.
    return [
        root / "Lenticulizer",
        root / "Lenticular Lens Heightmap Generator",
    ]


def _pending_handoff_paths():
    return [folder / "pending_blender_project.txt" for folder in _app_handoff_dirs()]


def _consume_pending_project_handoff():
    # The Windows app writes handoff pointers to both the current and legacy
    # LocalAppData locations for compatibility. Treat those files as one logical
    # one-time handoff. Delete every duplicate before returning so a second copy
    # cannot reconnect Blender immediately after Close Project.
    candidates = []
    closed_at = float(_state.get("project_closed_at", 0.0) or 0.0)
    for pointer in _pending_handoff_paths():
        if not pointer.is_file():
            continue
        try:
            stat = pointer.stat()
            mtime = float(stat.st_mtime)
            age = max(0.0, time.time() - mtime)
            raw = pointer.read_text(encoding="utf-8").strip()
            try:
                pointer.unlink()
            except Exception:
                pass
            # Ignore stale handoffs and anything that predates the user's most
            # recent explicit Close Project action.
            if age > 180.0 or mtime <= closed_at:
                continue
            path = Path(raw)
            if path.is_dir():
                path = path / "project.json"
            if path.is_file():
                candidates.append((mtime, path))
        except Exception:
            try:
                pointer.unlink()
            except Exception:
                pass

    if not candidates:
        return None
    # If multiple valid handoffs were published, use only the newest one.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _clear_blender_project_handoff_pointers(clear_current=True):
    names = ["pending_blender_project.txt"]
    if clear_current:
        names.append("current_blender_project.txt")
    for folder in _app_handoff_dirs():
        for name in names:
            pointer = folder / name
            try:
                if pointer.is_file():
                    pointer.unlink()
            except Exception:
                pass


def _pending_app_handoff_paths():
    return [folder / "pending_app_project.txt" for folder in _app_handoff_dirs()]


def _publish_app_project_handoff(project_path):
    payload = str(Path(project_path).resolve())
    wrote_any = False
    for pointer in _pending_app_handoff_paths():
        try:
            pointer.parent.mkdir(parents=True, exist_ok=True)
            pointer.write_text(payload, encoding="utf-8")
            wrote_any = True
        except Exception:
            pass
    return wrote_any


def _find_project_from_scene(context):
    scene = context.scene
    custom = scene.get("lenticular_project_file", "")
    if custom:
        path = Path(str(custom))
        if path.is_file():
            return path
    env_dir = os.environ.get("LENTICULAR_SIM_DIR", "")
    if env_dir:
        candidate = Path(env_dir) / "project.json"
        if candidate.is_file():
            return candidate
    for folder in _app_handoff_dirs():
        pointer = folder / "current_blender_project.txt"
        try:
            if pointer.is_file():
                pointed = Path(pointer.read_text(encoding="utf-8").strip())
                if pointed.is_dir():
                    pointed = pointed / "project.json"
                if pointed.is_file():
                    return pointed
        except Exception:
            pass
    if bpy.data.filepath:
        candidate = Path(bpy.data.filepath).parent / "project.json"
        if candidate.is_file():
            return candidate
    return None


def _profile_items():
    return [
        ("AUTO", "Auto Recommended", "Use the calibrated automatic recommendation"),
        ("AUTO_THEORETICAL", "Auto Mathematically Optimal", "Use first-principles aplanatic aspheric optics from LPI and IOR"),
        ("REFERENCE", "Reference Calibrated", "Use the known-good calibrated profile"),
        ("THEORETICAL", "Mathematically Optimal Aspheric", "Exact aplanatic aspheric profile calculated from lenticule pitch and IOR"),
        ("ASPHERIC", "Aspheric", "General aspheric lens profile"),
        ("CIRCULAR", "Rounded / Circular", "Circular lens profile"),
        ("PRISMATIC", "Multi-facet / Prismatic", "Faceted profile"),
        ("TRIANGULAR", "Linear / Triangular", "Triangular profile"),
        ("COSINE", "Cosine", "Cosine profile"),
    ]


def _print_profile_items():
    return [
        ("LOWER", "Lower Thickness", "Use 90 percent of the calibrated reference Thickness"),
        ("RECOMMENDED", "Recommended (Reference Calibrated)", "Use the calibrated reference Thickness"),
        ("THEORETICAL", "Mathematically Optimal", "Use the first-principles full-aperture optical Thickness"),
        ("HIGHER", "Higher Thickness", "Use 110 percent of the calibrated reference Thickness"),
        ("MANUAL", "Manual Thickness", "Enter the exact UV printer Thickness manually"),
    ]


def _base_mode_items():
    return [
        ("RECOMMENDED", "Recommended (Reference Calibrated)", "Use the calibrated reference valley height"),
        ("THEORETICAL", "Mathematically Optimal", "Use the exact theoretical aspheric edge/valley height"),
        ("NONE", "No base", "Use a 0.00 mm valley/base"),
        ("MINIMUM", "Printer minimum", "Use the configured minimum non-zero printed height"),
        ("RAISED", "Raised base", "Raise the valley above the active recommendation"),
        ("MANUAL", "Manual base height", "Enter the exact valley/base height manually"),
    ]


def _print_profile_label(value):
    return {
        "LOWER": "Lower Thickness",
        "RECOMMENDED": "Recommended (Reference Calibrated)",
        "THEORETICAL": "Mathematically Optimal",
        "HIGHER": "Higher Thickness",
        "MANUAL": "Manual Thickness",
    }.get(value, "Recommended (Reference Calibrated)")


def _base_mode_label(value):
    return {
        "RECOMMENDED": "Recommended (Reference Calibrated)",
        "THEORETICAL": "Mathematically Optimal",
        "NONE": "No base",
        "MINIMUM": "Printer minimum",
        "RAISED": "Raised base",
        "MANUAL": "Manual base height",
    }.get(value, "Recommended (Reference Calibrated)")


def _profile_to_enum(text):
    low = (text or "").lower()
    if "mathemat" in low or "theoret" in low:
        return "AUTO_THEORETICAL" if "auto" in low else "THEORETICAL"
    if "reference" in low:
        return "REFERENCE"
    if "aspheric" in low:
        return "ASPHERIC"
    if "circular" in low or "rounded" in low:
        return "CIRCULAR"
    if "prismatic" in low or "facet" in low:
        return "PRISMATIC"
    if "triangular" in low or "linear" in low:
        return "TRIANGULAR"
    if "cosine" in low:
        return "COSINE"
    return "AUTO"


def _enum_to_profile(value):
    return {
        "AUTO": "Auto Recommended",
        "AUTO_THEORETICAL": "Auto Mathematically Optimal",
        "REFERENCE": "Reference Calibrated",
        "THEORETICAL": "Mathematically Optimal Aspheric",
        "ASPHERIC": "Aspheric",
        "CIRCULAR": "Rounded / Circular",
        "PRISMATIC": "Multi-facet / Prismatic",
        "TRIANGULAR": "Linear / Triangular",
        "COSINE": "Cosine",
    }.get(value, "Auto Recommended")


def _resin_preset_items():
    return [
        ("PERFECT", "Perfect Optical", "Ideal polished surface with no simulated surface scatter"),
        ("SMOOTH", "Smooth UV Clear", "Smoother clear UV surface with moderate optical scatter"),
        ("CALIBRATED", "Calibrated UV Clear", "Current printer/material calibration based on the real printed result"),
        ("TYPICAL", "Typical UV Clear", "Higher optical scatter with visible cured-surface texture"),
        ("ROUGH", "Rough UV Clear", "Strong scatter and stronger cured-surface texture"),
        ("CUSTOM", "Custom", "Use the values below without preset changes"),
    ]


def _find_lens_material(material=None):
    if material is not None:
        return material
    lens_obj = bpy.data.objects.get(OBJECT_PREFIX + "LenticularLens")
    if lens_obj and getattr(lens_obj.data, "materials", None) and len(lens_obj.data.materials):
        return lens_obj.data.materials[0]
    return bpy.data.materials.get(OBJECT_PREFIX + "LensMat")


def _surface_shader_node(material):
    if not material or not material.use_nodes:
        return None
    nt = material.node_tree
    nodes = nt.nodes
    output = nodes.get("Material Output")
    if output is None:
        return None
    surface_links = [
        link for link in nt.links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1:
        return None
    return surface_links[0].from_node


def _surface_refraction_node(material):
    node = _surface_shader_node(material)
    if node is not None and (
        getattr(node, "bl_idname", "") == "ShaderNodeBsdfRefraction"
        or getattr(node, "type", "") == "BSDF_REFRACTION"
    ):
        return node
    return None


def _surface_emission_node(material):
    node = _surface_shader_node(material)
    if node is not None and (
        getattr(node, "bl_idname", "") == "ShaderNodeEmission"
        or getattr(node, "type", "") == "EMISSION"
    ):
        return node
    return None


def _surface_diffuse_node(material):
    node = _surface_shader_node(material)
    if node is not None and (
        getattr(node, "bl_idname", "") == "ShaderNodeBsdfDiffuse"
        or getattr(node, "type", "") == "BSDF_DIFFUSE"
    ):
        return node
    return None


def _generated_material_needs_display_migration(name, material):
    if not material or not material.use_nodes:
        return False
    if name.endswith("LensMat"):
        # Optical lens must keep refraction but lose any alternative surface shader.
        if _surface_refraction_node(material) is None:
            return True
        for node in material.node_tree.nodes:
            if getattr(node, "bl_idname", "") in {"ShaderNodeBsdfPrincipled", "ShaderNodeEmission", "ShaderNodeBsdfDiffuse"}:
                return True
            if getattr(node, "type", "") in {"BSDF_PRINCIPLED", "EMISSION", "BSDF_DIFFUSE"}:
                return True
        return False

    if name.endswith("PrintMat"):
        emission = _surface_emission_node(material)
        if emission is None:
            return True
        has_image_link = any(
            link.to_node == emission and getattr(link.to_socket, "name", "") == "Color" and
            getattr(link.from_node, "type", "") == "TEX_IMAGE"
            for link in material.node_tree.links
        )
        if not has_image_link:
            return True
        for node in material.node_tree.nodes:
            if getattr(node, "bl_idname", "") in {"ShaderNodeBsdfPrincipled", "ShaderNodeBsdfRefraction", "ShaderNodeBsdfDiffuse"}:
                return True
            if getattr(node, "type", "") in {"BSDF_PRINCIPLED", "BSDF_REFRACTION", "BSDF_DIFFUSE"}:
                return True
        return False

    if name.endswith("SubstrateMat"):
        if _surface_diffuse_node(material) is None:
            return True
        for node in material.node_tree.nodes:
            if getattr(node, "bl_idname", "") in {"ShaderNodeBsdfPrincipled", "ShaderNodeBsdfRefraction", "ShaderNodeEmission"}:
                return True
            if getattr(node, "type", "") in {"BSDF_PRINCIPLED", "BSDF_REFRACTION", "EMISSION"}:
                return True
        return False

    return False


def _ensure_refraction_material(material, color, roughness, ior, image_texture=None):
    if material is None:
        return None
    material.use_nodes = True
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"

    refraction = None
    for candidate in nodes:
        if getattr(candidate, "bl_idname", "") == "ShaderNodeBsdfRefraction" or getattr(candidate, "type", "") == "BSDF_REFRACTION":
            refraction = candidate
            break
    if refraction is None:
        refraction = nodes.new("ShaderNodeBsdfRefraction")
    refraction.name = "Refraction BSDF"
    refraction.label = "Refraction BSDF"

    if "Color" in refraction.inputs:
        if image_texture is None:
            refraction.inputs["Color"].default_value = color
        else:
            linked = any(
                link.from_socket == image_texture.outputs.get("Color")
                and link.to_socket == refraction.inputs["Color"]
                for link in links
            )
            if not linked:
                for link in list(links):
                    if link.to_socket == refraction.inputs["Color"]:
                        links.remove(link)
                links.new(image_texture.outputs["Color"], refraction.inputs["Color"])

    if "Roughness" in refraction.inputs:
        refraction.inputs["Roughness"].default_value = max(0.0, min(1.0, float(roughness)))
    if "IOR" in refraction.inputs:
        refraction.inputs["IOR"].default_value = max(1.0, float(ior))

    surface_links = [
        link for link in links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1 or surface_links[0].from_node != refraction:
        for link in surface_links:
            links.remove(link)
        links.new(refraction.outputs["BSDF"], output.inputs["Surface"])

    for node in list(nodes):
        if node in {output, refraction, image_texture}:
            continue
        node_type = getattr(node, "bl_idname", "")
        short_type = getattr(node, "type", "")
        if node_type in {"ShaderNodeBsdfPrincipled", "ShaderNodeEmission", "ShaderNodeBsdfDiffuse"} or short_type in {"BSDF_PRINCIPLED", "EMISSION", "BSDF_DIFFUSE"}:
            nodes.remove(node)

    return refraction


def _ensure_emission_material(material, image_texture, strength=1.0):
    if material is None:
        return None
    material.use_nodes = True
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"

    emission = None
    for candidate in nodes:
        if getattr(candidate, "bl_idname", "") == "ShaderNodeEmission" or getattr(candidate, "type", "") == "EMISSION":
            emission = candidate
            break
    if emission is None:
        emission = nodes.new("ShaderNodeEmission")
    emission.name = "Emission"
    emission.label = "Emission"
    if "Strength" in emission.inputs:
        emission.inputs["Strength"].default_value = float(strength)

    if image_texture is not None and "Color" in emission.inputs:
        linked = any(
            link.from_socket == image_texture.outputs.get("Color")
            and link.to_socket == emission.inputs["Color"]
            for link in links
        )
        if not linked:
            for link in list(links):
                if link.to_socket == emission.inputs["Color"]:
                    links.remove(link)
            links.new(image_texture.outputs["Color"], emission.inputs["Color"])

    surface_links = [
        link for link in links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1 or surface_links[0].from_node != emission:
        for link in surface_links:
            links.remove(link)
        links.new(emission.outputs["Emission"], output.inputs["Surface"])

    for node in list(nodes):
        if node in {output, emission, image_texture}:
            continue
        node_type = getattr(node, "bl_idname", "")
        short_type = getattr(node, "type", "")
        if node_type in {"ShaderNodeBsdfPrincipled", "ShaderNodeBsdfRefraction", "ShaderNodeBsdfDiffuse"} or short_type in {"BSDF_PRINCIPLED", "BSDF_REFRACTION", "BSDF_DIFFUSE"}:
            nodes.remove(node)

    return emission


def _ensure_diffuse_material(material, color, roughness=0.0):
    if material is None:
        return None
    material.use_nodes = True
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"

    diffuse = None
    for candidate in nodes:
        if getattr(candidate, "bl_idname", "") == "ShaderNodeBsdfDiffuse" or getattr(candidate, "type", "") == "BSDF_DIFFUSE":
            diffuse = candidate
            break
    if diffuse is None:
        diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.name = "Diffuse BSDF"
    diffuse.label = "Diffuse BSDF"
    if "Color" in diffuse.inputs:
        diffuse.inputs["Color"].default_value = color
    if "Roughness" in diffuse.inputs:
        diffuse.inputs["Roughness"].default_value = max(0.0, min(1.0, float(roughness)))

    surface_links = [
        link for link in links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1 or surface_links[0].from_node != diffuse:
        for link in surface_links:
            links.remove(link)
        links.new(diffuse.outputs["BSDF"], output.inputs["Surface"])

    for node in list(nodes):
        if node in {output, diffuse}:
            continue
        node_type = getattr(node, "bl_idname", "")
        short_type = getattr(node, "type", "")
        if node_type in {"ShaderNodeBsdfPrincipled", "ShaderNodeBsdfRefraction", "ShaderNodeEmission"} or short_type in {"BSDF_PRINCIPLED", "BSDF_REFRACTION", "EMISSION"}:
            nodes.remove(node)

    return diffuse


def _generated_materials_need_display_migration():
    for name in (OBJECT_PREFIX + "SubstrateMat", OBJECT_PREFIX + "PrintMat", OBJECT_PREFIX + "LensMat"):
        material = bpy.data.materials.get(name)
        if material is not None and _generated_material_needs_display_migration(name, material):
            return True
    return False


def _ensure_all_generated_display_materials(settings):
    substrate = bpy.data.materials.get(OBJECT_PREFIX + "SubstrateMat")
    if substrate is not None:
        _ensure_diffuse_material(substrate, (0.9, 0.9, 0.9, 1.0), 0.0)

    print_mat = bpy.data.materials.get(OBJECT_PREFIX + "PrintMat")
    if print_mat is not None:
        tex = None
        for node in print_mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.name.startswith("LenticulizerImageTexture"):
                tex = node
                break
        _ensure_emission_material(print_mat, tex, 1.0)

    lens = bpy.data.materials.get(OBJECT_PREFIX + "LensMat")
    if lens is not None:
        _ensure_refraction_lens_material(settings, lens)


def _lens_material_needs_refraction_migration(material=None):
    material = _find_lens_material(material)
    if not material or not material.use_nodes:
        return False
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links
    output = nodes.get("Material Output")
    if output is None:
        return True

    refraction = nodes.get("Refraction BSDF")
    if refraction is None or getattr(refraction, "bl_idname", "") != "ShaderNodeBsdfRefraction":
        refraction = None
        for candidate in nodes:
            if getattr(candidate, "bl_idname", "") == "ShaderNodeBsdfRefraction" or getattr(candidate, "type", "") == "BSDF_REFRACTION":
                refraction = candidate
                break
    if refraction is None:
        return True

    # The optical lens should have Refraction BSDF as the only shader driving
    # Material Output.Surface. Merely having an unused Refraction node is not enough.
    surface_links = [
        link for link in links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1 or surface_links[0].from_node != refraction:
        return True

    # Remove a legacy Principled node only once during migration.
    for node in nodes:
        if getattr(node, "bl_idname", "") == "ShaderNodeBsdfPrincipled" or getattr(node, "type", "") == "BSDF_PRINCIPLED":
            return True

    return False


def _ensure_refraction_lens_material(settings, material=None):
    material = _find_lens_material(material)
    if not material:
        return None
    material.use_nodes = True
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    output = nodes.get("Material Output")
    if output is None:
        output = nodes.new("ShaderNodeOutputMaterial")
        output.name = "Material Output"

    refraction = nodes.get("Refraction BSDF")
    if refraction is None or getattr(refraction, "bl_idname", "") != "ShaderNodeBsdfRefraction":
        refraction = None
        for candidate in nodes:
            if getattr(candidate, "bl_idname", "") == "ShaderNodeBsdfRefraction" or getattr(candidate, "type", "") == "BSDF_REFRACTION":
                refraction = candidate
                break
    if refraction is None:
        refraction = nodes.new("ShaderNodeBsdfRefraction")
        refraction.name = "Refraction BSDF"
        refraction.label = "Refraction BSDF"

    if "Color" in refraction.inputs:
        desired = (1.0, 1.0, 1.0, 1.0)
        if tuple(refraction.inputs["Color"].default_value) != desired:
            refraction.inputs["Color"].default_value = desired
    if "Roughness" in refraction.inputs:
        desired = max(0.0, min(1.0, float(settings.resin_roughness)))
        if abs(float(refraction.inputs["Roughness"].default_value) - desired) > 1.0e-6:
            refraction.inputs["Roughness"].default_value = desired
    if "IOR" in refraction.inputs:
        desired = max(1.0, float(settings.ior))
        if abs(float(refraction.inputs["IOR"].default_value) - desired) > 1.0e-6:
            refraction.inputs["IOR"].default_value = desired

    # Preserve an existing microtexture/bump normal connection when upgrading
    # an older LT_LensMat from Principled BSDF.
    bump = nodes.get(OBJECT_PREFIX + "MicroBump")
    if bump is not None and "Normal" in refraction.inputs:
        already_linked = any(
            link.from_node == bump and link.to_socket == refraction.inputs["Normal"]
            for link in links
        )
        if not already_linked and "Normal" in bump.outputs:
            links.new(bump.outputs["Normal"], refraction.inputs["Normal"])

    # Change the surface link only when it is actually wrong. Rebuilding this
    # link every sync-timer tick forces Cycles to restart the viewport render.
    surface_links = [
        link for link in links
        if link.to_node == output and link.to_socket == output.inputs.get("Surface")
    ]
    if len(surface_links) != 1 or surface_links[0].from_node != refraction:
        for link in surface_links:
            links.remove(link)
        links.new(refraction.outputs["BSDF"], output.inputs["Surface"])

    # Remove legacy Principled nodes once. Subsequent timer checks are read-only.
    for node in list(nodes):
        if getattr(node, "bl_idname", "") == "ShaderNodeBsdfPrincipled" or getattr(node, "type", "") == "BSDF_PRINCIPLED":
            nodes.remove(node)

    return refraction


def _find_lens_shader_node(material):
    if not material or not material.use_nodes:
        return None
    nodes = material.node_tree.nodes
    node = nodes.get("Refraction BSDF")
    if node is not None and getattr(node, "bl_idname", "") == "ShaderNodeBsdfRefraction":
        return node
    for candidate in nodes:
        if getattr(candidate, "bl_idname", "") == "ShaderNodeBsdfRefraction" or getattr(candidate, "type", "") == "BSDF_REFRACTION":
            return candidate
    return None


def _update_resin_basic(settings, material=None):
    material = _find_lens_material(material)
    if not material:
        return
    bsdf = _ensure_refraction_lens_material(settings, material)
    if not bsdf:
        return
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, float(settings.resin_roughness)))
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = max(1.0, float(settings.ior))


def _ensure_microtexture_nodes(settings, material=None):
    material = _find_lens_material(material)
    if not material:
        return
    bsdf = _ensure_refraction_lens_material(settings, material)
    if not bsdf or "Normal" not in bsdf.inputs:
        return
    nt = material.node_tree
    nodes = nt.nodes
    links = nt.links

    texcoord = nodes.get(OBJECT_PREFIX + "MicroTexCoord")
    noise = nodes.get(OBJECT_PREFIX + "MicroNoise")
    bump = nodes.get(OBJECT_PREFIX + "MicroBump")

    if texcoord is None:
        texcoord = nodes.new("ShaderNodeTexCoord")
        texcoord.name = OBJECT_PREFIX + "MicroTexCoord"
    if noise is None:
        noise = nodes.new("ShaderNodeTexNoise")
        noise.name = OBJECT_PREFIX + "MicroNoise"
    if bump is None:
        bump = nodes.new("ShaderNodeBump")
        bump.name = OBJECT_PREFIX + "MicroBump"

    # Create the links once. Reusing the nodes avoids the heavy node-tree churn
    # that made the add-on sliders much slower than Blender's native controls.
    def linked(from_socket, to_socket):
        return any(link.from_socket == from_socket and link.to_socket == to_socket for link in nt.links)

    if not linked(texcoord.outputs["Generated"], noise.inputs["Vector"]):
        links.new(texcoord.outputs["Generated"], noise.inputs["Vector"])
    if not linked(noise.outputs["Fac"], bump.inputs["Height"]):
        links.new(noise.outputs["Fac"], bump.inputs["Height"])
    if not linked(bump.outputs["Normal"], bsdf.inputs["Normal"]):
        links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    texture_size_m = max(5.0e-6, float(settings.micro_texture_size_um) / 1000000.0)
    texture_height_m = max(0.0, float(settings.micro_texture_height_um) / 1000000.0)
    physical_span_m = max(0.001, float(settings.width_mm) / 1000.0, float(settings.height_mm) / 1000.0)
    noise.inputs["Scale"].default_value = max(1.0, min(100000.0, physical_span_m / texture_size_m))
    if "Detail" in noise.inputs:
        noise.inputs["Detail"].default_value = 2.0
    if "Roughness" in noise.inputs:
        noise.inputs["Roughness"].default_value = 0.55
    # Use a fixed bump strength and express amplitude through Distance in real scene units.
    # This makes the control physically interpretable: 10 um means a 10 micron normal disturbance scale.
    bump.inputs["Strength"].default_value = 1.0 if settings.micro_texture_enabled and texture_height_m > 0.0 else 0.0
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = texture_height_m


def _configure_resin_material(settings, material=None):
    _update_resin_basic(settings, material)
    _ensure_microtexture_nodes(settings, material)


def _update_resin_basic_live(self, context):
    if _state["applying"]:
        return
    _update_resin_basic(self)
    _mark_dirty_scope("material")(self, context)


def _update_ior_live(self, context):
    if _state["applying"]:
        return
    _update_resin_basic(self)
    if self.settings_mode == "SEMI":
        _set_priority_silent(self, "ior")
    _apply_local_optical_rules(self, "ior" if self.settings_mode == "SEMI" else None)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _update_microtexture_live(self, context):
    if _state["applying"]:
        return
    _ensure_microtexture_nodes(self)
    _mark_dirty_scope("material")(self, context)


def _apply_resin_preset(self, context):
    if _state["applying"]:
        return
    preset = self.resin_surface_preset
    if preset == "CUSTOM":
        _configure_resin_material(self)
        _mark_dirty_scope("material")(self, context)
        return
    values = {
        "PERFECT": (0.000, False, 500.0, 0.0),
        "SMOOTH": (0.450, True, 650.0, 2.0),
        "CALIBRATED": (0.700, True, 500.0, 5.0),
        "TYPICAL": (0.750, True, 450.0, 8.0),
        "ROUGH": (0.850, True, 350.0, 15.0),
    }.get(preset, (0.700, True, 500.0, 5.0))
    _state["applying"] = True
    try:
        self.resin_roughness = values[0]
        self.micro_texture_enabled = values[1]
        self.micro_texture_size_um = values[2]
        self.micro_texture_height_um = values[3]
    finally:
        _state["applying"] = False
    _configure_resin_material(self)
    _mark_dirty_scope("material")(self, context)


def _aim_object_at(obj, target_location):
    try:
        direction = Vector(target_location) - obj.location
        if direction.length > 1.0e-9:
            obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    except Exception:
        pass


def _position_area_lights(settings):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if not collection:
        return
    lights = [obj for obj in collection.objects if obj.type == "LIGHT" and obj.name.startswith(OBJECT_PREFIX + "AreaLight")]
    if not lights:
        return
    width_m = max(0.001, float(settings.width_mm) / 1000.0)
    height_m = max(0.001, float(settings.height_mm) / 1000.0)
    peak_m = max(0.0, float(settings.thickness_mm) / 1000.0)
    size = max(width_m, height_m)
    distance = max(0.12, size * 2.25)
    angle = math.radians(max(15.0, min(85.0, float(settings.light_angle_deg))))
    lateral = math.sin(angle) * distance
    front = math.cos(angle) * distance + peak_m * 0.5
    target = (0.0, peak_m * 0.35, 0.0)

    for index, light in enumerate(sorted(lights, key=lambda obj: obj.name)):
        sign = -1.0 if index % 2 == 0 else 1.0
        # The upright print faces -Y. Put lights to the side of the active viewing sweep.
        if settings.orientation == "VERTICAL":
            light.location = (sign * lateral, front, 0.0)
        else:
            light.location = (0.0, front, sign * lateral)
        light.data.energy = max(0.0, float(settings.light_power_w))
        light.data.shape = "DISK"
        light.data.size = max(0.04, size * 0.75)
        _aim_object_at(light, target)


def _update_light_power(self, context):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if not collection:
        return
    for obj in collection.objects:
        if obj.type == "LIGHT" and obj.name.startswith(OBJECT_PREFIX + "AreaLight"):
            try:
                obj.data.energy = max(0.0, float(self.light_power_w))
            except Exception:
                pass


def _update_light_layout(self, context):
    if _state["applying"]:
        return
    _position_area_lights(self)
    _mark_dirty_scope("lighting")(self, context)


def _update_light_power_live(self, context):
    if _state["applying"]:
        return
    _update_light_power(self, context)
    _mark_dirty_scope("lighting")(self, context)


def _update_camera_layout(settings, context=None):
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if not collection:
        return
    cameras = _camera_objects()
    target = bpy.data.objects.get(OBJECT_PREFIX + "ViewTarget")
    if not cameras or target is None:
        return
    width_m = max(0.001, float(settings.width_mm) / 1000.0)
    height_m = max(0.001, float(settings.height_mm) / 1000.0)
    peak_m = max(0.0, float(settings.thickness_mm) / 1000.0)
    backing_m = max(0.0, float(settings.backing_mm) / 1000.0)
    distance_m = max(width_m, height_m) * 1.8 + max(backing_m, peak_m) * 15.0
    count = len(cameras)
    total = max(1.0, float(settings.viewing_angle_deg))
    start = -total / 2.0
    angles = [0.0] if count <= 1 else [start + (total / max(1, count - 1)) * i for i in range(count)]
    for cam, angle_deg in zip(cameras, angles):
        angle = math.radians(angle_deg)
        lateral = math.sin(angle) * distance_m
        depth = math.cos(angle) * distance_m + peak_m * 0.5
        cam.location = (lateral, depth, 0.0) if settings.orientation == "VERTICAL" else (0.0, depth, lateral)
        cam["lenticular_angle_deg"] = float(angle_deg)
    target.location = (0.0, peak_m * 0.45, 0.0)


def _viewing_angle_mode_changed(self, context):
    if _state["applying"]:
        return
    priority = "viewing_angle" if self.settings_mode == "SEMI" else None
    if priority:
        _set_priority_silent(self, priority)
    _apply_local_optical_rules(self, priority)
    _update_camera_layout(self, context)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _custom_viewing_angle_changed(self, context):
    if _state["applying"] or not _custom_viewing_angle_active(self):
        return
    priority = "viewing_angle" if self.settings_mode == "SEMI" else None
    if priority:
        _set_priority_silent(self, priority)
    _apply_local_optical_rules(self, priority)
    _update_camera_layout(self, context)
    _queue_reactive(self, context, "geometry", rebuild_lens=True)


def _update_viewing_angle_live(self, context):
    if _state["applying"]:
        return
    _update_camera_layout(self, context)
    _mark_dirty_scope("camera")(self, context)


def _effective_backing_mm(settings):
    return max(0.01, float(settings.backing_mm)) if getattr(settings, "backing_enabled", True) else 0.0


def _sync_backing_object(settings):
    """Change only the support block, without rebuilding lenses or image assets.

    Use data API creation instead of selection-dependent operators, so toggling
    the support does not steal the selected object or move any viewport/camera.
    """
    backing = bpy.data.objects.get(OBJECT_PREFIX + "Backing")
    thickness = _effective_backing_mm(settings) / 1000.0
    if thickness <= 0:
        if backing is not None:
            mesh = backing.data
            bpy.data.objects.remove(backing, do_unlink=True)
            if mesh is not None and getattr(mesh, "users", 1) == 0:
                bpy.data.meshes.remove(mesh)
        return None
    print_root = bpy.data.objects.get(OBJECT_PREFIX + "PrintRoot")
    if print_root is None:
        return None
    if backing is None:
        mesh = bpy.data.meshes.new(OBJECT_PREFIX + "BackingMesh")
        vertices = [(-.5,-.5,-.5),(.5,-.5,-.5),(.5,.5,-.5),(-.5,.5,-.5),
                    (-.5,-.5,.5),(.5,-.5,.5),(.5,.5,.5),(-.5,.5,.5)]
        faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        backing = bpy.data.objects.new(OBJECT_PREFIX + "Backing", mesh)
        collection = next(iter(print_root.users_collection), None)
        if collection is None:
            collection = bpy.context.scene.collection
        collection.objects.link(backing)
        material = _material_by_name(OBJECT_PREFIX + "SubstrateMat")
        _ensure_diffuse_material(material, (0.9, 0.9, 0.9, 1.0), 0.0)
        backing.data.materials.append(material)
        backing.parent = print_root
    backing.dimensions = (settings.width_mm / 1000.0, settings.height_mm / 1000.0, thickness)
    backing.location = (0.0, 0.0, -thickness / 2.0)
    return backing


def _update_backing_live(self, context):
    if _state["applying"]:
        return
    _sync_backing_object(self)
    _mark_dirty_scope("backing")(self, context)


class LenticularSourceFrame(PropertyGroup):
    path: StringProperty(name="Path", subtype="FILE_PATH")
    display_name: StringProperty(name="Image")


# This callback must be defined before LenticularSyncSettings is created because
# Blender evaluates EnumProperty(update=...) while constructing the class.
_REFERENCE_SHARED_FIELDS = (
    'reference_heightmap_width_mm', 'reference_heightmap_height_mm', 'reference_heightmap_thickness_mm',
    'reference_heightmap_orientation', 'reference_heightmap_display_style', 'reference_heightmap_detection',
    'reference_heightmap_pitch_px', 'reference_heightmap_phase_pitch', 'reference_heightmap_show',
)
_heightmap_cache = {}


def _reference_info(settings):
    try:
        return json.loads(settings.reference_heightmap_info_json or '{}')
    except (ValueError, TypeError):
        return {}


def _reference_data(settings):
    path = _resolve_preview_path(settings, settings.reference_heightmap_path)
    if path is None or not path.is_file():
        raise RuntimeError('Import a reference heightmap first')
    stat = path.stat()
    key = (str(path.resolve()),stat.st_size,stat.st_mtime_ns)
    if key in _heightmap_cache:
        return _heightmap_cache[key]
    data = None
    if path.suffix.lower() == '.png':
        try:
            data = heightmap_tools.read_png(path)
        except NotImplementedError:
            pass
    if data is None:
        # Blender pixel buffers use bottom-up rows. Non-Color disables sRGB
        # decoding so normalized values remain linear physical heights.
        image = bpy.data.images.load(str(path),check_existing=True)
        image.colorspace_settings.name = 'Non-Color'
        image.reload()
        w,h = int(image.size[0]),int(image.size[1])
        if w < 2 or h < 2 or w > 100000 or h > 100000 or w*h > 100000000:
            raise RuntimeError('Heightmap must have at least 2 pixels per side and at most 100 million pixels')
        pixels = np.empty(w*h*4,dtype=np.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(h,w,4)[::-1]
        first = pixels[:,:,0]
        grayscale = bool(np.max(np.abs(pixels[:,:,:3]-first[:,:,None])) <= 1/255)
        metadata = heightmap_tools.tiff_size_metadata(path) if path.suffix.lower() in ('.tif','.tiff') else heightmap_tools.png_size_metadata(path) if path.suffix.lower()=='.png' else {}
        data = (first[h//2,:].astype(np.float64), first[:,w//2].astype(np.float64), w,h,metadata,grayscale,16 if image.depth>=16 else 8,float(first.min()),float(first.max()))
    _heightmap_cache.clear()
    _heightmap_cache[key] = data
    return data


def _analyze_reference_heightmap(settings):
    data = _reference_data(settings)
    path = _resolve_preview_path(settings,settings.reference_heightmap_path)
    key = (str(path),path.stat().st_size,path.stat().st_mtime_ns)
    if _state.get('reference_analysis_key') == key:
        info = _state['reference_analysis_result']
    else:
        info = heightmap_tools.analyze_axes(*data)
        _state['reference_analysis_key'],_state['reference_analysis_result'] = key,info
    previous = _state['applying']
    _state['applying'] = True
    try:
        settings.reference_heightmap_info_json = json.dumps(info)
        if settings.reference_heightmap_detection == 'Automatic' and info.get('ok'):
            settings.reference_heightmap_orientation = info['orientation'].upper()
            settings.reference_heightmap_pitch_px = info['pitch_px']
            settings.reference_heightmap_phase_pitch = info['phase_pitch']
    finally:
        _state['applying'] = previous
    return info


def _apply_imported_heightmap_settings(settings):
    if _state.get('applying'):
        return
    info = _reference_info(settings)
    previous = _state['applying']
    _state['applying'] = True
    try:
        settings.width_mm = settings.reference_heightmap_width_mm
        settings.height_mm = settings.reference_heightmap_height_mm
        settings.orientation = settings.reference_heightmap_orientation
        pitch = float(settings.reference_heightmap_pitch_px)
        axis = 'width' if settings.orientation=='VERTICAL' else 'height'
        if pitch>0 and info.get(axis+'_px',0)>0:
            settings.lpi = float(info[axis+'_px'])*25.4/(float(getattr(settings,'reference_heightmap_'+axis+'_mm'))*pitch)
        if len(settings.source_frames)>0:
            settings.views = len(settings.source_frames)
        settings.lpi_helper_mode = 'MANUAL'
        settings.build_detail_mode = 'CUSTOM'
        settings.pixels_per_lenticule = max(2,round(pitch))
        scale = float(settings.reference_heightmap_thickness_mm)
        settings.thickness_mm = float(info.get('maximum',1))*scale
        settings.base_mm = float(info.get('minimum',0))*scale
        settings.rise_mm = max(0,settings.thickness_mm-settings.base_mm)
        settings.print_profile = 'MANUAL'
        settings.base_mode = 'MANUAL'
        _set_manual_thickness_display_from_mm(settings,settings.thickness_mm)
        settings.manual_base_mm = settings.base_mm
    finally:
        _state['applying'] = previous


def _validate_heightmap_build(settings, info, require_sources=True):
    if info.get('grayscale') is False:
        raise RuntimeError('Use a grayscale lens heightmap')
    if settings.reference_heightmap_detection == 'Automatic' and not info.get('ok'):
        raise RuntimeError(info.get('message','Detection needs manual review'))
    pitch=float(settings.reference_heightmap_pitch_px)
    if pitch<2:
        raise RuntimeError('Enter at least 2 pixels per lens')
    views=len(settings.source_frames)
    if require_sources and views<2:
        raise RuntimeError('Add at least two source images')
    if views>pitch:
        raise RuntimeError('The map needs at least one pixel per source view within each lens')


def _sync_reference_preview(context):
    settings=context.scene.lenticular_sync
    path=_resolve_preview_path(settings,settings.reference_heightmap_path)
    if not path or not path.is_file() or not settings.reference_heightmap_show:
        collection=bpy.data.collections.get(REFERENCE_COLLECTION_NAME)
        if collection:
            collection.hide_viewport=True
            collection.hide_render=True
        return
    key=(str(path),path.stat().st_size,path.stat().st_mtime_ns,settings.reference_heightmap_width_mm,settings.reference_heightmap_height_mm,settings.reference_heightmap_thickness_mm,settings.reference_heightmap_orientation)
    collection=bpy.data.collections.get(REFERENCE_COLLECTION_NAME)
    if _state.get('reference_preview_key') != key or collection is None:
        data=_reference_data(settings)
        if not data[5]:
            raise RuntimeError('Use a grayscale lens heightmap')
        vertical=settings.reference_heightmap_orientation=='VERTICAL'
        values=data[0] if vertical else data[1][::-1]
        collection=_ensure_reference_collection(context.scene)
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj,do_unlink=True)
        width=settings.reference_heightmap_width_mm/1000
        height=settings.reference_heightmap_height_mm/1000
        obj=_build_lens_mesh(collection,values,width,height,settings.reference_heightmap_thickness_mm/1000,0,vertical)
        obj.name=OBJECT_PREFIX+'ReferenceHeightmapLens'
        obj.data.materials.append(_reference_material(settings,create=True))
        # Match the main print's authored presentation while keeping the
        # existing comparison offset. Viewport areas and framing stay intact.
        main=bpy.data.objects.get(OBJECT_PREFIX+'PrintRoot')
        if main:
            obj.rotation_euler=main.rotation_euler
        obj.location=(width*.65,0,0) if vertical else (0,height*.65,0)
        _state['reference_preview_key']=key
        _state['reference_style_key']=None
    collection.hide_viewport=False
    collection.hide_render=False
    style_key=(key,settings.reference_heightmap_display_style,settings.ior)
    if _state.get('reference_style_key') != style_key:
        _apply_reference_display_style(settings)
        _state['reference_style_key']=style_key


def _update_reference_display_style(self, context):
    if _state.get("applying", False):
        return
    _apply_reference_display_style(self)
    _queue_reactive(self, context, "reference")


def _reference_heightmap_changed(self, context):
    if _state.get("applying", False):
        return
    _state["reference_preview_key"] = None
    try:
        if self.reference_heightmap_path:
            _analyze_reference_heightmap(self)
        if self.workflow == "HEIGHTMAP":
            _apply_imported_heightmap_settings(self)
    except Exception as exc:
        self.reference_heightmap_info_json = json.dumps({"ok": False, "message": str(exc)})
        _set_status(self, str(exc))
    active = self.workflow == "HEIGHTMAP"
    _queue_reactive(self, context, "images" if active else "reference", rebuild_interlace=active, rebuild_lens=active, refresh_texture=active)


def _reference_visibility_changed(self, context):
    if not _state.get("applying", False):
        _state["reference_preview_key"] = None
        _queue_reactive(self, context, "reference")

class LenticularSyncSettings(PropertyGroup):
    project_file: StringProperty(
        name="Project",
        description="project.json created by Lenticulizer",
        subtype="FILE_PATH",
    )
    status: StringProperty(name="Status", default="Not connected")
    workflow: EnumProperty(
        name="Image Source",
        items=[
            ("SOURCE_FRAMES", "Build from Source Images", "Use 2 to 8 ordered source images"),
            ("EXISTING_INTERLACED", "Use Existing Interlaced Image", "Use an already interlaced image"),
            ("HEIGHTMAP", "Build from Heightmap", "Preserve imported lens geometry and generate matching interlacing"),
        ],
        default="SOURCE_FRAMES",
        update=_mark_dirty_scope("images"),
    )
    test_output_name: StringProperty(name="Test name", description="Optional label for this test print; does not change project geometry", default="", maxlen=64)
    source_frames: CollectionProperty(type=LenticularSourceFrame)
    source_frame_index: IntProperty(name="Selected Source Image", default=0, min=0, update=_source_frame_selection_changed)
    source_frame_selector: EnumProperty(
        name="Source Image",
        description="Click the thumbnail to choose the source image shown in the dedicated top image viewer",
        items=_source_frame_selector_items,
        update=_source_frame_selector_changed,
    )
    active_camera_name: StringProperty(name="Active Camera", default="")
    active_viewport_camera_name: StringProperty(name="Viewport View", default="")
    target_viewport_index: IntProperty(
        name="Target Viewport",
        description="Explicit 3D viewport number controlled by both Camera View and Viewport Match. This never follows the mouse automatically.",
        default=1,
        min=1,
        max=16,
    )
    # Keep all saved enum identifiers and numbers for .blend compatibility.
    # _ui_workflow_tab maps Project/Images and Optics/Calibration onto the three
    # visible tabs without a migration write, generation request or sync event.
    ui_workspace: EnumProperty(
        name="Workspace",
        items=[
            ("PROJECT", "Project", "Project connection, print size, output mode and printer", 0),
            ("IMAGES", "Images", "Source images, view order, interlacing and reference heightmap", 3),
            ("OPTICS", "Optics", "Lens or prism settings, backing, materials and lighting", 4),
            ("OUTPUT", "Output", "Generate, export, camera views and rendering", 2),
            ("CALIBRATION", "Calibration", "Generate small optical calibration coupon sets", 1),
        ],
        default="PROJECT",
    )
    output_mode: EnumProperty(
        name="Output Mode",
        items=[
            ("LENTICULAR", "Lenticular Lens", "Use a refractive lenticular lens layer"),
            ("RELIEF", "Lens-Free Relief", "Use an integrated faceted relief with no separate lens layer"),
        ],
        default="LENTICULAR",
        update=_output_mode_changed,
    )
    relief_prism_height_mm: FloatProperty(
        name="Prism Height",
        description="Maximum naked-eye relief height above the substrate. Use the same value as UV texture thickness.",
        default=0.8,
        min=MIN_NONZERO_PEAK_MM,
        max=MAX_PEAK_MM,
        soft_min=0.5,
        soft_max=2.5,
        precision=3,
        update=_relief_height_changed,
    )
    relief_base_mode: EnumProperty(
        name="Relief Base",
        items=[
            ("NONE", "No base", "Lens-free relief starts directly from the substrate"),
            ("MINIMUM", "Legacy printer minimum", "Legacy project compatibility only"),
            ("MANUAL", "Legacy manual", "Legacy project compatibility only"),
        ],
        default="NONE",
        update=_relief_base_changed,
    )
    relief_manual_base_mm: FloatProperty(
        name="Manual Relief Base", default=0.0, min=0.0, max=5.0, soft_max=5.0, precision=3, update=_relief_base_changed
    )
    calibration_mode: EnumProperty(
        name="Calibration Test",
        items=[
            ("THICKNESS", "Thickness Test", "Seven focused Thickness variants around the current value"),
            ("VIEWING", "Viewing Test", "Five target viewing-angle variants while keeping LPI fixed"),
            ("ALIGNMENT", "Alignment Test", "Five phase-registration variants around the current phase"),
            ("LENS_TYPE", "Lens Type Test", "Compare Aspheric, Circular, Prismatic, Cosine, and Triangular profiles"),
        ],
        default="THICKNESS",
    )
    calibration_coupon_size_mm: EnumProperty(
        name="Coupon Size",
        items=[("15", "15 mm", "15 x 15 mm centered coupon"), ("20", "20 mm", "20 x 20 mm centered coupon"), ("25", "25 mm", "25 x 25 mm centered coupon")],
        default="20",
    )
    calibration_output_dir: StringProperty(
        name="Output Folder",
        description="Folder where calibration sets are created. Leave blank to use the current project folder.",
        subtype="DIR_PATH",
        default="",
    )
    calibration_last_folder: StringProperty(name="Last Calibration Folder", default="")

    reference_heightmap_path: StringProperty(name="Reference Heightmap", subtype="FILE_PATH", default="", update=_reference_heightmap_changed)
    reference_heightmap_width_mm: FloatProperty(name="Ref Width", default=60.0, min=0.01, soft_max=1000.0, precision=3, update=_reference_heightmap_changed)
    reference_heightmap_height_mm: FloatProperty(name="Ref Height", default=60.0, min=0.01, soft_max=1000.0, precision=3, update=_reference_heightmap_changed)
    reference_heightmap_thickness_mm: FloatProperty(name="White-Level Height (mm)", default=1.86, min=0.01, max=5.0, soft_max=5.0, precision=3, update=_reference_heightmap_changed)
    reference_heightmap_orientation: EnumProperty(name="Ref Direction", items=[("VERTICAL", "Vertical", "Vertical lenticules"), ("HORIZONTAL", "Horizontal", "Horizontal lenticules")], default="VERTICAL", update=_reference_heightmap_changed)
    reference_heightmap_display_style: EnumProperty(
        name="Display Style",
        items=[
            ("OPAQUE", "Opaque Inspection", "Solid colored surface for reading the lens shape clearly"),
            ("TINTED", "Tinted Translucent", "Colored optical preview with limited transmission"),
            ("CLEAR", "Clear Resin", "Transparent resin-style optical preview"),
        ],
        default="OPAQUE",
        update=_update_reference_display_style,
    )
    reference_heightmap_detection: EnumProperty(name="Detection", items=[("Automatic", "Automatic", "Detect repeating lens pitch and registration"), ("Manual", "Manual", "Enter direction, pitch and registration")], default="Automatic", update=_reference_heightmap_changed)
    reference_heightmap_pitch_px: FloatProperty(name="Pixels per Lens", default=0.0, min=0.0, soft_max=1000.0, precision=6, update=_reference_heightmap_changed)
    reference_heightmap_phase_pitch: FloatProperty(name="Registration (pitch)", default=0.0, min=-0.5, max=0.5, precision=6, update=_reference_heightmap_changed)
    reference_heightmap_show: BoolProperty(name="Show Reference 3D", default=False, update=_reference_visibility_changed)
    reference_heightmap_info_json: StringProperty(default="{}", options={'HIDDEN'})
    reference_cross_section_span: EnumProperty(
        name="Cross-Section Span",
        items=[
            ("1", "1 Lenticule", "Show approximately 1 lenticule"),
            ("3", "3 Lenticules", "Show approximately 3 lenticules"),
            ("5", "5 Lenticules", "Show approximately 5 lenticules"),
            ("10", "10 Lenticules", "Show approximately 10 lenticules"),
            ("12", "12 Lenticules", "Show approximately 12 lenticules"),
            ("20", "20 Lenticules", "Show approximately 20 lenticules"),
            ("FULL", "Full Width", "Show the full center scanline"),
        ],
        default="12",
    )
    build_cross_section_expanded: BoolProperty(
        name="Show Build Cross Section",
        description="Expand or collapse the generated lens/heightmap cross-section preview",
        default=True,
    )
    reference_cross_section_expanded: BoolProperty(
        name="Show Reference Cross Section",
        description="Expand or collapse the imported heightmap cross-section preview",
        default=True,
    )
    source_image_list_expanded: BoolProperty(
        name="Show Source Images",
        description="Expand or collapse the source image list",
        default=True,
    )
    selected_source_preview_expanded: BoolProperty(
        name="Show Selected Source Preview",
        description="Expand or collapse the selected source image preview",
        default=True,
    )
    interlaced_preview_expanded: BoolProperty(
        name="Show Interlaced Preview",
        description="Expand or collapse the current interlaced image preview",
        default=True,
    )
    image_outputs_expanded: BoolProperty(
        name="Show Image Outputs",
        description="Expand or collapse image export controls",
        default=True,
    )

    settings_mode: EnumProperty(
        name="Mode",
        items=[
            ("AUTOMATIC", "Automatic", "Calculate all optical settings automatically from the selected optical basis"),
            ("SEMI", "Semi-Automatic", "Change one optical choice and recalculate the dependent geometry"),
            ("MANUAL", "Manual", "All optical settings are manual"),
        ],
        default="AUTOMATIC",
        update=_mode_changed,
    )
    priority: EnumProperty(
        name="Priority",
        items=[
            ("lpi", "LPI", "Keep this LPI and recalculate dependent settings"),
            ("relief_prism_height_mm", "Prism Height", "Keep this relief print height and recalculate dependent relief geometry"),
            ("ior", "IOR", "Keep this refractive index and recalculate dependent optical geometry"),
            ("viewing_angle", "Viewing Angle", "Keep this custom total viewing angle and recalculate dependent optical geometry"),
            ("thickness_mm", "Thickness", "Keep this peak thickness"),
            ("base_mm", "Base Height", "Keep this valley height"),
            ("lens_profile", "Lens Type", "Keep this lens type"),
            ("backing_mm", "Backing", "Change only the backing thickness"),
            ("phase_pitch", "Phase", "Change registration phase"),
        ],
        default="thickness_mm",
        update=_priority_selection_changed,
    )
    width_mm: FloatProperty(name="Width", default=60.0, min=0.01, soft_max=1000.0, precision=3, update=_mark_interlace_geometry)
    height_mm: FloatProperty(name="Height", default=60.0, min=0.01, soft_max=1000.0, precision=3, update=_mark_interlace_geometry)
    lpi: FloatProperty(name="LPI", default=35.0, min=1.0, soft_max=200.0, precision=3, update=_mark_lpi_interlace)
    views: IntProperty(name="Views", default=3, min=1, max=8, update=_mark_views_change)
    orientation: EnumProperty(name="Lens Direction", items=[("VERTICAL", "Vertical", "Vertical lenticules"), ("HORIZONTAL", "Horizontal", "Horizontal lenticules")], default="VERTICAL", update=_mark_interlace_geometry)
    lens_profile: EnumProperty(name="Lens Type", items=_profile_items(), default="AUTO", update=_lens_profile_changed)
    print_profile: EnumProperty(name="Print Profile", items=_print_profile_items(), default="RECOMMENDED", update=_print_profile_changed)
    manual_thickness_value: FloatProperty(name="Manual Thickness", default=0.797, min=0.0, max=5000.0, soft_max=5.0, precision=3, update=_manual_thickness_changed)
    manual_thickness_unit: EnumProperty(name="Thickness Unit", items=[("MM", "mm", "Millimeters"), ("UM", "um", "Micrometers")], default="MM", update=_manual_thickness_unit_changed)
    manual_thickness_unit_last: StringProperty(name="Manual Thickness Previous Unit", default="MM", options={'HIDDEN'})
    base_mode: EnumProperty(name="Base", items=_base_mode_items(), default="RECOMMENDED", update=_base_mode_changed)
    manual_base_mm: FloatProperty(name="Manual Base Height", default=0.506, min=0.0, max=5.0, soft_max=5.0, precision=3, update=_manual_base_changed)
    # Resolved/calculated geometry. These remain serialized for backward compatibility and scene construction.
    thickness_mm: FloatProperty(name="Thickness", default=0.797, min=0.0, max=5.0, soft_max=5.0, precision=3, update=_mark_priority("thickness_mm"))
    base_mm: FloatProperty(name="Base Height", default=0.506, min=0.0, max=5.0, soft_max=5.0, precision=3, update=_mark_priority("base_mm"))
    rise_mm: FloatProperty(name="Lens Rise", default=0.291, min=0.0, max=5.0, soft_max=5.0, precision=3)
    viewing_angle_mode: EnumProperty(
        name="Viewing Angle",
        items=[
            ("NARROW", "Narrow", "Use a narrower recommended viewing angle and recalculate Thickness, Base and Rise"),
            ("STANDARD", "Standard", "Use the balanced recommended viewing angle and recalculate Thickness, Base and Rise"),
            ("WIDE", "Wide", "Use a wider recommended viewing angle and recalculate Thickness, Base and Rise"),
            ("EXTRA_WIDE", "Extra Wide", "Use the widest recommended viewing angle target and recalculate Thickness, Base and Rise"),
            ("CUSTOM", "Custom", "Use a custom total viewing angle as an optical target and recalculate Thickness, Base and Rise"),
        ],
        default="STANDARD",
        update=_viewing_angle_mode_changed,
    )
    custom_viewing_angle_deg: FloatProperty(name="Custom Viewing Angle", default=44.0, min=1.0, max=178.9, soft_min=10.0, soft_max=90.0, precision=2, update=_custom_viewing_angle_changed)
    viewing_angle_deg: FloatProperty(name="Resolved Viewing Angle", default=44.0, min=1.0, max=179.0, precision=2, update=_update_viewing_angle_live)
    ior: FloatProperty(name="IOR", default=1.55, min=1.0001, max=3.0, precision=4, update=_update_ior_live)
    resin_surface_preset: EnumProperty(name="Resin Surface", items=_resin_preset_items(), default="CALIBRATED", update=_apply_resin_preset)
    resin_roughness: FloatProperty(name="Effective Optical Roughness", default=0.700, min=0.0, max=1.0, soft_max=1.0, precision=3, update=_update_resin_basic_live)
    micro_texture_enabled: BoolProperty(name="Micro Surface Texture", default=True, update=_update_microtexture_live)
    micro_texture_size_um: FloatProperty(name="Surface Texture Size", description="Approximate spacing/size of cured resin surface features in microns", default=500.0, min=10.0, max=5000.0, soft_min=100.0, soft_max=1500.0, precision=1, update=_update_microtexture_live)
    micro_texture_height_um: FloatProperty(name="Surface Texture Height", description="Effective surface normal disturbance height in microns", default=5.0, min=0.0, max=100.0, soft_max=30.0, precision=2, update=_update_microtexture_live)
    backing_enabled: BoolProperty(name="Enable backing / support base", default=True,
        description="Include the support block beneath the image or relief. Does not change the lens base/valley or heightmap. Thickness is remembered when disabled",
        update=_update_backing_live)
    backing_mm: FloatProperty(name="Backing thickness (mm)", default=5.0, min=0.01, soft_max=50.0, precision=3, update=_update_backing_live)
    phase_pitch: FloatProperty(name="Phase", default=0.0, min=-0.5, max=0.5, precision=4, update=_mark_priority("phase_pitch"))
    interlaced_image: StringProperty(name="Interlaced Image", default="interlaced_image.png")
    heightmap_image: StringProperty(name="Heightmap", default="heightmap16.png")
    auto_sync: BoolProperty(name="Auto Sync", default=True)
    auto_rebuild: BoolProperty(name="Auto Rebuild Scene", default=True)
    light_power_w: FloatProperty(name="Area Light Power", description="Power of each simulation area light", default=0.5, min=0.0, max=1000.0, soft_max=10.0, precision=2, update=_update_light_power_live)
    light_angle_deg: FloatProperty(name="Light Angle", description="Angle of the area lights away from straight overhead. Higher values move the lights farther to the sides and reduce direct glare", default=65.0, min=15.0, max=85.0, soft_min=35.0, soft_max=80.0, precision=1, update=_update_light_layout)
    render_samples: IntProperty(name="Render Samples", default=128, min=8, max=4096)
    render_width: IntProperty(name="Render Width", default=1600, min=128, max=8192)
    render_height: IntProperty(name="Render Height", default=1200, min=128, max=8192)
    printer_dpi: IntProperty(name="Printer DPI", default=1440, min=72, max=9600, soft_min=300, soft_max=2400, update=_mark_interlace_setting)
    lpi_helper_mode: EnumProperty(name="LPI Helper", items=[("RECOMMENDED", "Recommended", "Use an exact mathematically aligned LPI recommendation"), ("MANUAL", "Manual", "Enter LPI manually")], default="RECOMMENDED", update=_lpi_helper_mode_changed)
    lpi_helper_preset: EnumProperty(
        name="LPI Helper Preset",
        items=[
            ("EASIER", "Easier", "Lower LPI with more pixels per lenticule"),
            ("BALANCED", "Balanced", "Balanced exact LPI based on printer DPI and view count"),
            ("FINER", "Finer", "Higher LPI with fewer pixels per lenticule"),
        ],
        default="BALANCED",
        update=_lpi_helper_preset_changed,
    )
    build_detail_mode: EnumProperty(name="Build Detail", items=[("QUICK", "Quick Draft", "Smaller build raster"), ("BALANCED", "Balanced", "Balanced quality"), ("FINE", "Fine Detail", "Higher detail raster"), ("RECOMMENDED", "Recommended", "Based on printer DPI and LPI"), ("CUSTOM", "Custom", "Use the exact pixels-per-lenticule value")], default="RECOMMENDED", update=_mark_interlace_setting)
    pixels_per_lenticule: IntProperty(name="Pixels per Lenticule", default=48, min=4, max=256, soft_min=24, soft_max=144, update=_mark_interlace_setting)
    build_preview_zoom: FloatProperty(
        name="Image Preview Zoom",
        description="Display scale for image thumbnails in Build > Images & Output",
        default=1.0, min=0.5, max=2.0, soft_min=0.5, soft_max=2.0, precision=2,
    )


def _apply_project_to_settings(settings, project):
    data = project.get("settings", {})
    assets = project.get("assets", {})
    _state["applying"] = True
    try:
        mode = str(data.get("mode", "Automatic")).lower()
        settings.settings_mode = "MANUAL" if mode.startswith("manual") else ("SEMI" if mode.startswith("semi") else "AUTOMATIC")
        output_mode = str(data.get("output_mode", "Lenticular Lens")).lower()
        settings.output_mode = "RELIEF" if "relief" in output_mode else "LENTICULAR"
        relief_base = str(data.get("relief_base_mode", "No base")).lower()
        settings.relief_base_mode = "NONE" if "no base" in relief_base else ("MANUAL" if "manual" in relief_base else "MINIMUM")
        settings.relief_manual_base_mm = max(0.0, min(MAX_PEAK_MM, _safe_float(data.get("relief_manual_base_mm"), settings.relief_manual_base_mm)))
        settings.relief_prism_height_mm = max(MIN_NONZERO_PEAK_MM, min(MAX_PEAK_MM, _safe_float(data.get("relief_prism_height_mm"), settings.relief_prism_height_mm)))
        settings.width_mm = _safe_float(data.get("width_mm"), settings.width_mm)
        settings.height_mm = _safe_float(data.get("height_mm"), settings.height_mm)
        settings.lpi = _safe_float(data.get("lpi"), settings.lpi)
        incoming_helper = str(data.get("lpi_helper_mode", "Manual")).strip().lower()
        settings.lpi_helper_mode = "RECOMMENDED" if incoming_helper.startswith("recommend") else "MANUAL"
        incoming_preset = str(data.get("lpi_helper_preset", "Balanced")).strip().upper()
        settings.lpi_helper_preset = "EASIER" if incoming_preset.startswith("EAS") else ("FINER" if incoming_preset.startswith("FIN") else "BALANCED")
        settings.views = max(1, min(8, _safe_int(data.get("views"), settings.views)))
        orientation = str(data.get("orientation", "Vertical")).lower()
        settings.orientation = "HORIZONTAL" if orientation.startswith("h") else "VERTICAL"
        settings.lens_profile = _profile_to_enum(str(data.get("lens_profile", "Reference Calibrated")))
        settings.thickness_mm = max(0.0, min(MAX_PEAK_MM, _safe_float(data.get("thickness_mm"), settings.thickness_mm)))
        settings.base_mm = max(0.0, min(settings.thickness_mm, _safe_float(data.get("base_mm"), settings.base_mm)))
        settings.rise_mm = max(0.0, settings.thickness_mm - settings.base_mm)

        incoming_print = str(data.get("print_profile", "")).strip().lower()
        if "mathemat" in incoming_print or "theoret" in incoming_print:
            settings.print_profile = "THEORETICAL"
        elif "lower" in incoming_print:
            settings.print_profile = "LOWER"
        elif "higher" in incoming_print:
            settings.print_profile = "HIGHER"
        elif "manual" in incoming_print:
            settings.print_profile = "MANUAL"
        elif incoming_print:
            settings.print_profile = "RECOMMENDED"
        else:
            settings.print_profile = _infer_print_profile(settings.lpi, settings.thickness_mm, settings)

        incoming_base = str(data.get("base_mode", "")).strip().lower()
        if "mathemat" in incoming_base or "theoret" in incoming_base:
            settings.base_mode = "THEORETICAL"
        elif "no base" in incoming_base or incoming_base in {"none", "no_base"}:
            settings.base_mode = "NONE"
        elif "minimum" in incoming_base:
            settings.base_mode = "MINIMUM"
        elif "raised" in incoming_base:
            settings.base_mode = "RAISED"
        elif "manual" in incoming_base:
            settings.base_mode = "MANUAL"
        elif incoming_base:
            settings.base_mode = "RECOMMENDED"
        else:
            settings.base_mode = _infer_base_mode(settings.lpi, settings.thickness_mm, settings.base_mm, settings)

        unit_text = str(data.get("manual_thickness_unit", "mm")).strip().lower()
        settings.manual_thickness_unit = "UM" if unit_text in {"um", "µm", "micron", "microns", "micrometer", "micrometers"} else "MM"
        settings.manual_thickness_unit_last = settings.manual_thickness_unit
        manual_peak_mm = max(0.0, min(MAX_PEAK_MM, _safe_float(data.get("manual_thickness_mm"), settings.thickness_mm)))
        _set_manual_thickness_display_from_mm(settings, manual_peak_mm)
        settings.manual_base_mm = max(0.0, min(MAX_PEAK_MM, _safe_float(data.get("manual_base_mm"), settings.base_mm)))
        incoming_angle_mode = str(data.get("viewing_angle_mode", "Standard")).strip().lower()
        if incoming_angle_mode.startswith("custom"):
            settings.viewing_angle_mode = "CUSTOM"
        elif incoming_angle_mode.startswith("narrow"):
            settings.viewing_angle_mode = "NARROW"
        elif incoming_angle_mode.startswith("extra"):
            settings.viewing_angle_mode = "EXTRA_WIDE"
        elif incoming_angle_mode.startswith("wide"):
            settings.viewing_angle_mode = "WIDE"
        else:
            settings.viewing_angle_mode = "STANDARD"
        custom_angle = _safe_float(data.get("custom_viewing_angle_deg"), settings.custom_viewing_angle_deg)
        settings.custom_viewing_angle_deg = max(1.0, min(178.9, custom_angle))
        settings.viewing_angle_deg = _safe_float(data.get("viewing_angle_deg"), settings.viewing_angle_deg)
        settings.ior = _safe_float(data.get("ior"), settings.ior)
        preset = str(data.get("resin_surface_preset", settings.resin_surface_preset)).upper().replace(" ", "_")
        preset_map = {"PERFECT_OPTICAL": "PERFECT", "SMOOTH_UV_CLEAR": "SMOOTH", "CALIBRATED_UV_CLEAR": "CALIBRATED", "TYPICAL_UV_CLEAR": "TYPICAL", "ROUGH_UV_CLEAR": "ROUGH", "CUSTOM": "CUSTOM", "PERFECT": "PERFECT", "SMOOTH": "SMOOTH", "CALIBRATED": "CALIBRATED", "TYPICAL": "TYPICAL", "ROUGH": "ROUGH"}
        settings.resin_surface_preset = preset_map.get(preset, settings.resin_surface_preset)
        settings.resin_roughness = max(0.0, min(1.0, _safe_float(data.get("resin_roughness"), settings.resin_roughness)))
        settings.micro_texture_enabled = bool(data.get("micro_texture_enabled", settings.micro_texture_enabled))
        settings.micro_texture_size_um = max(10.0, _safe_float(data.get("micro_texture_size_um"), settings.micro_texture_size_um))
        if "micro_texture_height_um" in data:
            settings.micro_texture_height_um = max(0.0, min(100.0, _safe_float(data.get("micro_texture_height_um"), settings.micro_texture_height_um)))
        elif "micro_texture_strength" in data:
            # Backward compatibility with v1.4 and earlier. Old 0-1 strength maps to 0-20 um.
            settings.micro_texture_height_um = max(0.0, min(100.0, _safe_float(data.get("micro_texture_strength"), 0.0) * 20.0))
        incoming_light_power = _safe_float(data.get("light_power_w"), settings.light_power_w)
        if "light_angle_deg" not in data and incoming_light_power >= 1.5:
            incoming_light_power = 0.5
        settings.light_power_w = max(0.0, incoming_light_power)
        settings.light_angle_deg = max(15.0, min(85.0, _safe_float(data.get("light_angle_deg"), settings.light_angle_deg)))
        effective_backing = _safe_float(data.get("backing_mm"), _effective_backing_mm(settings))
        remembered_backing = effective_backing if effective_backing > 0 else _safe_float(data.get("backing_saved_mm"), settings.backing_mm)
        settings.backing_enabled = effective_backing > 0 and data.get("backing_enabled", True) is not False
        settings.backing_mm = max(0.01, remembered_backing)
        settings.phase_pitch = max(-0.5, min(0.5, _safe_float(data.get("phase_pitch"), settings.phase_pitch)))
        settings.interlaced_image = str(assets.get("interlaced_image", settings.interlaced_image))
        settings.heightmap_image = str(assets.get("heightmap", settings.heightmap_image))
        settings.printer_dpi = max(72, _safe_int(data.get("printer_dpi"), settings.printer_dpi))
        incoming_build_mode = str(data.get("build_detail_mode", settings.build_detail_mode)).upper().replace(" ", "_")
        build_mode_map = {"AUTO_FROM_PRINTER_DPI": "RECOMMENDED", "AUTO": "RECOMMENDED", "QUICK_DRAFT": "QUICK", "QUICK": "QUICK", "BALANCED": "BALANCED", "FINE_DETAIL": "FINE", "FINE": "FINE", "RECOMMENDED": "RECOMMENDED", "CUSTOM": "CUSTOM"}
        settings.build_detail_mode = build_mode_map.get(incoming_build_mode, settings.build_detail_mode)
        settings.pixels_per_lenticule = _snap_pixels_per_lenticule(_safe_int(data.get("pixels_per_lenticule"), settings.pixels_per_lenticule), max(1, settings.views))
        workflow = str(data.get("workflow", "")).lower()
        settings.workflow = "HEIGHTMAP" if "heightmap" in workflow else "EXISTING_INTERLACED" if "existing" in workflow or "interlaced" in workflow else "SOURCE_FRAMES"
        settings.reference_heightmap_path = str(assets.get("reference_heightmap", ""))
        for key in _REFERENCE_SHARED_FIELDS:
            if key in data:
                value = data[key]
                if key == "reference_heightmap_orientation": value = "HORIZONTAL" if str(value).lower().startswith("h") else "VERTICAL"
                setattr(settings, key, value)
        settings.reference_heightmap_info_json = json.dumps(project.get("reference_heightmap_info", {}))
        incoming_frames = assets.get("source_frames", [])
        if isinstance(incoming_frames, list):
            settings.source_frames.clear()
            for raw in incoming_frames[:8]:
                resolved = _resolve_project_relative(settings, str(raw))
                if resolved and resolved.is_file() and _is_supported_image(resolved):
                    item = settings.source_frames.add()
                    item.path = str(resolved)
                    item.display_name = resolved.name
            settings.source_frame_index = min(settings.source_frame_index, max(0, len(settings.source_frames) - 1))
            if len(settings.source_frames) >= 2:
                settings.views = len(settings.source_frames)
        priority = str(project.get("requested_change", {}).get("priority", settings.priority))
        valid_priorities = {"lpi", "relief_prism_height_mm", "ior", "viewing_angle", "thickness_mm", "base_mm", "lens_profile", "backing_mm", "phase_pitch"}
        if priority in valid_priorities:
            settings.priority = priority
    finally:
        _state["applying"] = False
    # The selector/IOR values are the authoritative optical inputs in Automatic and
    # Semi-Automatic modes. Re-resolve the dependent Thickness, Base, Rise and
    # Viewing Angle after a project sync so the visible lens settings cannot remain
    # stale when the app changed an optical driver.
    if settings.workflow == "HEIGHTMAP":
        _apply_imported_heightmap_settings(settings)
    elif settings.settings_mode in {"AUTOMATIC", "SEMI"}:
        _apply_local_optical_rules(settings)
    else:
        if _custom_viewing_angle_active(settings):
            _apply_local_optical_rules(settings)
        else:
            settings.rise_mm = max(0.0, float(settings.thickness_mm) - float(settings.base_mm))
            settings.viewing_angle_deg = max(1.0, min(179.0, _viewing_angle_for_peak(settings)))
    _state["last_revision"] = _safe_int(project.get("revision"), 0)
    path = _project_path(settings)
    if path and path.exists():
        try:
            _state["last_mtime"] = path.stat().st_mtime
        except OSError:
            pass
    _state["dirty"] = False


def _current_project_dict(settings):
    path = _project_path(settings)
    existing = {}
    if path and path.is_file():
        try:
            existing = _load_json(path)
        except Exception:
            existing = {}
    revision = max(_state["last_revision"], _safe_int(existing.get("revision"), 0)) + 1
    project_dir = str(path.parent) if path else ""
    assets = existing.get("assets", {}) if isinstance(existing.get("assets", {}), dict) else {}
    if settings.interlaced_image:
        assets["interlaced_image"] = settings.interlaced_image
    if settings.heightmap_image:
        assets["heightmap"] = settings.heightmap_image
    assets["reference_heightmap"] = settings.reference_heightmap_path
    assets["source_frames"] = [_project_relative_path(settings, item.path) for item in settings.source_frames if item.path]
    mode_text = {"AUTOMATIC": "Automatic", "SEMI": "Semi-Automatic", "MANUAL": "Manual"}[settings.settings_mode]
    result = {
        "schema": 1,
        "revision": revision,
        "changed_by": "blender",
        "changed_utc_ticks": int(time.time() * 10000000),
        "project_name": existing.get("project_name", path.parent.name if path else "LenticularProject"),
        "project_dir": project_dir,
        "assets": assets,
        "settings": {
            "mode": mode_text,
            "output_mode": "Lens-Free Relief" if settings.output_mode == "RELIEF" else "Lenticular Lens",
            "relief_prism_height_mm": round(settings.relief_prism_height_mm, 6),
            "relief_base_mode": "No base",
            "relief_manual_base_mm": 0.0,
            "workflow": "Build from heightmap" if settings.workflow == "HEIGHTMAP" else "Build from source frames" if settings.workflow == "SOURCE_FRAMES" else "Use existing interlaced image",
            "width_mm": round(settings.width_mm, 6),
            "height_mm": round(settings.height_mm, 6),
            "lpi": round(settings.lpi, 6),
            "lpi_helper_mode": "Recommended" if settings.lpi_helper_mode == "RECOMMENDED" else "Manual",
            "lpi_helper_preset": settings.lpi_helper_preset.title(),
            "views": int(settings.views),
            "printer_dpi": int(settings.printer_dpi),
            "build_detail_mode": settings.build_detail_mode,
            "pixels_per_lenticule": int(_recommended_pixels_per_lenticule(settings) if settings.build_detail_mode != "CUSTOM" else settings.pixels_per_lenticule),
            "orientation": "Vertical" if settings.orientation == "VERTICAL" else "Horizontal",
            "lens_profile": _enum_to_profile(settings.lens_profile),
            "print_profile": _print_profile_label(settings.print_profile),
            "manual_thickness_mm": round(_manual_thickness_mm(settings), 6),
            "manual_thickness_unit": "um" if settings.manual_thickness_unit == "UM" else "mm",
            "base_mode": _base_mode_label(settings.base_mode),
            "manual_base_mm": round(settings.manual_base_mm, 6),
            "thickness_mm": round(settings.thickness_mm, 6),
            "base_mm": round(settings.base_mm, 6),
            "rise_mm": round(max(0.0, settings.thickness_mm - settings.base_mm), 6),
            "viewing_angle_mode": _viewing_angle_mode_label(settings),
            "custom_viewing_angle_deg": round(settings.custom_viewing_angle_deg, 6),
            "viewing_angle_deg": round(settings.viewing_angle_deg, 6),
            "ior": round(settings.ior, 6),
            "resin_surface_preset": settings.resin_surface_preset,
            "resin_roughness": round(settings.resin_roughness, 6),
            "micro_texture_enabled": bool(settings.micro_texture_enabled),
            "micro_texture_size_um": round(settings.micro_texture_size_um, 6),
            "micro_texture_height_um": round(settings.micro_texture_height_um, 6),
            "light_power_w": round(settings.light_power_w, 6),
            "light_angle_deg": round(settings.light_angle_deg, 6),
            "backing_mm": round(_effective_backing_mm(settings), 6),
            "backing_enabled": bool(settings.backing_enabled),
            "backing_saved_mm": round(settings.backing_mm, 6),
            "phase_pitch": round(settings.phase_pitch, 6),
        },
        "requested_change": {
            "priority": (
                "rebuild-pair" if _state.get("app_rebuild_pair_requested", False)
                else ("rebuild-heightmap" if _state.get("app_rebuild_heightmap_requested", False)
                else (settings.priority if _state.get("dirty_scope", "geometry") == "geometry" else ""))
            ),
            "scope": _state.get("dirty_scope", "geometry"),
        },
    }
    for key in _REFERENCE_SHARED_FIELDS:
        value = getattr(settings, key)
        result["settings"][key] = value.title() if key == "reference_heightmap_orientation" else value
    result["reference_heightmap_info"] = _reference_info(settings)
    result["settings"]["imported_heightmap_geometry"] = settings.workflow == "HEIGHTMAP"
    return result


def _send_to_app(context, quiet=False):
    settings = context.scene.lenticular_sync
    path = _project_path(settings)
    if not path:
        _set_status(settings, "Choose a project.json first")
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        project = _current_project_dict(settings)
        _write_json_atomic(path, project)
        _state["last_revision"] = int(project["revision"])
        _state["last_mtime"] = path.stat().st_mtime
        _state["dirty"] = False
        _state["dirty_scope"] = "geometry"
        _state["app_rebuild_pair_requested"] = False
        _state["app_rebuild_heightmap_requested"] = False
        if settings.auto_sync and _state.get("session_connected", False):
            _publish_app_project_handoff(path)
        _set_status(settings, "Sent to app - waiting for recalculation")
        return True
    except Exception as exc:
        _set_status(settings, "Send failed: " + str(exc))
        if not quiet:
            print("Lenticulizer sync send failed:", exc)
        return False


def _pull_from_app(context, rebuild=False, quiet=False):
    settings = context.scene.lenticular_sync
    path = _project_path(settings)
    if not path or not path.is_file():
        _set_status(settings, "Project file not found")
        return False
    try:
        project = _load_json(path)
        _apply_project_to_settings(settings, project)
        _set_status(settings, "Synced from app")
        if rebuild:
            _rebuild_scene(context, project)
        return True
    except Exception as exc:
        _set_status(settings, "Load failed: " + str(exc))
        if not quiet:
            print("Lenticulizer sync load failed:", exc)
        return False


def _remove_sim_collection():
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection:
        for obj in list(collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(collection)


def _remove_legacy_sim_objects():
    legacy_exact = {"Backing", "InterlacedImage", "LenticularLens", "ViewTarget"}
    for obj in list(bpy.data.objects):
        base_name = obj.name.split(".")[0]
        is_legacy = base_name in legacy_exact or base_name.startswith("View_")
        if is_legacy:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass


def _new_sim_collection(scene):
    _remove_sim_collection()
    _remove_legacy_sim_objects()
    for material in list(bpy.data.materials):
        if material.name.startswith(OBJECT_PREFIX) and material.users == 0:
            try:
                bpy.data.materials.remove(material)
            except Exception:
                pass
    collection = bpy.data.collections.new(COLLECTION_NAME)
    scene.collection.children.link(collection)
    return collection


def _move_to_collection(obj, collection):
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    collection.objects.link(obj)


def _paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _reference_axis_cache_key(path, vertical):
    try:
        resolved = Path(path).resolve()
        stat = resolved.stat()
        return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size), bool(vertical))
    except Exception:
        return (str(path), 0, 0, bool(vertical))


def _trim_reference_caches():
    # Reference scanlines are small, but avoid accumulating stale entries when
    # repeatedly comparing different files during a long Blender session.
    if len(_reference_axis_cache) > 8:
        _reference_axis_cache.clear()
    if len(_reference_cross_section_meta_cache) > 16:
        _reference_cross_section_meta_cache.clear()


def _read_png_axis_values_exact(path, vertical):
    """Decode only the required center scanline from a non-interlaced PNG.

    PNG row filters require processing prior rows, but we deliberately retain
    only the previous row plus the requested center row/column. This avoids the
    very large temporary row list used by v1.14.3 on high-resolution 16-bit
    heightmaps.
    """
    path = Path(path)
    if path.suffix.lower() != ".png" or not path.is_file():
        return None
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", payload[:13])
            if compression != 0 or filter_method != 0:
                return None
        elif ctype == b"IDAT":
            idat.extend(payload)
        elif ctype == b"IEND":
            break
    if not width or not height or interlace != 0:
        return None
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(color_type)
    if channels is None or bit_depth not in (8, 16):
        return None
    sample_bytes = 2 if bit_depth == 16 else 1
    bpp = channels * sample_bytes
    stride = width * bpp
    raw = zlib.decompress(bytes(idat))
    expected = height * (stride + 1)
    if len(raw) < expected:
        return None

    def first_channel(row, x):
        index = x * bpp
        if bit_depth == 16:
            sample = (row[index] << 8) | row[index + 1]
            return sample / 65535.0
        return row[index] / 255.0

    previous = bytearray(stride)
    offset = 0
    target_y = max(0, min(height - 1, height // 2))
    target_x = max(0, min(width - 1, width // 2))
    values = []
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        scan = memoryview(raw)[offset:offset + stride]
        offset += stride
        recon = bytearray(stride)
        for i, value in enumerate(scan):
            left = recon[i - bpp] if i >= bpp else 0
            up = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = _paeth_predictor(left, up, up_left)
            else:
                return None
            recon[i] = (int(value) + predictor) & 0xFF

        if vertical:
            if y == target_y:
                values = [first_channel(recon, x) for x in range(width)]
                # The center row itself is all we need. PNG filtering for later
                # rows is irrelevant once it has been reconstructed.
                break
        else:
            values.append(first_channel(recon, target_x))
        previous = recon

    return int(width), int(height), tuple(values)


def _load_axis_values(path, vertical):
    """Return the exact center height scanline, cached until the file changes."""
    key = _reference_axis_cache_key(path, vertical)
    cached = _reference_axis_cache.get(key)
    if cached is not None:
        return cached

    exact = _read_png_axis_values_exact(path, vertical)
    if exact is not None:
        result = exact
    else:
        image = bpy.data.images.load(str(path), check_existing=True)
        width, height = int(image.size[0]), int(image.size[1])
        pixels = image.pixels
        if vertical:
            y = max(0, min(height - 1, height // 2))
            start = (y * width) * 4
            row = pixels[start:start + width * 4]
            values = tuple(max(0.0, min(1.0, float(row[x * 4]))) for x in range(width))
        else:
            x = max(0, min(width - 1, width // 2))
            values = tuple(max(0.0, min(1.0, float(pixels[(y * width + x) * 4]))) for y in range(height))
        result = (width, height, values)

    _trim_reference_caches()
    _reference_axis_cache[key] = result
    return result


def _reference_material(settings, create=False):
    name = OBJECT_PREFIX + "ReferenceHeightmapMat"
    material = bpy.data.materials.get(name)
    if material is None and create:
        material = bpy.data.materials.new(name)
        material.use_nodes = True
    return material


def _apply_reference_display_style(settings):
    material = _reference_material(settings, create=False)
    if material is None:
        return
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is None:
        return
    style = str(getattr(settings, "reference_heightmap_display_style", "OPAQUE") or "OPAQUE")
    # Keep the inspection modes intentionally high-contrast. Clear Resin remains
    # available when the user wants to compare the reference as an optical object.
    if style == "CLEAR":
        base = (0.96, 0.985, 1.0, 1.0)
        transmission = 1.0
        roughness = max(0.0, min(1.0, float(settings.resin_roughness)))
    elif style == "TINTED":
        base = (0.12, 0.52, 0.78, 1.0)
        transmission = 0.30
        roughness = 0.24
    else:
        base = (0.10, 0.38, 0.72, 1.0)
        transmission = 0.0
        roughness = 0.32
    bsdf.inputs["Base Color"].default_value = base
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["IOR"].default_value = max(1.0, float(settings.ior))
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = transmission
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = transmission
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = 1.0
    try:
        material.diffuse_color = base
    except Exception:
        pass


def _reference_cross_section_signature(settings):
    path = _resolve_preview_path(settings, settings.reference_heightmap_path)
    if path is None or not path.is_file():
        return None
    try:
        stat = path.stat()
        stamp = stat.st_mtime_ns
    except Exception:
        stamp = 0
    return repr((
        str(path.resolve()), stamp,
        settings.reference_heightmap_orientation,
        round(float(settings.reference_heightmap_width_mm), 6),
        round(float(settings.reference_heightmap_height_mm), 6),
        round(float(settings.reference_heightmap_thickness_mm), 6),
        str(getattr(settings, "reference_cross_section_span", "12")),
        round(float(getattr(settings, "lpi", 0.0)), 6),
    ))


def _reference_cross_section_preview(settings):
    signature = _reference_cross_section_signature(settings)
    if signature is None:
        return None
    # Preview revision prevents stale thumbnails created by the older renderer
    # from being reused after switching every cross-section path to the common
    # 1:1 physical X:Z renderer.
    signature = 'common_physical_1to1_v1|' + signature
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:18]
    temp_dir = Path(bpy.app.tempdir or tempfile.gettempdir()) / "lenticular_previews"
    path = temp_dir / ("reference_heightmap_cross_section_1to1_" + digest + ".png")

    cached_meta = _reference_cross_section_meta_cache.get(signature)
    if cached_meta is not None and path.is_file():
        return (path,) + cached_meta

    vertical = settings.reference_heightmap_orientation == "VERTICAL"
    source_path = _resolve_preview_path(settings, settings.reference_heightmap_path)
    source_w, source_h, values = _load_axis_values(source_path, vertical)
    if not values:
        return None

    # Prefer the actual generated reference mesh so the sidebar is the same
    # geometry that Blender is displaying. Fall back to the heightmap-derived
    # profile only when that mesh has not been built yet.
    obj = bpy.data.objects.get(OBJECT_PREFIX + 'ReferenceHeightmapLens')
    all_points = _mesh_cross_section_points(obj, vertical)
    if not all_points:
        all_points = _fallback_reference_cross_section_points(settings)
    if not all_points:
        return None

    points = _crop_reference_profile_to_selected_span(settings, all_points)
    if not points:
        return None

    x_values = [float(p[0]) for p in points]
    z_values = [float(p[1]) for p in points]
    displayed_span_mm = max(0.000001, max(x_values) - min(x_values))
    actual_height_mm = max(0.000001, max(z_values))
    min_mm = min(z_values)
    max_mm = max(z_values)
    total_samples = len(all_points)
    sample_count = len(points)

    span_mode = str(getattr(settings, "reference_cross_section_span", "12") or "12")
    shown_lenticules = "Full Width" if span_mode == "FULL" else f"~{span_mode} lenticules"

    _render_sidebar_cross_section(points, path)
    meta = (
        source_w, source_h, sample_count, min_mm, max_mm, total_samples,
        shown_lenticules, displayed_span_mm, actual_height_mm,
    )
    _trim_reference_caches()
    _reference_cross_section_meta_cache[signature] = meta
    return (path,) + meta

def _draw_reference_cross_section(layout, settings):
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        settings,
        "reference_cross_section_expanded",
        text="",
        icon="TRIA_DOWN" if settings.reference_cross_section_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text="Exact Heightmap Cross Section")
    open_view = header.operator("lenticular.open_cross_section_viewer", text="Open Full View", icon="IMAGE_DATA")
    open_view.source_kind = "REFERENCE"

    if not settings.reference_cross_section_expanded:
        return

    try:
        result = _reference_cross_section_preview(settings)
        if result is None:
            box.label(text="Import a heightmap to view its cross section", icon="INFO")
            return
        preview_path, source_w, source_h, sample_count, min_mm, max_mm, total_samples, shown_lenticules, displayed_span_mm, actual_height_mm = result
        icon_id = _preview_icon_for_file(preview_path, "reference_cross_section")
        axis_name = "Center row / X" if settings.reference_heightmap_orientation == "VERTICAL" else "Center column / Y"
        if icon_id:
            preview_row = box.row()
            preview_row.alignment = 'CENTER'
            preview_row.template_icon(icon_value=icon_id, scale=10.0)
        else:
            box.label(text="Cross-section preview unavailable", icon="IMAGE_DATA")

        row = box.row(align=True)
        row.label(text=shown_lenticules)
        row.label(text=f"{displayed_span_mm:.3f} x {actual_height_mm:.4f} mm")
        row.label(text="X:Z 1:1")
        row = box.row(align=True)
        row.label(text=axis_name)
        row.label(text=f"{sample_count}/{total_samples} samples")
        row.label(text=f"Gray 0..1 = 0..{settings.reference_heightmap_thickness_mm:.4f} mm")
    except Exception as exc:
        box.label(text="Cross-section preview unavailable", icon="ERROR")
        box.label(text=str(exc))

def _normalized_surface(values):
    if not values:
        return [0.0, 1.0]
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span < 1e-8:
        return [0.0 for _ in values]
    return [(v - lo) / span for v in values]


def _reference_profile_z(u):
    samples = [0.0000, 0.1700, 0.4200, 0.5400, 0.6300, 0.7000, 0.7500, 0.8000, 0.8400, 0.8800, 0.9100, 0.9300, 0.9500, 0.9650, 0.9800, 0.9900, 1.0000]
    u = max(0.0, min(1.0, float(u)))
    fp = u * (len(samples) - 1)
    i = int(math.floor(fp))
    if i >= len(samples) - 1:
        return samples[-1]
    t = fp - i
    return samples[i] + (samples[i + 1] - samples[i]) * t


def _conic_sag(x, radius, conic_k):
    if radius <= 0:
        return 0.0
    term = 1.0 - (1.0 + conic_k) * x * x / (radius * radius)
    term = max(0.0, term)
    denom = radius * (1.0 + math.sqrt(term))
    return 0.0 if abs(denom) < 1e-12 else x * x / denom


def _circular_profile_z(x, radius, hshape):
    inside = max(0.0, radius * radius - x * x)
    z = (math.sqrt(inside) - (radius - hshape)) / max(hshape, 1e-9)
    return max(0.0, min(1.0, z))


def _resolved_local_profile(settings):
    if _lens_free_mode(settings):
        return "RELIEF"
    value = settings.lens_profile
    if value == "AUTO":
        return _recommended_lens_profile(settings)
    if value == "AUTO_THEORETICAL":
        return "THEORETICAL"
    return value


def _profile_value_for_phase_overrides(settings, phase, profile_override=None, peak_override=None, base_override=None):
    phase = float(phase) % 1.0
    x = phase - 0.5
    a = 0.5
    lpi = max(0.001, float(settings.lpi))
    pitch_mm = 25.4 / lpi
    peak_mm = float(settings.thickness_mm if peak_override is None else peak_override)
    base_mm = float(settings.base_mm if base_override is None else base_override)
    rise_mm = max(0.000001, peak_mm - base_mm)
    ratio = rise_mm / pitch_mm
    hshape = max(ratio, 0.001)
    radius = (a * a + hshape * hshape) / (2.0 * hshape)
    profile = _resolved_local_profile(settings) if profile_override is None else profile_override
    if profile == "AUTO":
        profile = _recommended_lens_profile(settings)
    elif profile == "AUTO_THEORETICAL":
        profile = "THEORETICAL"
    facets = max(4, int(settings.views) * 2)
    conic_k = -1.0 / max(1.0001, float(settings.ior)) ** 2
    edge_sag = _conic_sag(a, radius, conic_k)

    if profile == "REFERENCE":
        u = 1.0 - min(1.0, abs(x) / a)
        z = _reference_profile_z(u)
    elif profile == "RELIEF":
        z = _relief_profile_value(settings, phase)
    elif profile == "THEORETICAL":
        # Exact aplanatic surface that collimates the center image point.
        # When peak/base are the mathematical automatic values, this is the
        # first-principles surface with no empirical calibration dimensions.
        shape_peak = max(peak_mm, _theoretical_minimum_peak_mm(settings, lpi))
        x_mm = x * pitch_mm
        edge_mm = _theoretical_base_for_peak_mm(settings, lpi, shape_peak)
        surface_mm = _theoretical_surface_height_mm(settings, lpi, shape_peak, x_mm)
        denom = shape_peak - edge_mm
        z = 0.0 if edge_mm < 0.0 or surface_mm < 0.0 or denom <= 1e-9 else (surface_mm - edge_mm) / denom
    elif profile == "COSINE":
        z = 0.5 * (1.0 + math.cos(math.pi * max(-1.0, min(1.0, x / a))))
    elif profile == "TRIANGULAR":
        z = 1.0 - min(1.0, abs(x) / a)
    elif profile == "ASPHERIC":
        if edge_sag <= 1e-9:
            z = _circular_profile_z(x, radius, hshape)
        else:
            x_sag = _conic_sag(abs(x), radius, conic_k)
            z = 1.0 - max(0.0, min(1.0, x_sag / edge_sag))
    elif profile == "PRISMATIC":
        u = min(1.0, abs(x) / a)
        fp = u * facets
        fi = min(facets - 1, int(math.floor(fp)))
        local = fp - fi
        u0 = fi / float(facets)
        u1 = (fi + 1) / float(facets)
        z0 = _circular_profile_z(u0 * a, radius, hshape)
        z1 = _circular_profile_z(u1 * a, radius, hshape)
        z = z0 + (z1 - z0) * local
    else:
        z = _circular_profile_z(x, radius, hshape)
    return max(0.0, min(1.0, z))


def _profile_value_for_phase(settings, phase):
    return _profile_value_for_phase_overrides(settings, phase)


def _surface_from_settings(settings):
    if settings.workflow == "HEIGHTMAP":
        data = _reference_data(settings)
        values = data[0] if settings.reference_heightmap_orientation == "VERTICAL" else data[1][::-1]
        return [float(v) for v in values]
    _validate_theoretical_printability(settings)
    vertical = settings.orientation == "VERTICAL"
    axis_mm = float(settings.width_mm) if vertical else float(settings.height_mm)
    lpi = max(0.001, float(settings.lpi))
    pitch_mm = 25.4 / lpi
    lens_count = max(1.0, axis_mm / pitch_mm)
    ppl = max(16, min(128, _recommended_pixels_per_lenticule(settings)))
    count = max(64, min(24000, int(round(lens_count * ppl)) + 1))
    phase_offset = float(settings.phase_pitch)
    values = []
    for i in range(count):
        physical_mm = axis_mm * i / max(1, count - 1)
        if not vertical and not _lens_free_mode(settings):
            # PNG/interlaced rasters are indexed visually from top to bottom. In the
            # upright print transform, local +Y is the top edge, while mesh samples
            # are emitted from local -Y to +Y. Traverse phase from the top edge so
            # horizontal lenticule slopes are registered to the same raster rows.
            physical_mm = axis_mm - physical_mm
        phase = (physical_mm / pitch_mm + phase_offset) % 1.0
        values.append(_profile_value_for_phase(settings, phase))
    return values


def _cross_section_profile_value(settings, phase):
    # The preview calls the exact same profile function as the generated lens mesh.
    return _profile_value_for_phase(settings, phase)


def _png_chunk(chunk_type, payload):
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xffffffff)


def _pixels_per_meter(width_px, height_px, width_mm=None, height_mm=None, fallback_dpi=72.0):
    try:
        width_mm = float(width_mm) if width_mm is not None else 0.0
        height_mm = float(height_mm) if height_mm is not None else 0.0
    except Exception:
        width_mm = 0.0
        height_mm = 0.0
    if width_mm > 0.0 and height_mm > 0.0:
        x_ppm = max(1, int(round(float(width_px) / (width_mm / 1000.0))))
        y_ppm = max(1, int(round(float(height_px) / (height_mm / 1000.0))))
        return x_ppm, y_ppm
    ppm = max(1, int(round(float(fallback_dpi) / 0.0254)))
    return ppm, ppm


def _write_rgba_png(path, width, height, rgba_bytes, pixels_per_meter=None, text_metadata=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stride = width * 4
    raw = bytearray()
    # PNG rows are written top to bottom. Our raster buffer is bottom-up for the chart,
    # so reverse the row order while serializing.
    for row in range(height - 1, -1, -1):
        raw.append(0)  # filter type 0
        start = row * stride
        raw.extend(rgba_bytes[start:start + stride])
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)))
    if pixels_per_meter:
        x_ppm, y_ppm = pixels_per_meter
        png.extend(_png_chunk(b"pHYs", struct.pack(">IIB", int(x_ppm), int(y_ppm), 1)))
    if text_metadata:
        for key, value in text_metadata.items():
            key_bytes = str(key).encode("latin-1", errors="ignore")
            value_bytes = str(value).encode("utf-8")
            png.extend(_png_chunk(b"tEXt", key_bytes + b"\x00" + value_bytes))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(png)


def _write_gray16_png(path, width, height, row_iterable, pixels_per_meter=None, vertical_profile=None):
    """Write a 16-bit grayscale PNG without building it pixel-by-pixel in Python.

    Automatic rebuilds can create multi-megapixel heightmaps.  The old writer
    packed every individual sample with struct.pack(), which made heightmap I/O
    dominate Blender's live rebuild time.  NumPy handles the raster packing in C
    and zlib is streamed in modest chunks so memory use stays bounded.  The
    pure-Python fallback is retained for Blender builds without NumPy.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0)))
    if pixels_per_meter:
        x_ppm, y_ppm = pixels_per_meter
        png.extend(_png_chunk(b"pHYs", struct.pack(">IIB", int(x_ppm), int(y_ppm), 1)))

    compressor = zlib.compressobj(level=1)
    compressed = bytearray()
    if np is not None:
        # Materialize only the 1-D profile.  _generate_heightmap_file supplies
        # either one full-width row repeated for every scanline, or one scalar
        # value per scanline repeated across the width.
        rows = iter(row_iterable)
        first = next(rows, None)
        if first is None:
            raise RuntimeError("Heightmap has no raster rows")
        first_vals = np.asarray(tuple(first), dtype=np.uint16)
        if vertical_profile is True:
            # Vertical lenticules: every raster row is identical.  Build and
            # compress 64 scanlines at a time instead of looping every pixel.
            if first_vals.size != width:
                raise RuntimeError("Vertical heightmap row width mismatch")
            be_row = np.clip(first_vals, 0, 65535).astype('>u2', copy=False).view(np.uint8).reshape(1, width * 2)
            chunk_rows = 64
            y = 0
            while y < height:
                count = min(chunk_rows, height - y)
                packet = np.zeros((count, 1 + width * 2), dtype=np.uint8)
                packet[:, 1:] = be_row
                compressed.extend(compressor.compress(packet.tobytes()))
                y += count
        elif vertical_profile is False:
            # Horizontal lenticules: each full-width scanline is a constant
            # value.  Read only one sample from each row and expand in NumPy.
            values = [int(first_vals[0])]
            values.extend(int(tuple(row)[0]) for row in rows)
            vals = np.clip(np.asarray(values, dtype=np.int64), 0, 65535).astype('>u2')
            chunk_rows = 64
            for start in range(0, min(height, vals.size), chunk_rows):
                block_vals = vals[start:start + chunk_rows]
                block = np.repeat(block_vals[:, None], width, axis=1)
                raw_rows = block.view(np.uint8).reshape(block_vals.size, width * 2)
                packet = np.zeros((block_vals.size, 1 + width * 2), dtype=np.uint8)
                packet[:, 1:] = raw_rows
                compressed.extend(compressor.compress(packet.tobytes()))
        else:
            # Generic vectorized row path when the caller does not declare the
            # profile orientation.  This preserves arbitrary row content.
            def emit(row):
                vals = np.clip(np.asarray(tuple(row), dtype=np.int64), 0, 65535).astype('>u2')
                return b"\x00" + vals.tobytes()
            compressed.extend(compressor.compress(emit(first)))
            for row in rows:
                compressed.extend(compressor.compress(emit(row)))
    else:
        for row in row_iterable:
            raw = bytearray((0,))
            for value in row:
                v = int(max(0, min(65535, value)))
                raw.extend(struct.pack(">H", v))
            compressed.extend(compressor.compress(bytes(raw)))
    compressed.extend(compressor.flush())
    png.extend(_png_chunk(b"IDAT", bytes(compressed)))
    png.extend(_png_chunk(b"IEND", b""))
    path.write_bytes(png)


def _current_interlaced_path(settings):
    image_path = _resolve_project_relative(settings, settings.interlaced_image) if settings.interlaced_image else None
    if image_path and image_path.is_file():
        return image_path
    path = _project_path(settings)
    project = None
    if path and path.is_file():
        try:
            project = _load_json(path)
        except Exception:
            project = None
    if project:
        image_path = _resolve_asset(project, "interlaced_image", settings)
        if image_path and image_path.is_file():
            return image_path
    return None


def _image_dimensions_from_file(path):
    try:
        img = bpy.data.images.load(str(path), check_existing=True)
        return int(img.size[0]), int(img.size[1])
    except Exception:
        return None


def _heightmap_dimensions(settings):
    image_path = _current_interlaced_path(settings)
    if image_path:
        dims = _image_dimensions_from_file(image_path)
        if dims and dims[0] > 0 and dims[1] > 0:
            return dims
    if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"} and len(settings.source_frames) >= 2:
        return _build_target_canvas_size(settings)
    return None


def _generate_heightmap_file(settings, output_path):
    imported_source = _resolve_preview_path(settings, settings.reference_heightmap_path)
    if imported_source and Path(output_path).resolve() == imported_source.resolve():
        raise ValueError("The imported heightmap cannot be overwritten")
    if settings.workflow == "HEIGHTMAP":
        source = _resolve_preview_path(settings, settings.reference_heightmap_path)
        output_path = Path(output_path).with_suffix(source.suffix.lower())
        heightmap_tools.copy_heightmap(source, output_path, settings.reference_heightmap_width_mm, settings.reference_heightmap_height_mm, settings.reference_heightmap_thickness_mm)
        settings.heightmap_image = _project_relative_path(settings, output_path)
        return output_path
    _validate_theoretical_printability(settings)
    dims = _heightmap_dimensions(settings)
    if not dims:
        raise RuntimeError("Build or load an interlaced image first")
    width, height = int(dims[0]), int(dims[1])
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid interlaced image dimensions")
    peak_mm = max(0.000001, float(settings.thickness_mm))
    base_mm = max(0.0, min(peak_mm, float(settings.base_mm)))
    rise_mm = max(0.0, peak_mm - base_mm)
    surface = _surface_from_settings(settings)
    axis_count = width if settings.orientation == "VERTICAL" else height
    axis_count = max(1, int(axis_count))
    if len(surface) != axis_count:
        if np is not None and len(surface) > 1:
            xp = np.linspace(0.0, 1.0, len(surface))
            sample_x = np.linspace(0.0, 1.0, axis_count)
            sampled = np.interp(sample_x, xp, surface)
            surface = [float(v) for v in sampled]
        else:
            sampled = []
            for i in range(axis_count):
                fp = (len(surface) - 1) * (i / max(1, axis_count - 1))
                idx = int(fp)
                if idx >= len(surface) - 1:
                    sampled.append(float(surface[-1]))
                else:
                    t = fp - idx
                    sampled.append(float(surface[idx] + (surface[idx + 1] - surface[idx]) * t))
            surface = sampled
    values16 = []
    for z_norm in surface:
        physical_mm = base_mm + max(0.0, min(1.0, float(z_norm))) * rise_mm
        values16.append(int(round((physical_mm / peak_mm) * 65535.0)))
    if settings.orientation == "VERTICAL":
        row = tuple(values16)
        rows = (row for _ in range(height))
    else:
        rows = ((values16[y],) * width for y in range(height))
    _write_gray16_png(output_path, width, height, rows, _pixels_per_meter(width, height, settings.width_mm, settings.height_mm), settings.orientation == "VERTICAL")
    annotated = Path(output_path).with_name(Path(output_path).name + "." + uuid.uuid4().hex + ".tmp")
    try:
        heightmap_tools.copy_heightmap(Path(output_path), annotated, settings.width_mm, settings.height_mm, peak_mm)
        os.replace(annotated, output_path)
    finally:
        if annotated.exists(): annotated.unlink()
    settings.heightmap_image = _project_relative_path(settings, Path(output_path)) if _project_dir(settings) else str(output_path)
    return Path(output_path)


_CALIBRATION_MODE_LABELS = {
    "THICKNESS": "Thickness Test",
    "VIEWING": "Viewing Test",
    "ALIGNMENT": "Alignment Test",
    "LENS_TYPE": "Lens Type Test",
}


def _calibration_coupon_size_mm(settings):
    try:
        return float(settings.calibration_coupon_size_mm)
    except Exception:
        return 20.0


def _safe_calibration_name(value):
    result = []
    for c in str(value or "variant"):
        if c.isalnum():
            result.append(c)
        elif c == ".":
            result.append("p")
        elif c == "-":
            result.append("m")
        elif c in {"_", " "}:
            result.append("_")
    cleaned = "".join(result).strip("_")
    return cleaned or "variant"


def _minimum_focused_peak_mm(settings, lpi):
    if _uses_theoretical_optics(settings):
        return _theoretical_minimum_peak_mm(settings, lpi)
    return MIN_NONZERO_PEAK_MM


def _raw_peak_for_viewing_angle_mm(settings, lpi, angle_deg):
    n = max(1.0001, float(settings.ior))
    a = (25.4 / max(0.001, float(lpi))) * 0.5
    half_radians = float(angle_deg) * math.pi / 360.0
    if _uses_theoretical_optics(settings):
        s = math.sin(half_radians) / n
        if s <= 1.0e-12:
            return MAX_PEAK_MM + 1.0
        s = min(0.999999999, s)
        return a * math.sqrt(max(0.0, 1.0 - s * s)) / s
    tangent = math.tan(half_radians)
    if abs(tangent) < 1.0e-12:
        return MAX_PEAK_MM + 1.0
    return max(MIN_NONZERO_PEAK_MM, n * a / tangent)


def _focused_valley_for_peak_mm(settings, lpi, peak_mm):
    peak_mm = float(peak_mm)
    if peak_mm <= 0.0 or peak_mm > MAX_PEAK_MM + 1.0e-4:
        return -1.0
    if _uses_theoretical_optics(settings):
        if peak_mm + 1e-6 < _theoretical_minimum_peak_mm(settings, lpi):
            return -1.0
        return _theoretical_base_for_selected_peak(settings, lpi, peak_mm)
    return _recommended_base_for_peak(lpi, peak_mm)


def _adjust_peak_for_printer_valley_mm(settings, lpi, peak_mm):
    # Do not force a different theoretical focal thickness. Preserve the
    # requested calibration target and let normal printer constraints decide
    # whether it is printable.
    return float(peak_mm)


def _calibration_variant(settings, name, peak_mm, valley_mm, phase_pitch, profile, angle_deg, note):
    peak_mm = float(peak_mm)
    valley_mm = float(valley_mm)
    if peak_mm <= 0.0 or peak_mm > MAX_PEAK_MM + 1.0e-4:
        return None
    if valley_mm < 0.0 or valley_mm > peak_mm:
        return None
    if 0.0 < valley_mm < MIN_NONZERO_BASE_MM:
        return None
    return {
        "name": str(name),
        "peak_mm": peak_mm,
        "valley_mm": valley_mm,
        "phase_pitch": float(phase_pitch),
        "profile": str(profile),
        "viewing_angle_deg": float(angle_deg),
        "note": str(note),
    }


def _build_calibration_variants(settings):
    variants = []
    mode = getattr(settings, "calibration_mode", "THICKNESS")
    lpi = max(0.001, float(settings.lpi))
    current_profile = _resolved_local_profile(settings)
    current_phase = float(settings.phase_pitch)
    current_peak = float(settings.thickness_mm)
    current_valley = float(settings.base_mm)

    def add(*args):
        variant = _calibration_variant(settings, *args)
        if variant is not None:
            variants.append(variant)

    if mode == "THICKNESS":
        for delta in (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15):
            peak = current_peak + delta
            if peak <= 0.0 or peak > MAX_PEAK_MM + 1.0e-4:
                continue
            valley = _focused_valley_for_peak_mm(settings, lpi, peak)
            if valley < 0.0 or (0.0 < valley < MIN_NONZERO_BASE_MM):
                continue
            add(
                "focus_" + format(peak, ".2f") + "mm",
                peak, valley, current_phase, current_profile,
                _viewing_angle_for_peak(settings, peak),
                "Focused thickness sweep",
            )
    elif mode == "VIEWING":
        for angle in (32.0, 35.0, 38.0, 41.0, 44.0):
            peak = _adjust_peak_for_printer_valley_mm(settings, lpi, _raw_peak_for_viewing_angle_mm(settings, lpi, angle))
            if peak <= 0.0 or peak > MAX_PEAK_MM + 1.0e-4:
                continue
            valley = _focused_valley_for_peak_mm(settings, lpi, peak)
            if valley < 0.0 or (0.0 < valley < MIN_NONZERO_BASE_MM):
                continue
            add(
                "angle_" + format(angle, ".0f") + "deg",
                peak, valley, current_phase, current_profile,
                _viewing_angle_for_peak(settings, peak),
                "Viewing-angle sweep",
            )
    elif mode == "ALIGNMENT":
        for phase_delta in (-0.06, -0.03, 0.0, 0.03, 0.06):
            phase_text = ("+" if phase_delta > 0 else "") + format(phase_delta, ".2f")
            add(
                "phase_" + phase_text,
                current_peak, current_valley, current_phase + phase_delta, current_profile,
                _viewing_angle_for_peak(settings, current_peak),
                "Phase sweep",
            )
    else:
        for profile, label in (
            ("THEORETICAL", "Mathematically Optimal Aspheric"),
            ("ASPHERIC", "Aspheric"),
            ("CIRCULAR", "Rounded / Circular"),
            ("PRISMATIC", "Multi-facet / Prismatic"),
            ("COSINE", "Cosine"),
            ("TRIANGULAR", "Linear / Triangular"),
        ):
            add(
                "profile_" + _safe_calibration_name(label),
                current_peak, current_valley, current_phase, profile,
                _viewing_angle_for_peak(settings, current_peak),
                "Lens-shape comparison",
            )
    return variants


def _calibration_mode_summary(settings, variants=None):
    variants = _build_calibration_variants(settings) if variants is None else variants
    if not variants:
        return "No calibration variants fit the current printer limits"
    mode = settings.calibration_mode
    if mode == "THICKNESS":
        return "Thicknesses: " + ", ".join(format(v["peak_mm"], ".2f") for v in variants) + " mm"
    if mode == "VIEWING":
        return "Angles: " + ", ".join(format(v["viewing_angle_deg"], ".1f") + "°" for v in variants)
    if mode == "ALIGNMENT":
        return "Phase: " + ", ".join(format(v["phase_pitch"], "+.2f") for v in variants)
    return "Shapes: " + ", ".join(_enum_to_profile(v["profile"]) for v in variants)


def _calibration_output_root(settings):
    raw = bpy.path.abspath(getattr(settings, "calibration_output_dir", "") or "").strip()
    if raw:
        root = Path(raw)
    else:
        root = _project_dir(settings) or _workspace_dir(settings)
    if root is None:
        raise RuntimeError("Choose a calibration output folder")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_center_coupon(settings, image_path, coupon_mm):
    if np is None:
        raise RuntimeError("Blender NumPy support is required for calibration coupon generation")
    image = bpy.data.images.load(str(image_path), check_existing=True)
    try:
        image.reload()
    except Exception:
        pass
    width = int(image.size[0])
    height = int(image.size[1])
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid interlaced image dimensions")
    full_w_mm = max(0.001, float(settings.width_mm))
    full_h_mm = max(0.001, float(settings.height_mm))
    coupon_w_mm = min(float(coupon_mm), full_w_mm)
    coupon_h_mm = min(float(coupon_mm), full_h_mm)
    crop_w = max(8, min(width, int(round(width * coupon_w_mm / full_w_mm))))
    crop_h = max(8, min(height, int(round(height * coupon_h_mm / full_h_mm))))
    crop_x = max(0, (width - crop_w) // 2)
    crop_y = max(0, (height - crop_h) // 2)
    raw = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(raw)
    source = raw.reshape((height, width, 4))
    crop = source[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w, :]
    rgba_u8 = np.clip(np.rint(crop * 255.0), 0, 255).astype(np.uint8).ravel().tobytes()
    return rgba_u8, crop_x, crop_y, crop_w, crop_h, coupon_w_mm, coupon_h_mm, width, height


def _write_calibration_heightmap(settings, variant, output_path, crop_x, crop_y, crop_w, crop_h, coupon_w_mm, coupon_h_mm, full_w_px, full_h_px):
    vertical = settings.orientation == "VERTICAL"
    lpi = max(0.001, float(settings.lpi))
    axis_full_px = full_w_px if vertical else full_h_px
    axis_full_mm = float(settings.width_mm) if vertical else float(settings.height_mm)
    axis_dpi = axis_full_px / max(1.0e-9, axis_full_mm / 25.4)
    pitch_px = axis_dpi / lpi
    crop_axis_start = crop_x if vertical else crop_y
    coupon_axis_px = crop_w if vertical else crop_h
    coupon_phase = float(variant["phase_pitch"]) + crop_axis_start / max(1.0e-9, pitch_px)
    peak = float(variant["peak_mm"])
    base = float(variant["valley_mm"])
    rise = max(0.0, peak - base)
    profile = variant["profile"]
    axis_values = []
    for i in range(coupon_axis_px):
        phase = (i / max(1.0e-9, pitch_px)) + coupon_phase
        z_norm = _profile_value_for_phase_overrides(settings, phase, profile, peak, base)
        physical_mm = base + z_norm * rise
        axis_values.append(int(round(max(0.0, min(1.0, physical_mm / max(1.0e-9, peak))) * 65535.0)))
    if vertical:
        row = tuple(axis_values)
        rows = (row for _ in range(crop_h))
    else:
        rows = ((axis_values[y],) * crop_w for y in range(crop_h))
    ppm = _pixels_per_meter(crop_w, crop_h, coupon_w_mm, coupon_h_mm)
    _write_gray16_png(output_path, crop_w, crop_h, rows, ppm, vertical)


def _generate_calibration_coupon_set(settings):
    if settings.workflow == "HEIGHTMAP":
        raise RuntimeError("Use the registration control for imported heightmaps; procedural calibration changes lens geometry")
    image_path = _current_interlaced_path(settings)
    if image_path is None or not image_path.is_file():
        raise RuntimeError("Build or import an interlaced image first")
    variants = _build_calibration_variants(settings)
    if not variants:
        raise RuntimeError("No calibration variants fit the current 0.30–5.00 mm printer limits")

    coupon_mm = _calibration_coupon_size_mm(settings)
    rgba_u8, crop_x, crop_y, crop_w, crop_h, coupon_w_mm, coupon_h_mm, full_w_px, full_h_px = _extract_center_coupon(settings, image_path, coupon_mm)
    mode_label = _CALIBRATION_MODE_LABELS.get(settings.calibration_mode, "Calibration")
    stamp = time.strftime("%Y%m%d_%H%M%S")
    folder = _calibration_output_root(settings) / ("Lenticular_Calibration_" + _safe_calibration_name(mode_label) + "_" + stamp)
    folder.mkdir(parents=True, exist_ok=True)

    source_name = "calibration_source_" + format(coupon_w_mm, ".2f").rstrip("0").rstrip(".").replace(".", "p") + "x" + format(coupon_h_mm, ".2f").rstrip("0").rstrip(".").replace(".", "p") + "mm.png"
    source_path = folder / source_name
    _write_rgba_png(source_path, crop_w, crop_h, rgba_u8, _pixels_per_meter(crop_w, crop_h, coupon_w_mm, coupon_h_mm))

    csv_path = folder / "calibration_index.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("Variant,Source Image,Heightmap,Peak mm,Valley mm,Lens Rise mm,Viewing Angle deg,Phase pitch,Lens Shape,Note\n")
        for index, variant in enumerate(variants, 1):
            heightmap_name = f"{index:02d}_{_safe_calibration_name(variant['name'])}_heightmap16.png"
            heightmap_path = folder / heightmap_name
            _write_calibration_heightmap(settings, variant, heightmap_path, crop_x, crop_y, crop_w, crop_h, coupon_w_mm, coupon_h_mm, full_w_px, full_h_px)
            rise = max(0.0, variant["peak_mm"] - variant["valley_mm"])
            fields = [
                variant["name"], source_name, heightmap_name,
                format(variant["peak_mm"], ".6f"), format(variant["valley_mm"], ".6f"), format(rise, ".6f"),
                format(variant["viewing_angle_deg"], ".6f"), format(variant["phase_pitch"], ".6f"),
                _enum_to_profile(variant["profile"]), variant["note"],
            ]
            def csv_escape(value):
                value = str(value)
                return '"' + value.replace('"', '""') + '"'
            handle.write(",".join(csv_escape(v) for v in fields) + "\n")

    settings.calibration_last_folder = str(folder)
    return folder, len(variants), source_path, csv_path


def _lens_cross_section_signature(settings):
    return repr((
        _resolved_local_profile(settings),
        round(float(settings.lpi), 5),
        round(float(settings.thickness_mm), 5),
        round(float(settings.base_mm), 5),
        round(float(settings.phase_pitch), 5),
        int(settings.views),
        round(float(settings.ior), 5),
    ))


def _crop_build_profile_to_periods(settings, points, repeats=3.0):
    """Crop a physical mesh profile to a centered number of real pitch periods."""
    if not points or len(points) < 2:
        return points
    points = sorted(points, key=lambda pair: pair[0])
    pitch_mm = 25.4 / max(0.001, float(settings.lpi))
    desired_span = max(pitch_mm, pitch_mm * max(1.0, float(repeats)))
    x_min = float(points[0][0])
    x_max = float(points[-1][0])
    available_span = max(0.0, x_max - x_min)
    if desired_span >= available_span - 1e-9:
        return points
    center = (x_min + x_max) * 0.5
    left = center - desired_span * 0.5
    right = center + desired_span * 0.5

    def interp_at(x):
        for i in range(len(points) - 1):
            x0, z0 = points[i]
            x1, z1 = points[i + 1]
            if x0 <= x <= x1:
                if abs(x1 - x0) < 1e-12:
                    return float(z0)
                t = (x - x0) / (x1 - x0)
                return float(z0) + (float(z1) - float(z0)) * t
        return float(points[0][1] if x <= x_min else points[-1][1])

    cropped = [(left, interp_at(left))]
    cropped.extend((float(x), float(z)) for x, z in points if left < x < right)
    cropped.append((right, interp_at(right)))
    return cropped if len(cropped) >= 2 else points


def _lens_cross_section_preview_path(settings):
    _validate_theoretical_printability(settings)
    # Preview revision is part of the filename so old distorted cached thumbnails
    # cannot survive an add-on upgrade with otherwise identical settings.
    signature = 'physical_1to1_v2|' + _lens_cross_section_signature(settings)
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    temp_dir = Path(bpy.app.tempdir or os.environ.get("TEMP", ".")) / "lenticular_previews"
    path = temp_dir / ("lens_cross_section_1to1_" + digest + ".png")
    if path.is_file():
        return path

    vertical = settings.orientation == 'VERTICAL'
    object_name = OBJECT_PREFIX + ('DirectionalRelief' if _lens_free_mode(settings) else 'LenticularLens')
    obj = bpy.data.objects.get(object_name)
    points = _mesh_cross_section_points(obj, vertical)
    if not points:
        points = _fallback_build_cross_section_points(settings)
    if not points:
        raise RuntimeError('No generated geometry is available for the cross-section')

    # Three real pitch periods are enough to show the profile while preserving
    # its actual physical width-to-height ratio.
    points = _crop_build_profile_to_periods(settings, points, 3.0)
    _render_sidebar_cross_section(points, path)
    return path


def _draw_lens_cross_section(layout, settings):
    box = layout.box()
    header = box.row(align=True)
    header.prop(
        settings,
        "build_cross_section_expanded",
        text="",
        icon="TRIA_DOWN" if settings.build_cross_section_expanded else "TRIA_RIGHT",
        emboss=False,
    )
    header.label(text=("Relief Cross Section" if _lens_free_mode(settings) else "Lens Cross Section"))
    open_view = header.operator("lenticular.open_cross_section_viewer", text="Open Full View", icon="IMAGE_DATA")
    open_view.source_kind = "BUILD"

    if not settings.build_cross_section_expanded:
        return

    try:
        preview_path = _lens_cross_section_preview_path(settings)
        icon_id = _preview_icon_for_file(preview_path, "cross_section")
        if icon_id:
            row = box.row()
            row.alignment = 'CENTER'
            row.template_icon(icon_value=icon_id, scale=10.0)
        else:
            box.label(text="Cross-section preview unavailable", icon="IMAGE_DATA")
    except Exception as exc:
        box.label(text="Cross-section preview unavailable", icon="IMAGE_DATA")
        box.label(text=str(exc))
    pitch_mm = 25.4 / max(0.001, float(settings.lpi))
    rise_mm = max(0.0, float(settings.thickness_mm) - float(settings.base_mm))
    box.label(text="Preview scale: 1:1 physical X:Z")
    row = box.row(align=True)
    row.label(text="Type: " + _resolved_profile_label(settings))
    row.label(text=f"Pitch: {pitch_mm:.3f} mm")
    row = box.row(align=True)
    row.label(text=f"Base: {settings.base_mm:.3f} mm")
    row.label(text=f"Rise: {rise_mm:.3f} mm")
    row = box.row(align=True)
    row.label(text=f"Peak: {settings.thickness_mm:.3f} mm")
    row.label(text=f"LPI: {settings.lpi:.3f}")

def _build_lens_mesh(collection, surface_values, width_m, height_m, peak_m, base_m, vertical, smooth_top=True, object_name=None):
    n = max(2, len(surface_values))
    verts = []
    faces = []
    rise_m = max(0.0, peak_m - base_m)
    if vertical:
        for i, value in enumerate(surface_values):
            x = -width_m / 2.0 + width_m * i / (n - 1)
            z = base_m + value * rise_m
            verts.extend([(x, -height_m / 2.0, z), (x, height_m / 2.0, z), (x, -height_m / 2.0, 0.0), (x, height_m / 2.0, 0.0)])
    else:
        for i, value in enumerate(surface_values):
            y = -height_m / 2.0 + height_m * i / (n - 1)
            z = base_m + value * rise_m
            verts.extend([(-width_m / 2.0, y, z), (width_m / 2.0, y, z), (-width_m / 2.0, y, 0.0), (width_m / 2.0, y, 0.0)])
    for i in range(n - 1):
        a = i * 4
        b = (i + 1) * 4
        if vertical:
            # Axis advances along +X. These windings keep the optical top surface
            # facing local +Z, the backing surface facing -Z, and the side walls
            # facing outward.
            faces.append((a, b, b + 1, a + 1))
            faces.append((a + 2, a + 3, b + 3, b + 2))
            faces.append((a, a + 2, b + 2, b))
            faces.append((a + 1, b + 1, b + 3, a + 3))
        else:
            # Axis advances along +Y. Reusing the vertical winding reverses every
            # major surface normal in this orientation, which makes the refractive
            # material behave as though the viewer were looking through backfaces.
            # Use the transposed winding so the top still faces local +Z.
            faces.append((a, a + 1, b + 1, b))
            faces.append((a + 2, b + 2, b + 3, a + 3))
            faces.append((a, b, b + 2, a + 2))
            faces.append((a + 1, a + 3, b + 3, b + 1))
    if vertical:
        faces.append((0, 1, 3, 2))
        end = (n - 1) * 4
        faces.append((end, end + 2, end + 3, end + 1))
    else:
        # End caps also need orientation-specific winding after transposing X/Y.
        faces.append((0, 2, 3, 1))
        end = (n - 1) * 4
        faces.append((end, end + 1, end + 3, end + 2))
    mesh = bpy.data.meshes.new(OBJECT_PREFIX + "LensMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(object_name or (OBJECT_PREFIX + "LenticularLens"), mesh)
    collection.objects.link(obj)
    top_face_count = n - 1
    for index, polygon in enumerate(mesh.polygons):
        polygon.use_smooth = bool(smooth_top and index < top_face_count * 4 and (index % 4 == 0))
    # Planar UVs keep the generated interlaced raster phase-locked to the relief facets.
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            co = mesh.vertices[vertex_index].co
            u = (co.x + width_m * 0.5) / max(width_m, 1e-12)
            v = (co.y + height_m * 0.5) / max(height_m, 1e-12)
            uv_layer.data[loop_index].uv = (u, v)
    return obj


def _apply_planar_image_uv(obj, width_m, height_m):
    # Direct 0..1 planar mapping. Relief phase alignment is defined by the same
    # physical coordinate origin used to generate the facet profile and color
    # stripes, so no texture-coordinate offset is needed.
    mesh = obj.data
    uv_layer = mesh.uv_layers.get("UVMap") or mesh.uv_layers.new(name="UVMap")
    half_w = max(1e-12, width_m * 0.5)
    half_h = max(1e-12, height_m * 0.5)
    for poly in mesh.polygons:
        for loop_index in poly.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            co = mesh.vertices[vertex_index].co
            u = (co.x + half_w) / (2.0 * half_w)
            v = (co.y + half_h) / (2.0 * half_h)
            uv_layer.data[loop_index].uv = (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))
    mesh.update()


def _material_by_name(name):
    material = bpy.data.materials.get(name)
    if material is None:
        material = bpy.data.materials.new(name)
    material.use_nodes = True
    return material


def _make_materials(interlaced_image, settings):
    # Optical goal:
    # - Keep the lens on Refraction BSDF so lenticular refraction still works.
    # - Make the image itself purely emissive so lighting cannot blow it out.
    # - Keep the backing matte and non-reflective.
    substrate_mat = _material_by_name(OBJECT_PREFIX + "SubstrateMat")
    _ensure_diffuse_material(substrate_mat, (0.9, 0.9, 0.9, 1.0), 0.0)

    print_mat = _material_by_name(OBJECT_PREFIX + "PrintMat")
    print_nodes = print_mat.node_tree.nodes
    for node in list(print_nodes):
        if node.type == "TEX_IMAGE" and node.name.startswith("LenticulizerImageTexture"):
            print_nodes.remove(node)
    tex = print_nodes.new("ShaderNodeTexImage")
    tex.name = "LenticulizerImageTexture"
    tex.label = "Lenticulizer Image Texture"
    tex.image = interlaced_image
    _ensure_emission_material(print_mat, tex, 1.0)

    lens_mat = _material_by_name(OBJECT_PREFIX + "LensMat")
    _ensure_refraction_lens_material(settings, lens_mat)
    _configure_resin_material(settings, lens_mat)

    return substrate_mat, print_mat, lens_mat


def _add_camera(collection, angle_deg, distance_m, target, vertical, peak_m, name):
    angle = math.radians(angle_deg)
    lateral = math.sin(angle) * distance_m
    depth = math.cos(angle) * distance_m + peak_m * 0.5
    # Generated print uses the supplied reference scene convention: printed front faces +Y.
    # Vertical stripes sweep left/right across X; horizontal stripes
    # sweep down/up across Z.
    location = (lateral, depth, 0.0) if vertical else (0.0, depth, lateral)
    bpy.ops.object.camera_add(location=location)
    cam = bpy.context.active_object
    cam.name = name
    cam["lenticular_angle_deg"] = float(angle_deg)
    cam["lenticular_view_camera"] = True
    _move_to_collection(cam, collection)
    cam.data.lens = 50.0
    constraint = cam.constraints.new(type="TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"
    return cam


def _add_lights(collection, width_m, height_m, peak_m, settings):
    for index in range(2):
        bpy.ops.object.light_add(type="AREA", location=(0.0, 0.0, 1.0))
        light = bpy.context.active_object
        light.name = OBJECT_PREFIX + "AreaLight" + str(index + 1)
        _move_to_collection(light, collection)
    _position_area_lights(settings)


def _rebuild_scene(context, project=None):
    scene = context.scene
    settings = scene.lenticular_sync
    _apply_local_optical_rules(settings)
    _validate_theoretical_printability(settings)
    if project is None and settings.workflow != "HEIGHTMAP":
        path = _project_path(settings)
        if path and path.is_file():
            project = _load_json(path)
    if project is not None:
        image_path = _resolve_asset(project, "interlaced_image", settings)
    else:
        image_path = _resolve_project_relative(settings, settings.interlaced_image)
    if not image_path or not image_path.is_file():
        raise RuntimeError("Interlaced image not found")

    width_m = settings.width_mm / 1000.0
    height_m = settings.height_mm / 1000.0
    peak_m = settings.thickness_mm / 1000.0
    base_m = min(settings.base_mm, settings.thickness_mm) / 1000.0
    if _lens_free_mode(settings) and settings.workflow != "HEIGHTMAP":
        _, relief_base_mm, relief_rise_mm, relief_peak_mm = _relief_required_geometry(settings)
        peak_m = relief_peak_mm / 1000.0
        base_m = relief_base_mm / 1000.0
    if settings.workflow == "HEIGHTMAP":
        peak_m = settings.reference_heightmap_thickness_mm / 1000.0
        base_m = 0.0
    backing_m = _effective_backing_mm(settings) / 1000.0
    vertical = settings.orientation == "VERTICAL"

    collection = _new_sim_collection(scene)
    interlaced_image = bpy.data.images.load(str(image_path), check_existing=True)
    try:
        interlaced_image.reload()
    except Exception:
        pass
    surface = _surface_from_settings(settings)
    substrate_mat, print_mat, lens_mat = _make_materials(interlaced_image, settings)

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 0.0, 0.0))
    print_root = bpy.context.active_object
    print_root.name = OBJECT_PREFIX + "PrintRoot"
    print_root.rotation_mode = "XYZ"
    # Canonical Blender presentation from the supplied reference scene.
    # Local +Z is the printed front; -90 degrees around X makes the front face +Y.
    print_root.rotation_euler[0] = -math.pi / 2.0
    print_root.rotation_euler[1] = math.pi
    print_root.rotation_euler[2] = 0.0
    bpy.context.view_layer.update()
    print_root["lenticulizer_upright_root"] = True
    _move_to_collection(print_root, collection)

    _sync_backing_object(settings)

    if _lens_free_mode(settings):
        relief = _build_lens_mesh(
            collection, surface, width_m, height_m, peak_m, base_m, vertical,
            smooth_top=False, object_name=OBJECT_PREFIX + "DirectionalRelief"
        )
        relief.data.materials.append(print_mat)
        _apply_planar_image_uv(relief, width_m, height_m)
        relief["lenticulizer_output_mode"] = "Lens-Free Relief"
        relief["lenticulizer_prism_height_mm"] = float(_relief_prism_height_mm(settings))
        relief["lenticulizer_views"] = int(settings.views)
        relief["lenticulizer_lpi"] = float(settings.lpi)
        relief.parent = print_root
    else:
        bpy.ops.mesh.primitive_plane_add(location=(0.0, 0.0, 0.000001))
        print_plane = bpy.context.active_object
        print_plane.name = OBJECT_PREFIX + "InterlacedImage"
        print_plane.scale = (width_m / 2.0, height_m / 2.0, 1.0)
        _move_to_collection(print_plane, collection)
        print_plane.data.materials.append(print_mat)
        print_plane.parent = print_root

        lens = _build_lens_mesh(collection, surface, width_m, height_m, peak_m, base_m, vertical)
        lens.data.materials.append(lens_mat)
        lens.parent = print_root

    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, peak_m * 0.45, 0.0))
    target = bpy.context.active_object
    target.name = OBJECT_PREFIX + "ViewTarget"
    _move_to_collection(target, collection)

    distance_m = max(width_m, height_m) * 1.8 + max(backing_m, peak_m) * 15.0
    if _lens_free_mode(settings):
        angles = _relief_facet_angles(settings)
    else:
        angle_total = max(1.0, settings.viewing_angle_deg)
        start = -angle_total / 2.0
        if settings.views <= 1:
            angles = [0.0]
        else:
            step = angle_total / max(1, settings.views - 1)
            angles = [start + step * i for i in range(settings.views)]
    cameras = []
    for idx, angle in enumerate(angles):
        position = _camera_position_label(idx, len(angles), vertical)
        name = OBJECT_PREFIX + position.replace(" ", "_")
        cameras.append(_add_camera(collection, angle, distance_m, target, vertical, peak_m, name))
    if cameras:
        scene.camera = min(cameras, key=lambda cam: abs(float(cam.get("lenticular_angle_deg", 0.0))))
        settings.active_camera_name = scene.camera.name

    _add_lights(collection, width_m, height_m, peak_m, settings)
    try:
        bpy.ops.object.select_all(action="DESELECT")
        print_root.select_set(True)
        context.view_layer.objects.active = print_root
    except Exception:
        pass
    scene.render.engine = "CYCLES"
    scene.render.resolution_x = settings.render_width
    scene.render.resolution_y = settings.render_height
    if hasattr(scene, "cycles"):
        scene.cycles.samples = settings.render_samples
        if hasattr(scene.cycles, "max_bounces"):
            scene.cycles.max_bounces = 12
        if hasattr(scene.cycles, "transmission_bounces"):
            scene.cycles.transmission_bounces = 8
        if hasattr(scene.cycles, "caustics_reflective"):
            scene.cycles.caustics_reflective = False
        if hasattr(scene.cycles, "caustics_refractive"):
            scene.cycles.caustics_refractive = False
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "MILLIMETERS"
    scene.unit_settings.scale_length = 1.0
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.04, 0.04, 0.04, 1.0)
        bg.inputs[1].default_value = 0.005
    path = _project_path(settings)
    if path:
        scene["lenticular_project_file"] = str(path)
    settings.rise_mm = max(0.0, settings.thickness_mm - settings.base_mm)
    _set_status(settings, "Scene rebuilt from synced settings")
    _schedule_inspection_viewer_fit()


def _project_needs_scene_rebuild(settings, project):
    data = project.get("settings", {}) if isinstance(project, dict) else {}
    assets = project.get("assets", {}) if isinstance(project, dict) else {}

    def different_number(key, current, tolerance=1.0e-6):
        return abs(_safe_float(data.get(key), current) - float(current)) > tolerance

    if different_number("width_mm", settings.width_mm):
        return True
    if different_number("height_mm", settings.height_mm):
        return True
    if different_number("lpi", settings.lpi):
        return True
    incoming_output = str(data.get("output_mode", "Lenticular Lens")).lower()
    incoming_output = "RELIEF" if "relief" in incoming_output else "LENTICULAR"
    if incoming_output != settings.output_mode:
        return True
    if incoming_output == "RELIEF" and different_number("relief_prism_height_mm", settings.relief_prism_height_mm):
        return True
    incoming_workflow_text = str(data.get("workflow", "Build from source frames")).lower()
    incoming_workflow = "HEIGHTMAP" if "heightmap" in incoming_workflow_text else "EXISTING_INTERLACED" if "existing" in incoming_workflow_text else "SOURCE_FRAMES"
    if incoming_workflow != settings.workflow:
        return True
    if incoming_workflow == "HEIGHTMAP":
        if str(assets.get("reference_heightmap", "")) != settings.reference_heightmap_path: return True
        for key in ("reference_heightmap_width_mm", "reference_heightmap_height_mm", "reference_heightmap_thickness_mm", "reference_heightmap_pitch_px", "reference_heightmap_phase_pitch"):
            if different_number(key, getattr(settings,key)): return True
        if project.get("reference_heightmap_info", {}) != _reference_info(settings): return True
    incoming_helper_text = str(data.get("lpi_helper_mode", "Manual")).lower()
    incoming_helper = "RECOMMENDED" if incoming_helper_text.startswith("recommend") else "MANUAL"
    if incoming_helper != settings.lpi_helper_mode:
        return True
    incoming_preset_text = str(data.get("lpi_helper_preset", "Balanced")).upper()
    incoming_preset = "EASIER" if incoming_preset_text.startswith("EAS") else ("FINER" if incoming_preset_text.startswith("FIN") else "BALANCED")
    if incoming_preset != settings.lpi_helper_preset:
        return True
    if _safe_int(data.get("views"), settings.views) != int(settings.views):
        return True

    incoming_orientation = str(data.get("orientation", "Vertical")).lower()
    incoming_orientation = "HORIZONTAL" if incoming_orientation.startswith("h") else "VERTICAL"
    if incoming_orientation != settings.orientation:
        return True

    incoming_profile = _profile_to_enum(str(data.get("lens_profile", _enum_to_profile(settings.lens_profile))))
    if incoming_profile != settings.lens_profile:
        return True

    # IOR is part of the theoretical surface equation, so it must rebuild the lens
    # even when the resolved peak/base numbers do not change enough to trip the
    # dimensional checks below.
    if different_number("ior", settings.ior):
        return True

    incoming_mode = str(data.get("mode", "Automatic")).lower()
    incoming_mode = "MANUAL" if incoming_mode.startswith("manual") else ("SEMI" if incoming_mode.startswith("semi") else "AUTOMATIC")
    if incoming_mode != settings.settings_mode:
        return True

    incoming_print = str(data.get("print_profile", "")).strip().lower()
    if incoming_print:
        if "mathemat" in incoming_print or "theoret" in incoming_print:
            incoming_print_enum = "THEORETICAL"
        elif "lower" in incoming_print:
            incoming_print_enum = "LOWER"
        elif "higher" in incoming_print:
            incoming_print_enum = "HIGHER"
        elif "manual" in incoming_print:
            incoming_print_enum = "MANUAL"
        else:
            incoming_print_enum = "RECOMMENDED"
        if incoming_print_enum != settings.print_profile:
            return True

    incoming_base = str(data.get("base_mode", "")).strip().lower()
    if incoming_base:
        if "mathemat" in incoming_base or "theoret" in incoming_base:
            incoming_base_enum = "THEORETICAL"
        elif "no base" in incoming_base or incoming_base in {"none", "no_base"}:
            incoming_base_enum = "NONE"
        elif "minimum" in incoming_base:
            incoming_base_enum = "MINIMUM"
        elif "raised" in incoming_base:
            incoming_base_enum = "RAISED"
        elif "manual" in incoming_base:
            incoming_base_enum = "MANUAL"
        else:
            incoming_base_enum = "RECOMMENDED"
        if incoming_base_enum != settings.base_mode:
            return True

    if different_number("manual_thickness_mm", _manual_thickness_mm(settings)):
        return True
    if different_number("manual_base_mm", settings.manual_base_mm):
        return True

    # Auto Recommended can change surface family as raster detail changes.
    incoming_dpi = _safe_int(data.get("printer_dpi"), settings.printer_dpi)
    if incoming_dpi != int(settings.printer_dpi):
        return True
    incoming_build_mode = str(data.get("build_detail_mode", settings.build_detail_mode)).upper().replace("-", "_").replace(" ", "_")
    incoming_build_mode = {"AUTO_FROM_PRINTER_DPI":"RECOMMENDED", "AUTO":"RECOMMENDED", "QUICK_DRAFT":"QUICK", "FINE_DETAIL":"FINE"}.get(incoming_build_mode, incoming_build_mode)
    if incoming_build_mode != settings.build_detail_mode:
        return True
    incoming_ppl = _safe_int(data.get("pixels_per_lenticule"), settings.pixels_per_lenticule)
    current_ppl = int(_recommended_pixels_per_lenticule(settings) if settings.build_detail_mode != "CUSTOM" else settings.pixels_per_lenticule)
    if incoming_ppl != current_ppl:
        return True

    if different_number("thickness_mm", settings.thickness_mm):
        return True
    if different_number("base_mm", settings.base_mm):
        return True
    if different_number("phase_pitch", settings.phase_pitch):
        return True

    current_interlaced = str(settings.interlaced_image or "")
    incoming_interlaced = str(assets.get("interlaced_image", current_interlaced) or "")
    if incoming_interlaced != current_interlaced:
        return True

    # A changed height/depth-map asset path does not require rebuilding the Blender
    # scene. The scene is generated from optical settings and the color/interlaced
    # image. Treating the derived map path as geometry caused unnecessary sync
    # rebuilds when the Windows app and Blender used different working-map locations.
    return False


def _apply_live_non_geometry_settings(settings):
    _configure_resin_material(settings)
    _update_light_power(settings, bpy.context)
    _position_area_lights(settings)
    _update_backing_live_from_sync(settings)
    _update_camera_layout(settings, bpy.context)


def _update_backing_live_from_sync(settings):
    _sync_backing_object(settings)



def _auto_heightmap_path(settings):
    folder = _workspace_dir(settings)
    if folder is None:
        return None
    if settings.workflow == "HEIGHTMAP":
        return folder / ("heightmap_imported_" + uuid.uuid4().hex + Path(settings.reference_heightmap_path).suffix.lower())
    output = folder / ("depthmap16_autogenerated.png" if _lens_free_mode(settings) else "heightmap16_autogenerated.png")
    source = _resolve_preview_path(settings, settings.reference_heightmap_path)
    if source and output.resolve() == source.resolve(): output = folder / ("heightmap_"+uuid.uuid4().hex+".png")
    return output


def _generate_working_heightmap(settings):
    image_path = _resolve_project_relative(settings, settings.interlaced_image)
    if image_path is None or not image_path.is_file():
        raise RuntimeError("Automatic heightmap is waiting for a valid interlaced/color image")
    output_path = _auto_heightmap_path(settings)
    if output_path is None:
        raise RuntimeError("Could not create a working folder for the automatic heightmap")
    output_path = _generate_heightmap_file(settings, output_path)
    settings.heightmap_image = _project_relative_path(settings, output_path)
    return output_path


def _process_reactive_updates(context):
    # Output Mode has a dedicated first-pass timer. Until it consumes the request,
    # the ordinary reactive worker must not clear or partially process that request.
    if _state.get("mode_rebuild_timer_registered", False):
        return
    if _state.get("reactive_busy", False) or _state.get("applying", False) or not _state.get("dirty", False):
        return
    if time.time() - float(_state.get("last_change_time", 0.0)) < 0.30:
        return
    settings = context.scene.lenticular_sync
    reactive_origin = str(_state.get("reactive_origin", "local") or "local")
    _state["reactive_busy"] = True
    try:
        rebuilt_any = False
        status_parts = []
        upstream_valid = True

        # Interlace is the only hard upstream asset dependency for the scene.
        # Build it first when required so the texture and relief polarity are current.
        if _state.get("pending_interlace", False) and settings.auto_rebuild and settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
            frame_count = len(_source_frame_paths(settings))
            required_ok = frame_count >= 2 and (not _lens_free_mode(settings) or frame_count == _relief_supported_view_count())
            if required_ok:
                try:
                    out_path, out_w, out_h, ppl = _build_interlaced_image(settings)
                    rebuilt_any = True
                    _state["pending_interlace"] = False
                    _state["pending_heightmap"] = True
                    _state["pending_lens"] = True
                    _state["pending_texture"] = True
                    status_parts.append(f"Auto interlace {out_w}x{out_h}")
                except Exception as exc:
                    upstream_valid = False
                    status_parts.append("Interlace rebuild blocked: " + str(exc))
            else:
                upstream_valid = False
                if _lens_free_mode(settings):
                    status_parts.append(f"Lens-Free Relief requires exactly {_relief_supported_view_count()} source images; found {frame_count}")
                else:
                    status_parts.append("Add at least 2 source images for automatic interlacing")

        # Rebuild the visible Blender model immediately after the authoritative
        # interlaced image is ready.  The model is generated directly from the
        # optical/profile settings and does not consume the PNG heightmap, so a
        # full-resolution heightmap write must not block interactive geometry.
        model_rebuilt = False
        if _state.get("pending_lens", False) and settings.auto_rebuild and upstream_valid:
            image_path = _resolve_project_relative(settings, settings.interlaced_image)
            if image_path is not None and image_path.is_file():
                try:
                    _rebuild_scene(context)
                    context.view_layer.update()
                    rebuilt_any = True
                    model_rebuilt = True
                    _state["pending_lens"] = False
                    _state["pending_texture"] = False
                    status_parts.append("3D model rebuilt")
                except Exception as exc:
                    status_parts.append("3D rebuild blocked: " + str(exc))
            else:
                upstream_valid = False
                status_parts.append("3D rebuild waiting for a valid mode-matched interlaced image")
        elif _state.get("pending_texture", False) and upstream_valid:
            _apply_live_non_geometry_settings(settings)
            _state["pending_texture"] = False
            rebuilt_any = True

        # Full-resolution 16-bit height/depth-map output is intentionally moved
        # to a later timer pass when a model just rebuilt.  This keeps sliders and
        # field edits responsive while still guaranteeing automatic final output.
        if _state.get("pending_heightmap", False) and settings.auto_rebuild and upstream_valid:
            now = time.time()
            due = float(_state.get("heightmap_due_time", 0.0) or 0.0)
            if model_rebuilt:
                _state["heightmap_due_time"] = now + 0.20
                status_parts.append("height/depth map queued")
            elif now >= due:
                image_path = _resolve_project_relative(settings, settings.interlaced_image)
                if image_path is not None and image_path.is_file():
                    try:
                        heightmap_path = _generate_working_heightmap(settings)
                        rebuilt_any = True
                        _state["pending_heightmap"] = False
                        _state["heightmap_due_time"] = 0.0
                        status_parts.append("Auto " + ("depth map" if _lens_free_mode(settings) else "heightmap") + " " + heightmap_path.name)
                    except Exception as exc:
                        status_parts.append("Height/depth-map rebuild blocked: " + str(exc))
                else:
                    status_parts.append("Height/depth map waiting for a valid mode-matched interlaced image")

        if status_parts:
            _set_status(settings, " | ".join(status_parts))

        work_pending = bool(
            _state.get("pending_interlace", False)
            or _state.get("pending_heightmap", False)
            or _state.get("pending_lens", False)
            or _state.get("pending_texture", False)
        )

        # Publish only after the dependency transaction is complete.  While a
        # deferred heightmap is pending, keep the project dirty but do not send a
        # new revision containing a stale generated asset.
        if not work_pending:
            # An output-mode change is complete only when the newly authoritative
            # interlaced/color image, model, and deferred height/depth map have all
            # finished.
            _state["mode_transaction_active"] = False

            # Do not echo a project revision back to the side that just supplied it.
            # App-originated and startup rebuilds are local scene refreshes only.
            # Local Blender edits remain authoritative and are published normally.
            if reactive_origin in {"app", "startup"}:
                _state["dirty"] = False
                _state["dirty_scope"] = "geometry"
            elif settings.auto_sync and _project_path(settings):
                _send_to_app(context, quiet=True)
            elif rebuilt_any:
                _state["dirty"] = False
                _state["dirty_scope"] = "geometry"
            _state["reactive_origin"] = "local"
        else:
            _state["dirty"] = True
    except Exception as exc:
        _set_status(settings, "Live rebuild failed: " + str(exc))
        _state["pending_interlace"] = False
        _state["pending_heightmap"] = False
        _state["pending_lens"] = False
        _state["pending_texture"] = False
        _state["heightmap_due_time"] = 0.0
        _state["mode_transaction_active"] = False
        if reactive_origin in {"app", "startup"}:
            _state["dirty"] = False
            _state["dirty_scope"] = "geometry"
        _state["reactive_origin"] = "local"
    finally:
        _state["reactive_busy"] = False



def _refresh_viewport_selector_if_layout_changed():
    """Redraw 3D sidebars when the set/order of open 3D viewports changes."""
    try:
        wm = bpy.context.window_manager
        signatures = []
        for window in wm.windows:
            screen = window.screen
            areas = [a for a in screen.areas if a.type == "VIEW_3D" and _view3d_window_region(a) is not None]
            areas.sort(key=lambda a: (-int(a.y), int(a.x)))
            signatures.append((window.as_pointer(), tuple((a.as_pointer(), int(a.x), int(a.y), int(a.width), int(a.height)) for a in areas)))
        signature = tuple(signatures)
        if signature == _state.get("viewport_layout_signature"):
            return
        _state["viewport_layout_signature"] = signature
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    try:
                        area.tag_redraw()
                    except Exception:
                        pass
    except Exception:
        pass


def _timer_callback():
    try:
        _refresh_viewport_selector_if_layout_changed()
        if not hasattr(bpy.context.scene, "lenticular_sync"):
            return _SYNC_INTERVAL
        settings = bpy.context.scene.lenticular_sync

        try:
            _sync_dedicated_image_editors(bpy.context)
            _sync_reference_preview(bpy.context)
        except Exception:
            pass

        # Upgrade an older LT_LensMat only when a migration is actually needed.
        # v1.18.21 rewired Material Output.Surface on every 250 ms timer tick,
        # which invalidated the Cycles shader graph and continuously restarted
        # the rendered viewport. The normal steady-state path below is read-only.
        try:
            if _generated_materials_need_display_migration():
                _ensure_all_generated_display_materials(settings)
        except Exception as exc:
            print("Lenticulizer generated material migration error:", exc)

        if not _state.get("optics_initialized", False):
            _state["optics_initialized"] = True
            if settings.settings_mode in {"AUTOMATIC", "SEMI"}:
                _apply_local_optical_rules(settings)
                image_path = _resolve_project_relative(settings, settings.interlaced_image)
                if settings.auto_rebuild and image_path is not None and image_path.is_file():
                    _state["pending_heightmap"] = True
                    _state["pending_lens"] = True
                    _state["dirty"] = True
                    _state["reactive_origin"] = "startup"
                    _state["last_change_time"] = 0.0

        # Local image/lens updates always run, even when Blender is being used completely standalone.
        _process_reactive_updates(bpy.context)

        # A local output-mode switch is an atomic dependency transaction. The normal
        # reactive pass above is the only rebuild scheduler. While valid source/image
        # prerequisites exist and generated work is still pending, do not pull an older
        # project.json revision that could restore the previous mode before the first
        # rebuild completes. If prerequisites are not valid, release the sync hold so
        # the app can still supply missing project data.
        if _state.get("mode_transaction_active", False):
            pending_mode_work = bool(
                _state.get("pending_interlace", False)
                or _state.get("pending_heightmap", False)
                or _state.get("pending_lens", False)
                or _state.get("pending_texture", False)
            )
            if not pending_mode_work:
                _state["mode_transaction_active"] = False
            elif _output_mode_rebuild_prerequisites_ready(settings):
                return _SYNC_INTERVAL
            else:
                _state["mode_transaction_active"] = False

        # Do not auto-load a remembered project on ordinary Blender startup.
        # Only a fresh one-time handoff written by the Windows app may auto-connect.
        if not _state.get("session_connected", False):
            handoff = _consume_pending_project_handoff()
            if handoff:
                _state["applying"] = True
                try:
                    settings.project_file = str(handoff)
                    bpy.context.scene["lenticular_project_file"] = str(handoff)
                finally:
                    _state["applying"] = False
                _state["session_connected"] = True
                _pull_from_app(bpy.context, rebuild=settings.auto_rebuild, quiet=True)
                _set_status(settings, "Connected from Windows app handoff")
                return _SYNC_INTERVAL
            return _SYNC_INTERVAL

        path = _project_path(settings)
        if path and path.is_file():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            try:
                # Revision is the primary sync clock. Timestamp remains a fallback for
                # compatibility with older app builds that may not advance revision.
                project = _load_json(path)
                revision = _safe_int(project.get("revision"), 0)
                changed_by = str(project.get("changed_by", ""))
                incoming_changed = revision > _state["last_revision"] or mtime > _state["last_mtime"] + 1e-6
                if incoming_changed:
                    if changed_by != "blender":
                        needs_rebuild = _project_needs_scene_rebuild(settings, project)
                        _apply_project_to_settings(settings, project)
                        _set_status(settings, "Updated by app")
                        if settings.auto_rebuild and needs_rebuild:
                            _state["dirty"] = True
                            _state["reactive_origin"] = "app"
                            _state["last_change_time"] = 0.0

                            # The Windows app normally publishes a completed color/interlaced
                            # image together with its settings revision. Reuse that authoritative
                            # asset instead of regenerating the same source frames in Blender.
                            # Only build locally when the incoming project has no valid image.
                            incoming_image = _resolve_project_relative(settings, settings.interlaced_image)
                            have_incoming_image = bool(incoming_image is not None and incoming_image.is_file())
                            if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"} and len(_source_frame_paths(settings)) >= 2 and not have_incoming_image:
                                _state["pending_interlace"] = True
                            else:
                                _state["pending_interlace"] = False

                            incoming_heightmap = _resolve_project_relative(settings, settings.heightmap_image)
                            have_incoming_heightmap = bool(incoming_heightmap is not None and incoming_heightmap.is_file())
                            _state["pending_heightmap"] = not have_incoming_heightmap
                            _state["pending_lens"] = True
                            _state["pending_texture"] = True
                        else:
                            _apply_live_non_geometry_settings(settings)
                    else:
                        _state["last_revision"] = max(_state["last_revision"], revision)
                        _state["last_mtime"] = max(_state["last_mtime"], mtime)
            except Exception as exc:
                _set_status(settings, "Sync read failed: " + str(exc))

        pending_build_work = bool(
            _state.get("pending_interlace", False)
            or _state.get("pending_heightmap", False)
            or _state.get("pending_lens", False)
            or _state.get("pending_texture", False)
        )
        if settings.auto_sync and _state["dirty"] and not pending_build_work and time.time() - _state["last_change_time"] >= 0.35:
            _send_to_app(bpy.context, quiet=True)
    except Exception as exc:
        print("Lenticulizer sync timer error:", exc)
    return _SYNC_INTERVAL


def _source_frame_position_label(index, count, vertical=True):
    if count <= 1:
        return "View"
    if vertical:
        if count == 2:
            return ["Left", "Right"][index]
        if count == 3:
            return ["Left", "Center", "Right"][index]
        if count == 4:
            return ["Far Left", "Center Left", "Center Right", "Far Right"][index]
        if count == 5:
            return ["Far Left", "Left", "Center", "Right", "Far Right"][index]
        midpoint = (count - 1) / 2.0
        if abs(index - midpoint) < 0.25:
            return "Center"
        return ("Far Left" if index == 0 else "Left") if index < midpoint else ("Far Right" if index == count - 1 else "Right")
    else:
        if count == 2:
            return ["Top", "Bottom"][index]
        if count == 3:
            return ["Top", "Center", "Bottom"][index]
        if count == 4:
            return ["Far Top", "Center Top", "Center Bottom", "Far Bottom"][index]
        if count == 5:
            return ["Far Top", "Top", "Center", "Bottom", "Far Bottom"][index]
        if count == 6:
            return ["Far Top", "Top", "Center Top", "Center Bottom", "Bottom", "Far Bottom"][index]
        if count == 7:
            return ["Far Top", "Top", "Center Top", "Center", "Center Bottom", "Bottom", "Far Bottom"][index]
        if count == 8:
            return ["Far Top", "Top", "Center Top", "Slight Top", "Slight Bottom", "Center Bottom", "Bottom", "Far Bottom"][index]
        midpoint = (count - 1) / 2.0
        if abs(index - midpoint) < 0.25:
            return "Center"
        return ("Far Top" if index == 0 else "Top") if index < midpoint else ("Far Bottom" if index == count - 1 else "Bottom")


class LENTICULAR_UL_source_frames(UIList):
    bl_idname = "LENTICULAR_UL_source_frames"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        vertical = getattr(data, "orientation", "VERTICAL") == "VERTICAL"
        slot = _source_frame_position_label(index, len(data.source_frames), vertical)
        icon_id = _image_icon_id(data, item.path)

        # GRID mode makes the thumbnail itself the native Blender selection target.
        # There is no separate thin selector strip or side button.
        if self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            if icon_id:
                try:
                    layout.template_icon(icon_value=icon_id, scale=2.35)
                except Exception:
                    layout.label(text="", icon_value=icon_id)
            else:
                layout.label(text="", icon="IMAGE_DATA")
            return

        # Fallback list rendering for unusual Blender layouts.
        row = layout.row(align=True)
        if icon_id:
            row.label(text=slot, icon_value=icon_id)
        else:
            row.label(text=slot, icon="IMAGE_DATA")
        row.label(text=item.display_name or Path(item.path).name)



def _mesh_cross_section_points(obj, vertical):
    """Return the actual top-surface mesh profile as physical (axis_mm, z_mm) points."""
    if obj is None or obj.type != 'MESH' or obj.data is None:
        return []
    verts = obj.data.vertices
    if len(verts) < 4:
        return []
    points = []
    matrix = obj.matrix_world
    use_local = obj.parent is not None and obj.parent.name == OBJECT_PREFIX + "PrintRoot"
    # _build_lens_mesh stores 4 vertices per profile sample. Vertex 0 in each
    # group is one of the two identical top-surface vertices. Generated print-root
    # children are rotated upright as a group, so the physical profile is read from
    # their local pre-rotation X/Z or Y/Z coordinates.
    for index in range(0, len(verts), 4):
        try:
            co = verts[index].co.copy() if use_local else (matrix @ verts[index].co)
            axis_m = float(co.x if vertical else co.y)
            points.append((axis_m * 1000.0, float(co.z) * 1000.0))
        except Exception:
            continue
    points.sort(key=lambda pair: pair[0])
    return points


def _fallback_build_cross_section_points(settings):
    vertical = settings.orientation == 'VERTICAL'
    axis_mm = float(settings.width_mm if vertical else settings.height_mm)
    axis_mm = max(0.000001, axis_mm)
    surface = _surface_from_settings(settings)
    peak_mm = max(0.000001, float(settings.thickness_mm))
    base_mm = max(0.0, min(peak_mm, float(settings.base_mm)))
    rise_mm = max(0.0, peak_mm - base_mm)
    count = max(2, len(surface))
    points = []
    for i, value in enumerate(surface):
        axis = -axis_mm * 0.5 + axis_mm * (i / float(count - 1))
        z = base_mm + max(0.0, min(1.0, float(value))) * rise_mm
        points.append((axis, z))
    return points


def _fallback_reference_cross_section_points(settings):
    source_path = _resolve_preview_path(settings, settings.reference_heightmap_path)
    if source_path is None or not source_path.is_file():
        return []
    vertical = settings.reference_heightmap_orientation == 'VERTICAL'
    source_w, source_h, values = _load_axis_values(source_path, vertical)
    if not values:
        return []
    axis_mm = float(settings.reference_heightmap_width_mm if vertical else settings.reference_heightmap_height_mm)
    axis_mm = max(0.000001, axis_mm)
    peak_mm = max(0.000001, float(settings.reference_heightmap_thickness_mm))
    count = max(2, len(values))
    return [
        (-axis_mm * 0.5 + axis_mm * (i / float(count - 1)), max(0.0, min(1.0, float(v))) * peak_mm)
        for i, v in enumerate(values)
    ]


def _crop_reference_profile_to_selected_span(settings, points):
    if not points:
        return points
    span_mode = str(getattr(settings, 'reference_cross_section_span', '12') or '12')
    if span_mode == 'FULL':
        return points
    try:
        lenticules = max(1, int(span_mode))
    except Exception:
        lenticules = 12
    lpi = max(0.001, float(getattr(settings, 'lpi', 1.0)))
    span_mm = lenticules * (25.4 / lpi)
    axis_min = points[0][0]
    axis_max = points[-1][0]
    center = (axis_min + axis_max) * 0.5
    half = span_mm * 0.5
    cropped = [point for point in points if center - half <= point[0] <= center + half]
    return cropped if len(cropped) >= 2 else points


def _render_sidebar_cross_section(points, output_path):
    """Render a square sidebar image with exact 1:1 physical X:Z scale."""
    if not points or len(points) < 2:
        raise RuntimeError('Cross-section profile has too few points')
    points = sorted(points, key=lambda pair: pair[0])
    x_values = [float(p[0]) for p in points]
    z_values = [float(p[1]) for p in points]
    x_min, x_max = min(x_values), max(x_values)
    z_min = min(0.0, min(z_values))
    z_max = max(z_values)
    x_span = max(0.000001, x_max - x_min)
    z_span = max(0.000001, z_max - z_min)

    # Blender's template_icon may fit the source image into a square UI slot.
    # Supplying a square bitmap prevents independent X/Y rescaling. Geometry is
    # then drawn with exactly one shared pixels/mm value for both physical axes.
    canvas_size = 768
    pad = 32
    usable = canvas_size - pad * 2
    pixels_per_mm = max(1.0, min(usable / x_span, usable / z_span))
    plot_w = max(2, int(round(x_span * pixels_per_mm)))
    plot_h = max(2, int(round(z_span * pixels_per_mm)))
    width = canvas_size
    height = canvas_size
    x_origin = (width - plot_w) // 2
    y_origin = (height - plot_h) // 2

    bg = (20, 20, 22, 255)
    fill = (105, 120, 132, 255)
    line = (238, 243, 248, 255)
    baseline = (148, 154, 162, 255)

    if np is not None:
        canvas = np.empty((height, width, 4), dtype=np.uint8)
        canvas[:, :, :] = bg
        px_x = np.linspace(x_min, x_max, plot_w + 1, dtype=np.float64)
        px_z = np.interp(px_x, np.asarray(x_values, dtype=np.float64), np.asarray(z_values, dtype=np.float64))
        y_base = y_origin + int(round((0.0 - z_min) * pixels_per_mm))
        y_base = max(0, min(height - 1, y_base))
        canvas[y_base, x_origin:x_origin + plot_w + 1, :] = baseline
        curve_y = y_origin + np.rint((px_z - z_min) * pixels_per_mm).astype(np.int64)
        curve_y = np.clip(curve_y, 0, height - 1)
        for px, cy in enumerate(curve_y):
            x = x_origin + px
            lo = min(y_base, int(cy))
            hi = max(y_base, int(cy))
            if hi > lo:
                canvas[lo + 1:hi, x, :] = fill
            canvas[int(cy), x, :] = line
            if int(cy) + 1 < height:
                canvas[int(cy) + 1, x, :] = line
        rgba_bytes = canvas.reshape(-1).tobytes()
    else:
        pixels = bytearray(bg * (width * height))
        def put(x, y, color):
            if 0 <= x < width and 0 <= y < height:
                idx = (y * width + x) * 4
                pixels[idx:idx + 4] = bytes(color)
        y_base = y_origin + int(round((0.0 - z_min) * pixels_per_mm))
        for px in range(plot_w + 1):
            target_x = x_min + x_span * (px / float(plot_w))
            pos = (target_x - x_min) / x_span * (len(points) - 1)
            i0 = max(0, min(len(points) - 1, int(math.floor(pos))))
            i1 = min(len(points) - 1, i0 + 1)
            t = pos - i0
            z = z_values[i0] + (z_values[i1] - z_values[i0]) * t
            cy = y_origin + int(round((z - z_min) * pixels_per_mm))
            x = x_origin + px
            put(x, y_base, baseline)
            for y in range(min(y_base, cy) + 1, max(y_base, cy)):
                put(x, y, fill)
            put(x, cy, line)
        rgba_bytes = pixels

    _write_rgba_png(output_path, width, height, rgba_bytes)
    return Path(output_path)


def _render_high_res_cross_section(points, output_path):
    """Render a high-resolution 1:1 X:Z profile from actual physical mesh points."""
    if not points or len(points) < 2:
        raise RuntimeError('Cross-section profile has too few points')
    points = sorted(points, key=lambda pair: pair[0])
    x_values = [float(p[0]) for p in points]
    z_values = [float(p[1]) for p in points]
    x_min, x_max = min(x_values), max(x_values)
    z_min = min(0.0, min(z_values))
    z_max = max(z_values)
    x_span = max(0.000001, x_max - x_min)
    z_span = max(0.000001, z_max - z_min)

    # The full viewer is intentionally much higher resolution than the sidebar
    # thumbnail. Oversampling the actual mesh polyline keeps native zoom clean.
    side_pad = 48
    top_pad = 32
    bottom_pad = 32
    desired_plot_w = max(4096, min(16384, max(2, len(points)) * 6))
    ppm_w = desired_plot_w / x_span
    max_plot_h = 8192 - top_pad - bottom_pad
    ppm_h = max_plot_h / z_span
    pixels_per_mm = max(1.0, min(ppm_w, ppm_h))
    plot_w = max(2, int(round(x_span * pixels_per_mm)))
    plot_h = max(2, int(round(z_span * pixels_per_mm)))
    width = plot_w + side_pad * 2
    height = plot_h + top_pad + bottom_pad

    bg = (18, 19, 22, 255)
    fill = (74, 113, 158, 255)
    line = (242, 247, 252, 255)
    baseline = (142, 149, 158, 255)

    if np is not None:
        canvas = np.empty((height, width, 4), dtype=np.uint8)
        canvas[:, :, :] = bg
        px_x = np.linspace(x_min, x_max, plot_w + 1, dtype=np.float64)
        px_z = np.interp(px_x, np.asarray(x_values, dtype=np.float64), np.asarray(z_values, dtype=np.float64))
        y_base = bottom_pad + int(round((0.0 - z_min) * pixels_per_mm))
        y_base = max(bottom_pad, min(height - top_pad - 1, y_base))
        canvas[y_base, side_pad:side_pad + plot_w + 1, :] = baseline
        curve_y = bottom_pad + np.rint((px_z - z_min) * pixels_per_mm).astype(np.int64)
        curve_y = np.clip(curve_y, bottom_pad, height - top_pad - 1)
        for px, cy in enumerate(curve_y):
            x = side_pad + px
            lo = min(y_base, int(cy))
            hi = max(y_base, int(cy))
            if hi > lo:
                canvas[lo + 1:hi, x, :] = fill
            canvas[int(cy), x, :] = line
            if int(cy) + 1 < height - top_pad:
                canvas[int(cy) + 1, x, :] = line
        rgba_bytes = canvas.reshape(-1).tobytes()
    else:
        pixels = bytearray(bg * (width * height))
        def put(x, y, color):
            if 0 <= x < width and 0 <= y < height:
                idx = (y * width + x) * 4
                pixels[idx:idx + 4] = bytes(color)
        y_base = bottom_pad + int(round((0.0 - z_min) * pixels_per_mm))
        for px in range(plot_w + 1):
            target_x = x_min + x_span * (px / float(plot_w))
            # Binary search would be faster, but this path is only for Blender builds
            # without NumPy and typical profiles remain manageable.
            pos = (target_x - x_min) / x_span * (len(points) - 1)
            i0 = max(0, min(len(points) - 1, int(math.floor(pos))))
            i1 = min(len(points) - 1, i0 + 1)
            t = pos - i0
            z = z_values[i0] + (z_values[i1] - z_values[i0]) * t
            cy = bottom_pad + int(round((z - z_min) * pixels_per_mm))
            x = side_pad + px
            put(x, y_base, baseline)
            for y in range(min(y_base, cy) + 1, max(y_base, cy)):
                put(x, y, fill)
            put(x, cy, line)
        rgba_bytes = pixels

    _write_rgba_png(output_path, width, height, rgba_bytes)
    return Path(output_path), width, height, x_span, z_max


def _generate_full_cross_section_for_viewer(context, source_kind):
    settings = context.scene.lenticular_sync
    source_kind = str(source_kind or 'BUILD').upper()
    if source_kind == 'REFERENCE':
        vertical = settings.reference_heightmap_orientation == 'VERTICAL'
        obj = bpy.data.objects.get(OBJECT_PREFIX + 'ReferenceHeightmapLens')
        points = _mesh_cross_section_points(obj, vertical)
        if not points:
            points = _fallback_reference_cross_section_points(settings)
        points = _crop_reference_profile_to_selected_span(settings, points)
        filename = 'reference_heightmap_mesh_cross_section_full.png'
    else:
        vertical = settings.orientation == 'VERTICAL'
        obj = bpy.data.objects.get(OBJECT_PREFIX + ('DirectionalRelief' if _lens_free_mode(settings) else 'LenticularLens'))
        points = _mesh_cross_section_points(obj, vertical)
        if not points:
            points = _fallback_build_cross_section_points(settings)
        filename = 'generated_relief_mesh_cross_section_full.png' if _lens_free_mode(settings) else 'generated_lens_mesh_cross_section_full.png'
    if not points:
        raise RuntimeError('No generated geometry is available for the cross-section')
    temp_dir = Path(bpy.app.tempdir or tempfile.gettempdir()) / 'lenticular_previews'
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / filename
    return _render_high_res_cross_section(points, output_path)


class LENTICULAR_OT_open_cross_section_viewer(Operator):
    bl_idname = 'lenticular.open_cross_section_viewer'
    bl_label = 'Open Cross Section Full View'
    bl_description = 'Render a high-resolution 1:1 physical cross section from the actual current geometry and open it in the image viewer'

    source_kind: EnumProperty(
        items=[('BUILD', 'Build Lens', ''), ('REFERENCE', 'Reference Heightmap', '')],
        default='BUILD',
    )

    def execute(self, context):
        try:
            path, width, height, span_mm, max_height_mm = _generate_full_cross_section_for_viewer(context, self.source_kind)
            _open_image_viewer_window(context, str(path))
            label = 'reference heightmap' if self.source_kind == 'REFERENCE' else ('generated relief' if _lens_free_mode(context.scene.lenticular_sync) else 'generated lens')
            _set_status(
                context.scene.lenticular_sync,
                f'Opened {label} mesh cross section: {width} x {height} px, {span_mm:.3f} mm span',
            )
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


def _open_image_viewer_window(context, filepath):
    path = Path(bpy.path.abspath(filepath))
    if not path.is_file():
        raise RuntimeError("Image file not found")
    image = bpy.data.images.load(str(path), check_existing=True)
    try:
        image.reload()
    except Exception:
        pass

    wm = context.window_manager
    before = {window.as_pointer() for window in wm.windows}
    new_window = None

    # WM-level window creation is much more reliable than area_dupli when this
    # operator is invoked from an N-panel region.
    try:
        bpy.ops.wm.window_new()
    except Exception:
        pass
    for window in wm.windows:
        try:
            if window.as_pointer() not in before:
                new_window = window
                break
        except Exception:
            pass

    # Fallback for Blender builds where window_new is unavailable/restricted.
    if new_window is None and context.window is not None and context.area is not None:
        window_region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if window_region is not None:
            try:
                with context.temp_override(
                    window=context.window,
                    screen=context.window.screen,
                    area=context.area,
                    region=window_region,
                    space_data=context.area.spaces.active,
                ):
                    bpy.ops.screen.area_dupli()
            except Exception:
                pass
            for window in wm.windows:
                try:
                    if window.as_pointer() not in before:
                        new_window = window
                        break
                except Exception:
                    pass

    if new_window is None:
        raise RuntimeError("Blender could not create the image viewer window")

    areas = list(new_window.screen.areas)
    if not areas:
        raise RuntimeError("Image viewer window has no editor area")

    # Use the largest editor in the new window, convert it to an Image Editor,
    # then maximize that editor so the window behaves like a dedicated viewer.
    area = max(areas, key=lambda a: max(1, a.width) * max(1, a.height))
    area.type = 'IMAGE_EDITOR'
    space = area.spaces.active
    space.image = image
    try:
        space.show_region_toolbar = False
    except Exception:
        pass
    try:
        space.show_region_ui = False
    except Exception:
        pass
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is not None:
        try:
            with bpy.context.temp_override(
                window=new_window,
                screen=new_window.screen,
                area=area,
                region=region,
                space_data=space,
            ):
                try:
                    bpy.ops.screen.screen_full_area(use_hide_panels=True)
                except Exception:
                    pass
        except Exception:
            pass

    # Reacquire the editor after maximizing, then fit the image to the window.
    viewer_area = next((a for a in new_window.screen.areas if a.type == 'IMAGE_EDITOR'), area)
    viewer_space = viewer_area.spaces.active
    viewer_space.image = image
    viewer_region = next((r for r in viewer_area.regions if r.type == 'WINDOW'), None)
    if viewer_region is not None:
        try:
            with bpy.context.temp_override(
                window=new_window,
                screen=new_window.screen,
                area=viewer_area,
                region=viewer_region,
                space_data=viewer_space,
            ):
                bpy.ops.image.view_all(fit_view=True)
        except Exception:
            pass
    return True


class LENTICULAR_OT_open_image_viewer(Operator):
    bl_idname = "lenticular.open_image_viewer"
    bl_label = "Open Image Viewer"
    bl_description = "Open this image in a floating Blender Image Editor with native zoom and pan"

    filepath: StringProperty(default="", subtype="FILE_PATH")
    viewer_title: StringProperty(default="Image Viewer")

    def execute(self, context):
        try:
            _open_image_viewer_window(context, self.filepath)
            _set_status(context.scene.lenticular_sync, "Opened " + (self.viewer_title or "image") + " viewer")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_preview_zoom(Operator):
    bl_idname = "lenticular.preview_zoom"
    bl_label = "Image Preview Zoom"
    bl_description = "Change the display size of Build-page image previews"

    delta: FloatProperty(default=0.0)
    reset: BoolProperty(default=False)

    def execute(self, context):
        settings = context.scene.lenticular_sync
        if self.reset:
            settings.build_preview_zoom = 1.0
        else:
            settings.build_preview_zoom = max(0.5, min(2.0, float(settings.build_preview_zoom) + float(self.delta)))
        return {'FINISHED'}


class LENTICULAR_OT_create_project(Operator):
    bl_idname = "lenticular.create_project"
    bl_label = "Create Shared Project"
    bl_description = "Create a project.json so Blender can be the starting point"

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        folder = Path(self.directory) if self.directory else None
        if not folder:
            self.report({"ERROR"}, "Choose a project folder")
            return {"CANCELLED"}
        folder.mkdir(parents=True, exist_ok=True)
        settings = context.scene.lenticular_sync
        project_path = folder / "project.json"
        _state["applying"] = True
        try:
            settings.project_file = str(project_path)
        finally:
            _state["applying"] = False
        context.scene["lenticular_project_file"] = str(project_path)
        _state["session_connected"] = True
        _consolidate_assets_into_project(settings)
        if not _send_to_app(context):
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        _set_status(settings, "Shared project created")
        return {"FINISHED"}



def _add_source_image_paths(settings, context, paths):
    added = 0
    accepted = []
    existing = set()
    for item in settings.source_frames:
        try:
            existing.add(str(Path(item.path).resolve()).lower())
        except Exception:
            existing.add(str(item.path).lower())
    for raw in paths:
        if len(settings.source_frames) >= 8:
            break
        path = Path(raw)
        if not path.is_file() or not _is_supported_image(path):
            continue
        try:
            normalized = str(path.resolve()).lower()
        except Exception:
            normalized = str(path).lower()
        if normalized in existing:
            continue
        stored = _copy_asset_into_project(settings, path, "source_frames")
        item = settings.source_frames.add()
        item.path = str(stored)
        item.display_name = stored.name
        existing.add(normalized)
        accepted.append(stored)
        added += 1
    if added:
        if settings.workflow != "HEIGHTMAP": settings.workflow = "SOURCE_FRAMES"
        settings.views = len(settings.source_frames)
        settings.source_frame_index = max(0, len(settings.source_frames) - 1)
        _mark_dirty_scope("images")(settings, context)
        _sync_dedicated_image_editors(context, force=True)
    return added, accepted


class LENTICULAR_OT_drop_source_images(Operator):
    bl_idname = "lenticular.drop_source_images"
    bl_label = "Drop Source Images"
    bl_description = "Add dropped image files to the Lenticulizer source sequence"

    filepath: StringProperty(subtype="FILE_PATH")
    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        settings = context.scene.lenticular_sync
        paths = []
        if self.files:
            paths = [Path(self.directory) / f.name for f in self.files]
        elif self.filepath:
            paths = [Path(self.filepath)]
        added, _ = _add_source_image_paths(settings, context, paths)
        if added:
            _set_status(settings, f"Dropped {added} source image" + ("s" if added != 1 else ""))
            if len(paths) > added and len(settings.source_frames) >= 8:
                self.report({"INFO"}, "Maximum 8 source images")
            return {"FINISHED"}
        self.report({"WARNING"}, "No supported new images were added")
        return {"CANCELLED"}


class LENTICULAR_FH_source_images(FileHandler):
    bl_idname = "LENTICULAR_FH_source_images"
    bl_label = "Lenticulizer Source Images"
    bl_import_operator = "lenticular.drop_source_images"
    bl_file_extensions = ".png;.jpg;.jpeg;.bmp;.tif;.tiff"

    @classmethod
    def poll_drop(cls, context):
        try:
            return (
                context.area is not None
                and context.area.type in {"VIEW_3D", "IMAGE_EDITOR"}
                and hasattr(context.scene, "lenticular_sync")
                and bool(context.scene.lenticular_sync.project_file)
            )
        except Exception:
            return False


class LENTICULAR_OT_drag_source_reorder(Operator):
    bl_idname = "lenticular.drag_source_reorder"
    bl_label = "Drag Source Image"
    bl_description = "Drag up or down to reposition this source image in the viewing sequence"

    index: IntProperty(default=0, min=0)
    _anchor_y = 0
    _current_index = 0
    _original = None

    def invoke(self, context, event):
        settings = context.scene.lenticular_sync
        if self.index < 0 or self.index >= len(settings.source_frames):
            return {"CANCELLED"}
        self._current_index = int(self.index)
        self._anchor_y = int(event.mouse_y)
        self._original = [(item.path, item.display_name) for item in settings.source_frames]
        settings.source_frame_index = self._current_index
        context.window_manager.modal_handler_add(self)
        _set_status(settings, "Drag up/down to reorder source image; release to place")
        return {"RUNNING_MODAL"}

    def _restore(self, settings):
        if not self._original:
            return
        previous = _state["applying"]
        _state["applying"] = True
        try:
            settings.source_frames.clear()
            for path, display_name in self._original:
                item = settings.source_frames.add()
                item.path = path
                item.display_name = display_name
            settings.source_frame_index = min(self.index, max(0, len(settings.source_frames) - 1))
        finally:
            _state["applying"] = previous

    def modal(self, context, event):
        settings = context.scene.lenticular_sync
        if event.type == "MOUSEMOVE":
            dy = int(event.mouse_y) - int(self._anchor_y)
            threshold = 30
            moved = False
            while dy >= threshold and self._current_index > 0:
                settings.source_frames.move(self._current_index, self._current_index - 1)
                self._current_index -= 1
                self._anchor_y += threshold
                dy -= threshold
                moved = True
            while dy <= -threshold and self._current_index < len(settings.source_frames) - 1:
                settings.source_frames.move(self._current_index, self._current_index + 1)
                self._current_index += 1
                self._anchor_y -= threshold
                dy += threshold
                moved = True
            if moved:
                settings.source_frame_index = self._current_index
                _sync_dedicated_image_editors(context, force=True)
                try:
                    context.area.tag_redraw()
                except Exception:
                    pass
            return {"RUNNING_MODAL"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            settings.source_frame_index = self._current_index
            settings.views = len(settings.source_frames)
            _mark_dirty_scope("images")(settings, context)
            _set_status(settings, "Source image order updated")
            return {"FINISHED"}
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._restore(settings)
            _sync_dedicated_image_editors(context, force=True)
            _set_status(settings, "Source reorder cancelled")
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}


class LENTICULAR_OT_add_source_images(Operator, ImportHelper):
    bl_idname = "lenticular.add_source_images"
    bl_label = "Add Source Images"
    bl_description = "Add 2 to 8 source images in viewing order"

    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={"HIDDEN", "SKIP_SAVE"})
    directory: StringProperty(subtype="DIR_PATH")

    def execute(self, context):
        settings = context.scene.lenticular_sync
        selected = []
        if self.files:
            selected = [Path(self.directory) / f.name for f in self.files]
        elif self.filepath:
            selected = [Path(self.filepath)]
        added, _ = _add_source_image_paths(settings, context, selected)
        if added:
            _set_status(settings, f"Added {added} source image" + ("s" if added != 1 else ""))
        if len(selected) > added and len(settings.source_frames) >= 8:
            self.report({"INFO"}, "Maximum 8 source images")
        return {"FINISHED"}


class LENTICULAR_OT_select_source_image(Operator):
    bl_idname = "lenticular.select_source_image"
    bl_label = "Select Source Image"
    bl_description = "Select this source image and show it in the dedicated Selected Source Image viewer"

    index: IntProperty(default=0, min=0, max=7)

    def execute(self, context):
        settings = context.scene.lenticular_sync
        if self.index < 0 or self.index >= len(settings.source_frames):
            return {"CANCELLED"}
        settings.source_frame_index = int(self.index)
        return {"FINISHED"}


class LENTICULAR_OT_remove_source_image(Operator):
    bl_idname = "lenticular.remove_source_image"
    bl_label = "Remove Source Image"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        idx = settings.source_frame_index
        if idx < 0 or idx >= len(settings.source_frames):
            return {"CANCELLED"}
        settings.source_frames.remove(idx)
        settings.source_frame_index = min(idx, max(0, len(settings.source_frames) - 1))
        if len(settings.source_frames) > 0:
            settings.views = len(settings.source_frames)
        _mark_dirty_scope("images")(settings, context)
        return {"FINISHED"}


class LENTICULAR_OT_move_source_image(Operator):
    bl_idname = "lenticular.move_source_image"
    bl_label = "Move Source Image"
    direction: IntProperty(default=0)

    def execute(self, context):
        settings = context.scene.lenticular_sync
        idx = settings.source_frame_index
        new_idx = idx + self.direction
        if idx < 0 or idx >= len(settings.source_frames) or new_idx < 0 or new_idx >= len(settings.source_frames):
            return {"CANCELLED"}
        settings.source_frames.move(idx, new_idx)
        settings.source_frame_index = new_idx
        _mark_dirty_scope("images")(settings, context)
        return {"FINISHED"}


class LENTICULAR_OT_clear_source_images(Operator):
    bl_idname = "lenticular.clear_source_images"
    bl_label = "Clear Source Images"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        settings.source_frames.clear()
        settings.source_frame_index = 0
        _mark_dirty_scope("images")(settings, context)
        return {"FINISHED"}


class LENTICULAR_OT_import_interlaced(Operator, ImportHelper):
    bl_idname = "lenticular.import_interlaced"
    bl_label = "Import Existing Interlaced Image"
    bl_description = "Use an already interlaced image and sync it to the Windows app"

    filter_glob: StringProperty(default="*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff", options={"HIDDEN"})

    def execute(self, context):
        settings = context.scene.lenticular_sync
        source = Path(self.filepath)
        if not source.is_file() or not _is_supported_image(source):
            self.report({"ERROR"}, "Choose a supported image")
            return {"CANCELLED"}
        preferred = "interlaced_image" + source.suffix.lower()
        stored = _copy_asset_into_project(settings, source, None, preferred)
        settings.interlaced_image = _project_relative_path(settings, stored)
        settings.workflow = "EXISTING_INTERLACED"
        meta = _read_png_lenticular_metadata(source)
        detected_views = 0
        if meta:
            previous = _state["applying"]
            _state["applying"] = True
            try:
                if 2 <= int(meta.get("views", 0)) <= 8:
                    settings.views = int(meta["views"]); detected_views = settings.views
                if float(meta.get("lpi", 0.0)) > 0.0:
                    settings.lpi = float(meta["lpi"]); settings.lpi_helper_mode = "MANUAL"
                if float(meta.get("width_mm", 0.0)) > 0.0:
                    settings.width_mm = float(meta["width_mm"])
                if float(meta.get("height_mm", 0.0)) > 0.0:
                    settings.height_mm = float(meta["height_mm"])
                if meta.get("orientation") in {"VERTICAL", "HORIZONTAL"}:
                    settings.orientation = meta["orientation"]
            finally:
                _state["applying"] = previous
        if detected_views < 2:
            inferred = _infer_views_from_filename(source)
            if inferred >= 2:
                settings.views = inferred; detected_views = inferred
        _apply_local_optical_rules(settings)
        _mark_dirty_scope("images")(settings, context)
        if detected_views >= 2:
            _set_status(settings, f"Interlaced image imported - Views auto-set to {detected_views}; edit Views to override")
        else:
            _set_status(settings, "Interlaced image imported - enter Views in Print Setup if metadata is unavailable")
        return {"FINISHED"}


class LENTICULAR_OT_set_workflow(Operator):
    bl_idname = "lenticular.set_workflow"
    bl_label = "Set Workflow"

    workflow: StringProperty(default="SOURCE_FRAMES")

    def execute(self, context):
        settings = context.scene.lenticular_sync
        settings.workflow = self.workflow if self.workflow in {"EXISTING_INTERLACED", "HEIGHTMAP"} else "SOURCE_FRAMES"
        _mark_dirty_scope("images")(settings, context)
        _set_status(settings, "Workflow set to " + ("Use Existing Interlaced Image" if settings.workflow == "EXISTING_INTERLACED" else "Build from Source Images"))
        return {"FINISHED"}


class LENTICULAR_OT_build_interlaced(Operator):
    bl_idname = "lenticular.build_interlaced"
    bl_label = "Build Interlaced Image"
    bl_description = "Build an interlaced image from the ordered source images using the current print size, LPI, and detail settings"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            if _lens_free_mode(settings) and len(_source_frame_paths(settings)) != _relief_supported_view_count():
                raise RuntimeError("Lens-Free Relief currently supports exactly 2 source images using the corrected naked-eye prism baseline.")
            out_path, out_w, out_h, ppl = _build_interlaced_image(settings)
            if settings.workflow == "HEIGHTMAP":
                _generate_working_heightmap(settings)
            _state["dirty"] = True
            _state["dirty_scope"] = "images"
            _state["last_change_time"] = time.time()
            unit_label = "px per prism" if settings.output_mode == "RELIEF" else "px per lenticule"
            _set_status(settings, f"Built interlaced image: {Path(out_path).name} - {out_w} x {out_h} px - {ppl} {unit_label}")
            if settings.auto_sync:
                _send_to_app(context, quiet=True)
            if settings.auto_rebuild:
                _rebuild_scene(context)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            _set_status(settings, "Build failed: " + str(exc))
            return {"CANCELLED"}


class LENTICULAR_OT_select_camera(Operator):
    bl_idname = "lenticular.select_camera"
    bl_label = "Select Lenticular Camera"
    camera_name: StringProperty(default="")

    def execute(self, context):
        camera = bpy.data.objects.get(self.camera_name)
        if not _activate_camera(context, camera):
            self.report({"ERROR"}, "Camera not found")
            return {"CANCELLED"}
        return {"FINISHED"}


class LENTICULAR_OT_camera_step(Operator):
    bl_idname = "lenticular.camera_step"
    bl_label = "Step Lenticular Camera"
    direction: IntProperty(default=1)

    def execute(self, context):
        cameras = _camera_objects()
        if not cameras:
            self.report({"ERROR"}, "Rebuild the lens scene first")
            return {"CANCELLED"}
        target_area = _camera_control_area(context)
        current = _camera_used_by_area(context.scene, target_area) if target_area is not None else context.scene.camera
        try:
            idx = cameras.index(current)
        except ValueError:
            idx = min(range(len(cameras)), key=lambda i: abs(float(cameras[i].get("lenticular_angle_deg", 0.0))))
        idx = max(0, min(len(cameras) - 1, idx + self.direction))
        _activate_camera(context, cameras[idx])
        return {"FINISHED"}


class LENTICULAR_OT_camera_center(Operator):
    bl_idname = "lenticular.camera_center"
    bl_label = "Center Camera"

    def execute(self, context):
        cameras = _camera_objects()
        if not cameras:
            self.report({"ERROR"}, "Rebuild the lens scene first")
            return {"CANCELLED"}
        camera = min(cameras, key=lambda cam: abs(float(cam.get("lenticular_angle_deg", 0.0))))
        _activate_camera(context, camera)
        return {"FINISHED"}


class LENTICULAR_OT_viewport_tracker(Operator):
    bl_idname = "lenticular.viewport_tracker"
    bl_label = "Lenticulizer Viewport Tracker"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        if _state.get("viewport_tracker_running", False):
            return {'CANCELLED'}
        _state["viewport_tracker_running"] = True
        _state["viewport_tracker_stop"] = False
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if _state.get("viewport_tracker_stop", False):
            _state["viewport_tracker_running"] = False
            return {'CANCELLED'}

        interaction_events = {
            'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE',
            'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM',
            'NDOF_MOTION', 'NDOF_BUTTON_MENU', 'NDOF_BUTTON_FIT',
        }
        is_interaction = event.type in interaction_events and event.value in {'PRESS', 'NOTHING'}
        if is_interaction and context.window and context.window.screen and not _state.get("viewport_picker_running", False):
            area, region = _area_at_window_xy(context.window.screen, int(event.mouse_x), int(event.mouse_y))
            if area is not None:
                _remember_viewport_target(context.window, area, region)
        return {'PASS_THROUGH'}


class LENTICULAR_OT_pick_viewport_target(Operator):
    bl_idname = "lenticular.pick_viewport_target"
    bl_label = "Choose Target Viewport"
    bl_description = "Click the 3D viewport that the Viewport Match buttons should control"

    def invoke(self, context, event):
        if _state.get("viewport_picker_running", False):
            return {'CANCELLED'}
        _state["viewport_picker_running"] = True
        _set_status(context.scene.lenticular_sync, "Click inside the 3D viewport to control (Esc to cancel)")
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            _state["viewport_picker_running"] = False
            _set_status(context.scene.lenticular_sync, "Viewport target selection cancelled")
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and context.window and context.window.screen:
            area, region = _area_at_window_xy(context.window.screen, int(event.mouse_x), int(event.mouse_y))
            if area is not None and _remember_viewport_target(context.window, area, region):
                _state["viewport_picker_running"] = False
                _set_status(context.scene.lenticular_sync, "Target viewport: " + _target_viewport_label(context))
                return {'FINISHED'}
        return {'RUNNING_MODAL'}


class LENTICULAR_OT_select_target_viewport(Operator):
    bl_idname = "lenticular.select_target_viewport"
    bl_label = "Select Target Viewport"
    bl_description = "Explicitly choose which 3D viewport both Camera View and Viewport Match controls affect"
    viewport_index: IntProperty(default=1, min=1)

    def execute(self, context):
        areas = _view3d_areas_sorted(context)
        if not areas:
            self.report({"ERROR"}, "No 3D viewports are available")
            return {"CANCELLED"}
        index = max(1, min(int(self.viewport_index), len(areas)))
        context.scene.lenticular_sync.target_viewport_index = index
        try:
            _state["explicit_target_view3d_area_ptr"] = areas[index - 1].as_pointer()
        except Exception:
            _state["explicit_target_view3d_area_ptr"] = 0
        _set_status(context.scene.lenticular_sync, f"Target viewport: Viewport {index}")
        return {"FINISHED"}


class LENTICULAR_OT_use_panel_viewport(Operator):
    bl_idname = "lenticular.use_panel_viewport"
    bl_label = "Use This Panel Viewport"
    bl_description = "Set the 3D viewport containing this Lenticulizer panel as the explicit target for both view-control groups"

    def execute(self, context):
        if context.area is None or context.area.type != "VIEW_3D":
            self.report({"ERROR"}, "The Lenticulizer panel is not inside a 3D viewport")
            return {"CANCELLED"}
        settings = context.scene.lenticular_sync
        try:
            areas = _view3d_areas_sorted(context)
            panel_index = next((i for i, area in enumerate(areas, 1) if area.as_pointer() == context.area.as_pointer()), None)
            if panel_index is None:
                raise RuntimeError("Panel viewport not found")
            settings.target_viewport_index = panel_index
            _state["explicit_target_view3d_area_ptr"] = context.area.as_pointer()
        except Exception:
            self.report({"ERROR"}, "Could not select this viewport")
            return {"CANCELLED"}
        _set_status(settings, "Target viewport: " + _target_viewport_label(context))
        return {"FINISHED"}


class LENTICULAR_OT_viewport_camera(Operator):
    bl_idname = "lenticular.viewport_camera"
    bl_label = "Match Viewport to Lenticular View"
    bl_description = "Match only the selected normal 3D viewport to this lenticular view without changing the scene camera"
    camera_name: StringProperty(default="")

    def execute(self, context):
        camera = bpy.data.objects.get(self.camera_name)
        if not _match_viewport_to_camera(context, camera):
            self.report({"ERROR"}, "Could not activate that camera in the selected viewport")
            return {"CANCELLED"}
        return {"FINISHED"}


class LENTICULAR_OT_viewport_step(Operator):
    bl_idname = "lenticular.viewport_step"
    bl_label = "Step Viewport View"
    bl_description = "Match only the selected normal 3D viewport to the previous or next generated view"
    direction: IntProperty(default=1)

    def execute(self, context):
        cameras = _camera_objects()
        if not cameras:
            self.report({"ERROR"}, "Rebuild the lens scene first")
            return {"CANCELLED"}
        settings = context.scene.lenticular_sync
        current = bpy.data.objects.get(settings.active_viewport_camera_name) if settings.active_viewport_camera_name else None
        try:
            idx = cameras.index(current)
        except ValueError:
            idx = min(range(len(cameras)), key=lambda i: abs(float(cameras[i].get("lenticular_angle_deg", 0.0))))
        idx = max(0, min(len(cameras) - 1, idx + self.direction))
        if not _match_viewport_to_camera(context, cameras[idx]):
            return {"CANCELLED"}
        return {"FINISHED"}


class LENTICULAR_OT_viewport_center(Operator):
    bl_idname = "lenticular.viewport_center"
    bl_label = "Center Viewport"
    bl_description = "Match only the selected normal 3D viewport to the center generated view"

    def execute(self, context):
        cameras = _camera_objects()
        if not cameras:
            self.report({"ERROR"}, "Rebuild the lens scene first")
            return {"CANCELLED"}
        camera = min(cameras, key=lambda cam: abs(float(cam.get("lenticular_angle_deg", 0.0))))
        if not _match_viewport_to_camera(context, camera):
            return {"CANCELLED"}
        return {"FINISHED"}


class LENTICULAR_OT_find_project(Operator):
    bl_idname = "lenticular.find_project"
    bl_label = "Find Current Project"
    bl_description = "Use the project associated with the current Blender scene"

    def execute(self, context):
        found = _find_project_from_scene(context)
        if not found:
            self.report({"WARNING"}, "No project.json found for this scene")
            return {"CANCELLED"}
        settings = context.scene.lenticular_sync
        _state["applying"] = True
        try:
            settings.project_file = str(found)
        finally:
            _state["applying"] = False
        _state["session_connected"] = True
        _pull_from_app(context, rebuild=True)
        return {"FINISHED"}


class LENTICULAR_OT_pull(Operator):
    bl_idname = "lenticular.pull"
    bl_label = "Import From App"
    bl_description = "Read the latest settings written by the Windows app"

    def execute(self, context):
        _state["session_connected"] = True
        if not _pull_from_app(context, rebuild=context.scene.lenticular_sync.auto_rebuild):
            self.report({"ERROR"}, context.scene.lenticular_sync.status)
            return {"CANCELLED"}
        return {"FINISHED"}


class LENTICULAR_OT_send(Operator):
    bl_idname = "lenticular.send"
    bl_label = "Send Settings To App"
    bl_description = "Write Blender changes to the shared project file and tell the Windows app to open this project"

    def execute(self, context):
        _state["session_connected"] = True
        settings = context.scene.lenticular_sync
        if not _send_to_app(context):
            self.report({"ERROR"}, settings.status)
            return {"CANCELLED"}
        project_path = _project_path(settings)
        if project_path and _publish_app_project_handoff(project_path):
            _set_status(settings, "Sent to app - project handoff published")
        else:
            _set_status(settings, "Sent settings, but app handoff could not be published")
        return {"FINISHED"}


class LENTICULAR_OT_disconnect(Operator):
    bl_idname = "lenticular.disconnect"
    bl_label = "Close Project"
    bl_description = "Close the current lenticular project without deleting any project files"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        _state["project_closed_at"] = time.time()
        _clear_blender_project_handoff_pointers(clear_current=True)
        _state["session_connected"] = False
        _state["dirty"] = False
        _state["last_revision"] = 0
        _state["last_mtime"] = 0.0
        _state["last_change_time"] = 0.0
        _state["dirty_scope"] = "geometry"
        _state["pending_interlace"] = False
        _state["pending_heightmap"] = False
        _state["pending_lens"] = False
        _state["pending_texture"] = False
        _state["reactive_busy"] = False
        _state["optics_initialized"] = False

        _state["applying"] = True
        try:
            settings.project_file = ""
            settings.source_frames.clear()
            settings.source_frame_index = 0
            settings.interlaced_image = ""
            settings.heightmap_image = ""
            settings.reference_heightmap_path = ""
            settings.active_camera_name = ""
            settings.workflow = "SOURCE_FRAMES"
            settings.views = 3
            settings.width_mm = 60.0
            settings.height_mm = 60.0
            settings.lpi = 35.0
            settings.orientation = "VERTICAL"
            settings.settings_mode = "AUTOMATIC"
            settings.priority = "lpi"
            settings.lens_profile = "AUTO"
            settings.print_profile = "RECOMMENDED"
            settings.base_mode = "RECOMMENDED"
            settings.manual_thickness_unit = "MM"
            settings.manual_thickness_unit_last = "MM"
            settings.manual_thickness_value = 0.797
            settings.manual_base_mm = 0.506
            settings.phase_pitch = 0.0
            if "lenticular_project_file" in context.scene:
                del context.scene["lenticular_project_file"]
        finally:
            _state["applying"] = False

        _apply_local_optical_rules(settings)

        try:
            _remove_sim_collection()
            _remove_legacy_sim_objects()
            _remove_reference_collection()
        except Exception:
            pass

        if context.scene.camera and context.scene.camera.name.startswith(OBJECT_PREFIX):
            context.scene.camera = None
        _set_status(settings, "Project closed - live sync disconnected; choose or create a project to begin")
        return {"FINISHED"}


class LENTICULAR_OT_rebuild(Operator):
    bl_idname = "lenticular.rebuild"
    bl_label = "Rebuild Lens Scene"
    bl_description = "Rebuild the simulation geometry and cameras from current settings"

    def execute(self, context):
        try:
            _rebuild_scene(context)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}


class LENTICULAR_OT_render_current(Operator):
    bl_idname = "lenticular.render_current"
    bl_label = "Render Current View"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        project_dir = _project_dir(settings)
        if not project_dir:
            self.report({"ERROR"}, "No project folder")
            return {"CANCELLED"}
        render_dir = project_dir / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)
        camera_name = context.scene.camera.name if context.scene.camera else "current"
        context.scene.render.filepath = str(render_dir / (camera_name + ".png"))
        bpy.ops.render.render(write_still=True)
        _set_status(settings, "Rendered " + camera_name)
        return {"FINISHED"}


class LENTICULAR_OT_render_all(Operator):
    bl_idname = "lenticular.render_all"
    bl_label = "Render All Views"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        project_dir = _project_dir(settings)
        collection = bpy.data.collections.get(COLLECTION_NAME)
        if not project_dir or not collection:
            self.report({"ERROR"}, "Build the lenticular scene first")
            return {"CANCELLED"}
        render_dir = project_dir / "renders"
        render_dir.mkdir(parents=True, exist_ok=True)
        cameras = _camera_objects()
        if not cameras:
            self.report({"ERROR"}, "No lenticular view cameras found")
            return {"CANCELLED"}
        previous = context.scene.camera
        for camera in cameras:
            context.scene.camera = camera
            context.scene.render.filepath = str(render_dir / (camera.name + ".png"))
            bpy.ops.render.render(write_still=True)
        if previous:
            context.scene.camera = previous
        _set_status(settings, f"Rendered {len(cameras)} views")
        return {"FINISHED"}


class LENTICULAR_OT_export_interlaced(Operator, ExportHelper):
    bl_idname = "lenticular.export_interlaced"
    bl_label = "Export Interlaced Image"
    bl_description = "Save a copy of the current interlaced image"
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={'HIDDEN'})

    def invoke(self, context, event):
        settings = context.scene.lenticular_sync
        current = _current_interlaced_path(settings)
        base_name = current.name if current else "interlaced_image.png"
        self.filepath = str((Path.home() / base_name))
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        settings = context.scene.lenticular_sync
        current = _current_interlaced_path(settings)
        if current is None or not current.is_file():
            self.report({'ERROR'}, "No interlaced image is available to export")
            return {'CANCELLED'}
        out_path = Path(bpy.path.abspath(self.filepath))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            img = bpy.data.images.load(str(current), check_existing=True)
            width = int(img.size[0])
            height = int(img.size[1])
            raw = np.empty(width * height * 4, dtype=np.float32)
            img.pixels.foreach_get(raw)
            rgba_u8 = np.clip(np.rint(raw * 255.0), 0, 255).astype(np.uint8).tobytes()
            ppm = _pixels_per_meter(width, height, settings.width_mm, settings.height_mm)
            _write_rgba_png(out_path, width, height, rgba_u8, ppm)
        except Exception:
            import shutil
            shutil.copyfile(str(current), str(out_path))
        _set_status(settings, f"Exported interlaced image: {out_path.name}")
        return {'FINISHED'}


class LENTICULAR_OT_export_heightmap(Operator, ExportHelper):
    bl_idname = "lenticular.export_heightmap"
    bl_label = "Export Heightmap"
    bl_description = "Generate and save a 16-bit grayscale heightmap from the current lens settings"
    filename_ext = ".png"
    filter_glob: StringProperty(default="*.png", options={'HIDDEN'})

    def invoke(self, context, event):
        settings = context.scene.lenticular_sync
        preferred = _resolve_project_relative(settings, settings.heightmap_image) if settings.heightmap_image else None
        base_name = preferred.name if preferred else "heightmap16.png"
        self.filepath = str((Path.home() / base_name))
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            out_path = Path(bpy.path.abspath(self.filepath))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path = _generate_heightmap_file(settings, out_path)
            _set_status(settings, f"Exported heightmap: {out_path.name}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_export_assets(Operator):
    bl_idname = "lenticular.export_assets"
    bl_label = "Export Interlaced Image and Heightmap"
    bl_description = "Export both the current interlaced image and a matching heightmap into the project folder"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        project_dir = _project_dir(settings)
        if not project_dir:
            self.report({'ERROR'}, "Create or open a project first")
            return {'CANCELLED'}
        current = _current_interlaced_path(settings)
        if current is None or not current.is_file():
            self.report({'ERROR'}, "No interlaced image is available to export")
            return {'CANCELLED'}
        export_dir = project_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        interlace_target = export_dir / current.name
        try:
            img = bpy.data.images.load(str(current), check_existing=True)
            width = int(img.size[0])
            height = int(img.size[1])
            raw = np.empty(width * height * 4, dtype=np.float32)
            img.pixels.foreach_get(raw)
            rgba_u8 = np.clip(np.rint(raw * 255.0), 0, 255).astype(np.uint8).tobytes()
            ppm = _pixels_per_meter(width, height, settings.width_mm, settings.height_mm)
            _write_rgba_png(interlace_target, width, height, rgba_u8, ppm)
        except Exception:
            import shutil
            shutil.copyfile(str(current), str(interlace_target))
        try:
            heightmap_target = export_dir / "heightmap16.png"
            _generate_heightmap_file(settings, heightmap_target)
        except Exception as exc:
            self.report({'ERROR'}, f"Interlaced exported, but heightmap failed: {exc}")
            return {'CANCELLED'}
        _set_status(settings, f"Exported interlaced image and heightmap to {export_dir}")
        return {'FINISHED'}


def _test_export_ready(settings):
    if _state.get("reactive_busy") or _state.get("mode_transaction_active") or any(_state.get(k) for k in ("pending_interlace", "pending_heightmap", "pending_lens", "dirty")):
        return False
    color = _current_interlaced_path(settings)
    depth = _resolve_project_relative(settings, settings.heightmap_image) if settings.heightmap_image else None
    return bool(color and depth and color.is_file() and depth.is_file())


def _test_export_snapshot(settings):
    if not _test_export_ready(settings):
        raise RuntimeError("Wait for generation and synchronization to finish. Generate the matching image and heightmap first.")
    color = _current_interlaced_path(settings)
    depth = _resolve_project_relative(settings, settings.heightmap_image)
    data = _current_project_dict(settings)["settings"]
    # Snapshot only. Do not publish, generate, select, reload an image editor, or
    # change the active clean project assets to the larger test images.
    signature = json.dumps({"settings": data, "files": [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in (color, depth)]}, sort_keys=True)
    return color, depth, data, signature


class LENTICULAR_OT_export_test_set(Operator, ExportHelper):
    bl_idname = "lenticular.export_test_set"
    bl_label = "Export Labeled Test Set"
    bl_description = "Save a separate ZIP with printed settings below the color image and a matching padded heightmap; clean outputs stay unchanged"
    filename_ext = ".zip"
    filter_glob: StringProperty(default="*.zip", options={'HIDDEN'})
    _snapshot_key = ""

    def invoke(self, context, event):
        try:
            settings = context.scene.lenticular_sync
            _, _, _, self._snapshot_key = _test_export_snapshot(settings)
            self.filepath = str(Path.home() / ("Lenticulizer_Test_" + time.strftime("%Y%m%d_%H%M%S") + ".zip"))
            return ExportHelper.invoke(self, context, event)
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def execute(self, context):
        try:
            settings = context.scene.lenticular_sync
            color, depth, data, key = _test_export_snapshot(settings)
            if self._snapshot_key and key != self._snapshot_key:
                raise RuntimeError("The settings or output files changed while the dialog was open. Export again when generation finishes.")
            color_bytes, depth_bytes = color.read_bytes(), depth.read_bytes()
            outputs, plan = test_output_tools.create_test_set(color_bytes, depth_bytes, data,
                name=settings.test_output_name, version="Add-on " + ".".join(map(str, ADDON_VERSION)))
            if _test_export_snapshot(settings)[3] != key:
                raise RuntimeError("The output pair changed during export. Please export again.")
            path = Path(bpy.path.abspath(self.filepath))
            protected = [color, depth, _project_path(settings), bpy.data.filepath]
            protected.extend(_resolve_project_relative(settings, item.path) for item in settings.source_frames if item.path)
            if settings.reference_heightmap_path: protected.append(_resolve_project_relative(settings, settings.reference_heightmap_path))
            test_output_tools.write_test_zip(path, outputs, protected)
            width, height = plan['canvas_size_mm']
            _set_status(settings, f"Labeled test set saved: {path.name}. Print BOTH images at {width:.2f} x {height:.2f} mm, 100% scale.")
            self.report({'INFO'}, f"Test set saved. New print size: {width:.2f} x {height:.2f} mm. Clean outputs unchanged.")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            _set_status(context.scene.lenticular_sync, "Test export failed: " + str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_generate_calibration(Operator):
    bl_idname = "lenticular.generate_calibration"
    bl_label = "Generate Calibration Coupons"
    bl_description = "Create a centered source coupon, matching 16-bit heightmap variants, and a calibration index CSV"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            folder, count, source_path, csv_path = _generate_calibration_coupon_set(settings)
            _set_status(settings, f"Calibration set created: {count} variants in {folder.name}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            _set_status(settings, "Calibration generation failed: " + str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_open_calibration_folder(Operator):
    bl_idname = "lenticular.open_calibration_folder"
    bl_label = "Open Calibration Folder"
    bl_description = "Open the most recently generated calibration folder"

    def execute(self, context):
        settings = context.scene.lenticular_sync
        path = Path(bpy.path.abspath(settings.calibration_last_folder or ""))
        if not path.is_dir():
            self.report({'WARNING'}, "No generated calibration folder is available yet")
            return {'CANCELLED'}
        try:
            bpy.ops.wm.path_open(filepath=str(path))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_import_reference_heightmap(Operator, ImportHelper):
    bl_idname = "lenticular.import_reference_heightmap"
    bl_label = "Import Reference Heightmap"
    filter_glob: StringProperty(default="*.png;*.tif;*.tiff", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            previous = _state["applying"]
            _state["applying"] = True
            try:
                settings.reference_heightmap_path = str(Path(self.filepath).resolve())
                settings.reference_heightmap_detection = "Automatic"
                settings.reference_heightmap_pitch_px = 0
                settings.reference_heightmap_phase_pitch = 0
                info = _analyze_reference_heightmap(settings)
                settings.reference_heightmap_width_mm = info.get("width_mm") or settings.width_mm
                settings.reference_heightmap_height_mm = info.get("height_mm") or settings.height_mm
                settings.reference_heightmap_thickness_mm = info.get("scale_mm") or settings.thickness_mm or 1.86
                settings.reference_heightmap_show = True
            finally:
                _state["applying"] = previous
            _reference_heightmap_changed(settings, context)
            _sync_reference_preview(context)
            _set_status(settings, info["message"])
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_analyze_reference_heightmap(Operator):
    bl_idname = "lenticular.analyze_reference_heightmap"
    bl_label = "Detect Lens Spacing"
    def execute(self, context):
        settings = context.scene.lenticular_sync
        settings.reference_heightmap_detection = "Automatic"
        _reference_heightmap_changed(settings, context)
        _set_status(settings, _reference_info(settings).get("message", "Detection complete"))
        return {'FINISHED'}


class LENTICULAR_OT_use_reference_heightmap(Operator):
    bl_idname = "lenticular.use_reference_heightmap"
    bl_label = "Build from Heightmap"
    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            info = _analyze_reference_heightmap(settings)
            _validate_heightmap_build(settings, info, require_sources=False)
            previous = _state["applying"]
            _state["applying"] = True
            try:
                settings.workflow = "HEIGHTMAP"
                settings.reference_heightmap_show = False
                settings.phase_pitch = 0
            finally:
                _state["applying"] = previous
            _apply_imported_heightmap_settings(settings)
            _queue_reactive(settings, context, "images", rebuild_interlace=True, rebuild_lens=True, refresh_texture=True)
            _set_status(settings, "Building from imported heightmap" if len(settings.source_frames)>=2 else "Add at least two source images to build the matching interlace")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_preview_reference_heightmap(Operator):
    bl_idname = "lenticular.preview_reference_heightmap"
    bl_label = "Preview Reference Heightmap"
    def execute(self, context):
        settings = context.scene.lenticular_sync
        try:
            _analyze_reference_heightmap(settings)
            settings.reference_heightmap_show = True
            _sync_reference_preview(context)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class LENTICULAR_OT_clear_reference_heightmap(Operator):
    bl_idname = "lenticular.clear_reference_heightmap"
    bl_label = "Clear Reference Preview"
    def execute(self, context):
        settings = context.scene.lenticular_sync
        previous = _state["applying"]
        active = settings.workflow == "HEIGHTMAP"
        _state["applying"] = True
        try:
            settings.reference_heightmap_path = ''
            settings.reference_heightmap_info_json = '{}'
            settings.reference_heightmap_show = False
            if active: settings.workflow = "SOURCE_FRAMES"
        finally:
            _state["applying"] = previous
        _remove_reference_collection()
        _state["reference_preview_key"] = None
        _queue_reactive(settings, context, "images" if active else "reference", rebuild_interlace=active, rebuild_lens=active, refresh_texture=active)
        return {'FINISHED'}


def _ui_workflow_tab(settings):
    """Map saved page choices onto three visible tabs without changing project state.

    Preserve all ui_workspace enum numbers for saved .blend files. Legacy Images
    joins Project; legacy Calibration joins Optics. No migration writes, rebuild
    requests, or sync messages are generated by navigation or drawing panels.
    """
    value = getattr(settings, "ui_workspace", "PROJECT")
    if value in {"OPTICS", "CALIBRATION"}:
        return "OPTICS"
    if value in {"OUTPUT", "PREVIEW"}:
        return "OUTPUT"
    return "PROJECT"


def _ui_sidebar_width(context):
    """Return the sidebar's available width in UI coordinates, including UI zoom."""
    region = getattr(context, "region", None)
    width = float(getattr(region, "width", 360))
    try:
        a = region.view2d.region_to_view(0, 0)
        b = region.view2d.region_to_view(int(width), 0)
        width = abs(float(b[0]) - float(a[0]))
    except Exception:
        pass
    return width


class LENTICULAR_PT_panel(Panel):
    bl_label = "Lenticulizer"
    bl_idname = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"

    def draw(self, context):
        settings = context.scene.lenticular_sync
        layout = self.layout
        try:
            if context.area is not None:
                _state["panel_area_ptr"] = context.area.as_pointer()
        except Exception:
            pass
        tabs = (("PROJECT", "Project & Images"),
                ("OPTICS", "Optics & Calibration"), ("OUTPUT", "Output"))
        width = _ui_sidebar_width(context)
        groups = (tabs,) if width >= 520 else ((tabs[:2], tabs[2:]) if width >= 360 else tuple((tab,) for tab in tabs))
        active_tab = _ui_workflow_tab(settings)
        tab_column = layout.column(align=True)
        for group in groups:
            row = tab_column.row(align=True)
            row.scale_y = 1.15
            for value, label in group:
                # Use the loaded alias for the active tab so native button
                # highlighting also works in scenes saved on Images/Calibration.
                displayed_value = settings.ui_workspace if active_tab == value else value
                row.prop_enum(settings, "ui_workspace", displayed_value, text=label)
        layout.separator(factor=0.5)
        layout.label(text="Settings Mode")
        modes = (("AUTOMATIC", "Automatic"), ("SEMI", "Semi-Automatic"), ("MANUAL", "Manual"))
        mode_groups = (modes,) if width >= 330 else ((modes[:2], modes[2:]) if width >= 250 else tuple((mode,) for mode in modes))
        mode_column = layout.column(align=True)
        for group in mode_groups:
            row = mode_column.row(align=True)
            row.scale_y = 1.10
            for value, label in group:
                # These are the original shared setting and update callback.
                row.prop_enum(settings, "settings_mode", value, text=label)
        row = layout.row()
        row.label(text=settings.status or "Ready", icon="INFO")


class LENTICULAR_PT_project(Panel):
    bl_label = "Project & Sync"
    bl_idname = "LENTICULAR_PT_project"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "PROJECT"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        version_row = layout.row()
        version_row.alignment = 'RIGHT'
        version_row.label(text="Lenticulizer v" + ".".join(str(part) for part in ADDON_VERSION))
        layout.prop(settings, "project_file", text="Project")
        row = layout.row(align=True)
        row.operator("lenticular.find_project", text="Find Current")
        row.operator("lenticular.create_project", text="Create Project", icon="NEWFOLDER")
        close_row = layout.row()
        close_row.scale_y = 1.15
        close_row.operator("lenticular.disconnect", text="Close Project", icon="X")
        row = layout.row(align=True)
        row.operator("lenticular.pull", text="Import From App")
        row.operator("lenticular.send", text="Send To App")
        row = layout.row(align=True)
        row.prop(settings, "auto_sync")
        row.prop(settings, "auto_rebuild", text="Live Update")
        if not _state.get("session_connected", False) and not settings.project_file:
            layout.label(text="No active project connected", icon="INFO")


class LENTICULAR_PT_build(Panel):
    bl_label = "Project Setup"
    bl_idname = "LENTICULAR_PT_build"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "PROJECT"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        layout.prop(settings, "output_mode", text="Output mode")
        layout.prop(settings, "printer_dpi", text="Printer DPI")
        size_col = layout.column(align=True)
        size_col.prop(settings, "width_mm", text="Width")
        size_col.prop(settings, "height_mm", text="Height")
        layout.prop(settings, "orientation", text=("Stripe Direction" if settings.output_mode == "RELIEF" else "Lens Direction"))


class LENTICULAR_PT_images(Panel):
    bl_label = "Source Images & Imports"
    bl_idname = "LENTICULAR_PT_images"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "PROJECT"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync

        workflow_row = layout.row(align=True)
        op = workflow_row.operator("lenticular.set_workflow", text="Build from Source Images", depress=settings.workflow == "SOURCE_FRAMES")
        op.workflow = "SOURCE_FRAMES"
        op = workflow_row.operator("lenticular.set_workflow", text="Use Existing Interlaced Image", depress=settings.workflow == "EXISTING_INTERLACED")
        op.workflow = "EXISTING_INTERLACED"
        map_row = layout.row()
        map_row.enabled = bool(settings.reference_heightmap_path)
        map_row.operator("lenticular.use_reference_heightmap", text="Build from Heightmap", depress=settings.workflow == "HEIGHTMAP")
        if settings.workflow == "HEIGHTMAP": layout.label(text="Geometry comes from Reference Heightmap", icon="INFO")

        if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
            source_box = layout.box()
            source_header = source_box.row(align=True)
            source_header.prop(
                settings,
                "source_image_list_expanded",
                text="",
                icon="TRIA_DOWN" if settings.source_image_list_expanded else "TRIA_RIGHT",
                emboss=False,
            )
            source_header.label(text=f"Source Images ({len(settings.source_frames)})")
            source_header.operator("lenticular.add_source_images", text="Add Images", icon="ADD")
            if settings.source_image_list_expanded:
                if len(settings.source_frames):
                    # Keep every source visible while expanded.  Blender does
                    # not enlarge an operator's icon when a button is made taller, so
                    # use a real preview thumbnail beside a full-height selection
                    # button.  The two elements form one obvious visual row and the
                    # selection target now lines up with the thumbnail instead of
                    # becoming a thin strip.
                    active_index = max(0, min(int(settings.source_frame_index), len(settings.source_frames) - 1))
                    vertical = settings.orientation == "VERTICAL"
                    source_list = source_box.column(align=False)
                    for index, item in enumerate(settings.source_frames):
                        slot = _source_frame_position_label(index, len(settings.source_frames), vertical)
                        filename = item.display_name or Path(item.path).name or f"Image {index + 1}"
                        icon_id = _image_icon_id(settings, item.path)
                        item_box = source_list.box()
                        row = item_box.row(align=True)

                        thumb_col = row.column(align=True)
                        if icon_id:
                            try:
                                thumb_col.template_icon(icon_value=int(icon_id), scale=4.0)
                            except Exception:
                                thumb_col.label(text="", icon_value=int(icon_id))
                        else:
                            thumb_col.label(text="", icon="IMAGE_DATA")

                        select_col = row.column(align=True)
                        select_col.scale_y = 2.8
                        op = select_col.operator(
                            "lenticular.select_source_image",
                            text=f"{slot}    {filename}",
                            depress=(index == active_index),
                        )
                        op.index = index

                    controls_row = source_box.row(align=True)
                    controls_row.operator("lenticular.add_source_images", text="Add", icon="ADD")
                    controls_row.operator("lenticular.remove_source_image", text="Remove", icon="REMOVE")
                    up = controls_row.operator("lenticular.move_source_image", text="Up", icon="TRIA_UP"); up.direction = -1
                    down = controls_row.operator("lenticular.move_source_image", text="Down", icon="TRIA_DOWN"); down.direction = 1
                    source_box.operator("lenticular.clear_source_images", text="Clear List")
                else:
                    source_box.label(text="No source images. Use Add Images to begin.", icon="INFO")
                source_box.label(text=f"Source views: {len(settings.source_frames)}")
                if settings.orientation == "HORIZONTAL":
                    source_box.label(text="Order: Top to Bottom")
                else:
                    source_box.label(text="Order: Left to Right")
                if len(settings.source_frames) % 2 == 1 and len(settings.source_frames) > 0:
                    source_box.label(text=f"Center / straight-on view: {settings.source_frames[len(settings.source_frames)//2].display_name}")

        if settings.workflow == "EXISTING_INTERLACED":
            interlace_box = layout.box()
            action_row = interlace_box.row(align=True)
            action_row.scale_y = 1.15
            action_row.operator("lenticular.import_interlaced", text=("Replace Interlaced Image" if settings.interlaced_image else "Import Existing Interlaced Image"), icon="IMAGE_DATA")
            if not settings.interlaced_image:
                interlace_box.label(text="No interlaced image loaded", icon="IMAGE_DATA")


class LENTICULAR_PT_optical(Panel):
    bl_label = "Calculated UV Print Settings"
    bl_idname = "LENTICULAR_PT_optical"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS" and context.scene.lenticular_sync.output_mode == "LENTICULAR"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        calculated = layout
        display_peak = float(settings.thickness_mm)
        display_base = float(settings.base_mm)
        display_angle = float(settings.viewing_angle_deg)
        theory_over_limit = False
        angle_over_limit = False
        angle_under_limit = False
        if _custom_viewing_angle_active(settings):
            required_peak = _peak_for_viewing_angle(settings, settings.custom_viewing_angle_deg)
            display_peak = required_peak
            display_angle = float(settings.custom_viewing_angle_deg)
            if _uses_theoretical_optics(settings):
                exact_base = _theoretical_base_for_peak_mm(settings, settings.lpi, required_peak)
                display_base = max(0.0, exact_base) if exact_base >= 0.0 else 0.0
            else:
                display_base = _recommended_base_for_peak(settings.lpi, min(MAX_PEAK_MM, max(0.0, required_peak)))
            angle_over_limit = required_peak > MAX_PEAK_MM + 1e-6
            angle_under_limit = 0.0 < required_peak < MIN_NONZERO_PEAK_MM - 1e-6
            if _uses_theoretical_optics(settings) and required_peak + 1e-6 < _theoretical_minimum_peak_mm(settings):
                angle_under_limit = True
            if _uses_theoretical_optics(settings):
                exact_valley = _theoretical_base_for_peak_mm(settings, settings.lpi, required_peak)
                if 0.0 < exact_valley < MIN_NONZERO_BASE_MM - 1e-6:
                    angle_under_limit = True
        elif _uses_theoretical_optics(settings):
            required_peak = _theoretical_optimal_peak_mm(settings)
            if required_peak > MAX_PEAK_MM + 1e-6:
                theory_over_limit = True
                display_peak = required_peak
                exact_base = _theoretical_base_for_selected_peak(settings, settings.lpi, required_peak)
                display_base = max(0.0, exact_base)
                display_angle = _theoretical_viewing_angle_for_peak(settings, required_peak)

        row = calculated.row(align=True)
        if theory_over_limit or angle_over_limit or angle_under_limit:
            row.alert = True
            row.label(text="REQUIRED OPTICAL THICKNESS")
            state_text = "OVER LIMIT" if angle_over_limit or theory_over_limit else "NOT PRINTABLE"
            row.label(text=f"{display_peak:.3f} mm - {state_text}", icon="ERROR")
        else:
            row.label(text=("SET UV PRINTER THICKNESS TO" if settings.output_mode == "LENTICULAR" else "SET UV PRINTER SURFACE THICKNESS TO"))
            row.label(text=f"{display_peak:.3f} mm")

        grid = calculated.grid_flow(columns=2 if _ui_sidebar_width(context) >= 360 else 1, even_columns=True, align=True)
        grid.label(text=f"Valley height: {display_base:.3f} mm")
        grid.label(text=f"Peak height: {display_peak:.3f} mm")
        grid.label(text=f"Surface rise: {max(0.0, display_peak - display_base):.3f} mm")
        grid.label(text=f"Viewing angle: {display_angle:.1f} deg")
        per_image = display_angle / max(1, int(settings.views))
        grid.label(text=f"Approx. angle per image: {per_image:.1f} deg")
        grid.label(text="Print-height limit: 5.00 mm")
        if theory_over_limit or angle_over_limit or angle_under_limit:
            if angle_over_limit or theory_over_limit:
                calculated.label(text="Not printable with the configured 5.00 mm limit.", icon="ERROR")
            else:
                calculated.label(text="The requested angle violates a minimum optical/print-height constraint.", icon="ERROR")
            calculated.label(text="Lens/heightmap generation is blocked until the geometry is feasible.")
        else:
            calculated.label(text=f"Profile: {_resolved_profile_label(settings)}")


class LENTICULAR_PT_relief(Panel):
    bl_label = "Calculated UV Print Settings"
    bl_idname = "LENTICULAR_PT_relief"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS" and context.scene.lenticular_sync.output_mode == "RELIEF"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        spread, base, rise, peak = _relief_required_geometry(settings)
        angles = _relief_facet_angles(settings)
        pitch_mm = 25.4 / max(0.001, float(settings.lpi))
        facet_width_mm = pitch_mm / float(_relief_supported_view_count())

        calculated = layout
        row = calculated.row(align=True)
        row.label(text="SET UV TEXTURE THICKNESS TO")
        row.label(text=f"{peak:.3f} mm")
        grid = calculated.grid_flow(columns=2 if _ui_sidebar_width(context) >= 360 else 1, even_columns=True, align=True)
        grid.label(text="Valley: 0.000 mm")
        grid.label(text=f"Peak: {peak:.3f} mm")
        grid.label(text=f"Relief rise: {rise:.3f} mm")
        grid.label(text=f"Facet spread: {spread:.1f} deg")
        grid.label(text=f"Views: {int(settings.views)}")
        grid.label(text="Height limits: 0.30 to 5.00 mm")
        calculated.label(text="Use the same Prism Height as the UV texture thickness / depth-map height.")


class LENTICULAR_PT_interlace(Panel):
    bl_label = "Interlace & Registration"
    bl_idname = "LENTICULAR_PT_interlace"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 4

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "PROJECT"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        interlace_settings = layout
        interlace_settings.label(text=("Lens-Free Relief: stripes become the color map for matching physical facets." if settings.output_mode == "RELIEF" else "Lenticular Lens mode uses a separate refractive lens heightmap."))

        row = interlace_settings.row(align=True)
        lpi_part = row.row(align=True)
        if settings.output_mode == "RELIEF":
            lpi_part.enabled = settings.settings_mode in {"SEMI", "MANUAL"} and settings.lpi_helper_mode == "MANUAL"
        else:
            lpi_part.enabled = settings.lpi_helper_mode != "RECOMMENDED"
        lpi_part.prop(settings, "lpi", text="LPI")
        views_part = row.row(align=True)
        views_part.enabled = settings.output_mode != "RELIEF"
        views_part.prop(settings, "views", text="Views")

        row = interlace_settings.row(align=True)
        helper_part = row.row(align=True)
        helper_part.enabled = settings.output_mode != "RELIEF" or settings.settings_mode == "SEMI"
        helper_part.prop(settings, "lpi_helper_mode", text="LPI helper")
        preset = row.row(align=True)
        preset.enabled = settings.lpi_helper_mode == "RECOMMENDED" and (settings.output_mode != "RELIEF" or settings.settings_mode == "SEMI")
        preset.prop(settings, "lpi_helper_preset", text="")

        row = interlace_settings.row(align=True)
        row.prop(settings, "build_detail_mode", text="Detail")

        targets = _recommended_lpi_targets(settings)
        key = settings.lpi_helper_preset if settings.lpi_helper_preset in targets else "BALANCED"
        selected_lpi, selected_ppl = targets[key]
        logical_views = _relief_supported_view_count() if settings.output_mode == "RELIEF" else max(1, int(settings.views))
        px_per_view = selected_ppl // logical_views
        unit_label = "px/prism" if settings.output_mode == "RELIEF" else "px/lens"
        sub_label = "px/image" if settings.output_mode == "RELIEF" else "px/view"
        if settings.lpi_helper_mode == "RECOMMENDED":
            interlace_settings.label(text=f"Selected exact LPI: {selected_lpi:.3f} - {selected_ppl} {unit_label} - {px_per_view} {sub_label}")
        else:
            interlace_settings.label(text=f"Manual LPI: {float(settings.lpi):.3f}")
        interlace_settings.label(text=f"Recommended exact values - Easier {targets['EASIER'][0]:.3f} | Balanced {targets['BALANCED'][0]:.3f} | Finer {targets['FINER'][0]:.3f} LPI")
        if settings.output_mode == "RELIEF":
            interlace_settings.label(text="Lens-Free Relief baseline currently supports exactly 2 images and uses Prism Height as the printed depth height.")
            if settings.settings_mode == "SEMI":
                interlace_settings.label(text="Semi-Automatic: change LPI helper/preset, manual LPI, or Prism Height independently; dependent relief geometry recalculates automatically.")

        if settings.build_detail_mode == "CUSTOM":
            interlace_settings.prop(settings, "pixels_per_lenticule", text="Pixels per lenticule")
            effective_ppl = int(settings.pixels_per_lenticule)
        else:
            effective_ppl = _recommended_pixels_per_lenticule(settings)
            interlace_settings.label(text=f"Pixels per lenticule: {effective_ppl}")


        registration = interlace_settings.box()
        registration.label(text="Phase / Registration")
        registration.prop(settings, "phase_pitch", text="Offset (pitch)", slider=True)
        registration.label(text="Align the image with the lens or prism profile.")

        if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
            out_w, out_h = _build_target_canvas_size(settings)
            interlace_settings.label(text=f"Expected output: {out_w} x {out_h} px")
            build_row = interlace_settings.row(align=True)
            build_row.scale_y = 1.25
            build_row.enabled = len(settings.source_frames) >= 2
            build_row.operator("lenticular.build_interlaced", text=("Generate Image" if settings.output_mode == "RELIEF" else "Build Interlaced Image"), icon="SEQ_STRIP_DUPLICATE")
            if len(settings.source_frames) < 2:
                interlace_settings.label(text="Add at least 2 source images to build.", icon="ERROR")


class LENTICULAR_PT_lens_shape(Panel):
    bl_label = "Lens Shape & Optical Base"
    bl_idname = "LENTICULAR_PT_lens_shape"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS" and context.scene.lenticular_sync.output_mode == "LENTICULAR"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        options = layout
        editable = settings.settings_mode != "AUTOMATIC"

        # Lens Type remains selectable in Automatic mode so the user can choose
        # between the calibrated automatic solver and mathematical automatic solver.
        row = options.row()
        row.prop(settings, "lens_profile", text="Lens type")

        row = options.row()
        if settings.settings_mode == "AUTOMATIC" and _resolved_local_profile(settings) not in {"REFERENCE", "THEORETICAL"}:
            row.enabled = False
            row.label(text="Print profile:")
            row.label(text="Automatic for Selected Lens")
        else:
            row.enabled = editable
            row.prop(settings, "print_profile", text="Print profile")

        if editable and settings.print_profile == "MANUAL":
            row = options.row(align=True)
            row.prop(settings, "manual_thickness_value", text="Manual thickness")
            row.prop(settings, "manual_thickness_unit", text="")

        row = options.row()
        if settings.settings_mode == "AUTOMATIC" and _resolved_local_profile(settings) not in {"REFERENCE", "THEORETICAL"}:
            row.enabled = False
            row.label(text="Base:")
            row.label(text="Automatic for Selected Lens")
        else:
            row.enabled = editable
            row.prop(settings, "base_mode", text="Base")

        if editable and settings.base_mode == "MANUAL":
            row = options.row(align=True)
            row.prop(settings, "manual_base_mm", text="Manual base height")
            row.label(text="mm")


        options.label(text="Optical base is part of the clear lens.")


class LENTICULAR_PT_resin_viewing(Panel):
    bl_label = "Resin & Viewing"
    bl_idname = "LENTICULAR_PT_resin_viewing"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        if settings.output_mode == "RELIEF":
            layout.label(text="Lens-Free Relief does not use resin IOR.", icon="INFO")
            layout.label(text="Viewing spread follows the prism geometry.")
            return
        options = layout
        row = options.row()
        row.enabled = True
        row.prop(settings, "ior", text="Clear resin IOR")

        row = options.row()
        row.prop(settings, "viewing_angle_mode", text="Viewing angle")
        if settings.viewing_angle_mode == "CUSTOM":
            row = options.row(align=True)
            row.prop(settings, "custom_viewing_angle_deg", text="Custom angle")
            row.label(text="deg")
        options.label(text=f"Standard recommendation: {_standard_recommended_viewing_angle(settings):.1f} deg")
        options.label(text=f"Target angle ({_viewing_angle_mode_label(settings)}): {_recommended_viewing_angle(settings):.1f} deg")
        if _uses_theoretical_optics(settings):
            options.label(text=f"Maximum printable full-aperture angle: {_mathematical_maximum_feasible_viewing_angle(settings):.1f} deg")


class LENTICULAR_PT_backing(Panel):
    bl_label = "Backing / Support Base"
    bl_idname = "LENTICULAR_PT_backing"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 4

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        layout.prop(settings, "backing_enabled", text="Enable backing / support base")
        if settings.backing_enabled:
            layout.prop(settings, "backing_mm", text="Backing thickness (mm)")
        layout.label(text="Separate support block beneath the image or relief.")
        layout.label(text="Does not change the clear optical lens base.")


class LENTICULAR_PT_prism_shape(Panel):
    bl_label = "Prism Shape & Relief"
    bl_idname = "LENTICULAR_PT_prism_shape"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 3

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS" and context.scene.lenticular_sync.output_mode == "RELIEF"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        spread, base, rise, peak = _relief_required_geometry(settings)
        angles = _relief_facet_angles(settings)
        pitch_mm = 25.4 / max(0.001, float(settings.lpi))
        facet_width_mm = pitch_mm / float(_relief_supported_view_count())

        options = layout
        height_row = options.row()
        height_row.enabled = settings.settings_mode != "AUTOMATIC"
        height_row.prop(settings, "relief_prism_height_mm", text="Prism height (mm)")
        options.label(text="Corrected baseline: 2-image naked-eye prism relief")
        options.label(text=f"Prism pitch: {pitch_mm:.4f} mm at {float(settings.lpi):.3f} LPI")
        options.label(text=f"Supported images / planar facets per prism: {_relief_supported_view_count()}")
        options.label(text=f"Facet width: {facet_width_mm:.4f} mm")
        options.label(text=f"Derived total viewing spread: {spread:.1f} deg")
        if len(angles) > 1:
            options.label(text=f"Average adjacent image separation: {_relief_adjacent_view_deg(settings):.1f} deg")
        options.label(text="Facet normals: " + ", ".join(f"{a:+.1f}" for a in angles) + " deg")
        if int(settings.views) != _relief_supported_view_count():
            options.label(text=f"Current loaded views: {int(settings.views)}. Rebuild or import a 2-view color map for a functional lens-free result.", icon="ERROR")
        options.label(text="Each image stripe is mapped directly to its matching physical facet.")
        options.label(text="No lenticular lens, IOR, optical base, or refractive profile is used.")


class LENTICULAR_PT_output(Panel):
    bl_label = "Generated Files"
    bl_idname = "LENTICULAR_PT_output"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and context.scene.lenticular_sync.ui_workspace == "OUTPUT"

    def draw(self, context):
        layout, settings = self.layout, context.scene.lenticular_sync
        if settings.workflow in {"SOURCE_FRAMES", "HEIGHTMAP"}:
            row = layout.row()
            row.scale_y = 1.2
            row.enabled = len(settings.source_frames) >= 2
            row.operator("lenticular.build_interlaced", text="Generate / Regenerate Image", icon="SEQ_STRIP_DUPLICATE")
            if len(settings.source_frames) < 2:
                layout.label(text="Add source images on Project & Images.", icon="INFO")
        else:
            row = layout.row()
            row.enabled = bool(settings.interlaced_image)
            row.operator("lenticular.rebuild", text="Rebuild from Interlaced Image", icon="FILE_REFRESH")

        dims = _heightmap_dimensions(settings)
        pair = layout.row()
        pair.scale_y = 1.2
        pair.enabled = bool(dims and _project_dir(settings))
        pair.operator("lenticular.export_assets", text="Export Both to Project Folder", icon="EXPORT")
        if dims:
            layout.label(text=f"Output size: {dims[0]} x {dims[1]} px")
        else:
            layout.label(text="Build or import an interlaced image first.", icon="INFO")

        for title, asset, action, button, icon in (
            ("Interlaced image / color map", settings.interlaced_image, "lenticular.export_interlaced", "Export Interlaced Image", "IMAGE_DATA"),
            ("16-bit heightmap / depth map", settings.heightmap_image, "lenticular.export_heightmap", "Export Heightmap", "IMAGE_ZDEPTH"),
        ):
            box = layout.box()
            box.label(text=title, icon=icon)
            box.label(text=Path(asset).name if asset else "Not generated")
            row = box.row()
            row.enabled = bool(dims)
            row.operator(action, text=button, icon="EXPORT")
        layout.label(text="The image editors display the generated files.", icon="INFO")


class LENTICULAR_PT_test_output(Panel):
    bl_label = "Labeled Test Print"
    bl_idname = "LENTICULAR_PT_test_output"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and context.scene.lenticular_sync.ui_workspace == "OUTPUT"

    def draw(self, context):
        settings, layout = context.scene.lenticular_sync, self.layout
        layout.prop(settings, "test_output_name", text="Test name (optional)")
        row = layout.row()
        row.scale_y = 1.2
        row.enabled = _test_export_ready(settings)
        row.operator("lenticular.export_test_set", text="Export Labeled Test Set...", icon="EXPORT")
        layout.label(text="Settings footer below the artwork. Clean files stay unchanged.")
        layout.label(text="Includes a matching heightmap with a zero-height footer.")
        layout.label(text="Print both TEST images at 100% scale; the canvas is taller.", icon="INFO")
        if not _test_export_ready(settings):
            layout.label(text="Generate the matching pair and wait for sync to finish.")


class LENTICULAR_PT_calibration(Panel):
    bl_label = "Calibration Coupons"
    bl_idname = "LENTICULAR_PT_calibration"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 6
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return (
            hasattr(context.scene, "lenticular_sync")
            and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS"
        )

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        if settings.output_mode != "LENTICULAR":
            layout.label(text="Optical calibration requires Lenticular Lens mode.", icon="INFO")
            layout.label(text="Choose the output mode on Project & Images.")
            return
        image_path = _current_interlaced_path(settings)
        if image_path is None or not image_path.is_file():
            warn = layout.box()
            warn.label(text="Build or import an interlaced image first", icon="ERROR")
            warn.label(text="Calibration uses a small centered crop of that image.")
        anchor = layout.box()
        anchor.label(text="Current Optical Anchor")
        row = anchor.row(align=True)
        row.label(text=f"{settings.lpi:.3f} LPI")
        row = anchor.row(align=True)
        row.label(text=f"Peak {settings.thickness_mm:.3f} mm")
        row.label(text=f"Base {settings.base_mm:.3f} mm")
        anchor.label(text="Lens: " + _resolved_profile_label(settings))

        layout.prop(settings, "calibration_mode", text="Test")
        layout.prop(settings, "calibration_coupon_size_mm", text="Coupon Size")
        layout.prop(settings, "calibration_output_dir", text="Output Folder")
        if not settings.calibration_output_dir:
            layout.label(text="Blank output folder = current project folder", icon="INFO")

        variants = _build_calibration_variants(settings)
        preview = layout.box()
        preview.label(text=f"Variants: {len(variants)}")
        summary = _calibration_mode_summary(settings, variants)
        # Keep long summaries readable in the narrow N-panel.
        if len(summary) <= 72:
            preview.label(text=summary)
        else:
            midpoint = summary.rfind(",", 0, 72)
            if midpoint < 20:
                midpoint = 72
            preview.label(text=summary[:midpoint + 1])
            preview.label(text=summary[midpoint + 1:].lstrip())

        help_text = {
            "THICKNESS": "7 focused Thickness variants: current ±0.05, ±0.10, ±0.15 mm. LPI stays fixed.",
            "VIEWING": "5 target viewing-angle variants: 32°, 35°, 38°, 41°, 44°. LPI stays fixed.",
            "ALIGNMENT": "5 registration variants: current Phase ±0.03 and ±0.06 pitch.",
            "LENS_TYPE": "5 shape variants using the current Thickness, Base, LPI, Phase, and IOR.",
        }.get(settings.calibration_mode, "")
        help_box = layout.box()
        for sentence in [part.strip() for part in help_text.split(". ") if part.strip()]:
            help_box.label(text=sentence.rstrip(".") + ".")
        help_box.label(text="Each set includes one reusable source coupon,")
        help_box.label(text="16-bit heightmaps, and calibration_index.csv.")

        button = layout.row()
        button.scale_y = 1.35
        button.enabled = image_path is not None and image_path.is_file() and bool(variants)
        button.operator("lenticular.generate_calibration", text="Generate Calibration Coupons", icon="MODIFIER")
        if settings.calibration_last_folder:
            layout.operator("lenticular.open_calibration_folder", text="Open Last Calibration Folder", icon="FILE_FOLDER")


class LENTICULAR_PT_material(Panel):
    bl_label = "Simulation Material & Lighting"
    bl_idname = "LENTICULAR_PT_material"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "OPTICS"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        layout.prop(settings, "resin_surface_preset", text="Resin Preset")
        layout.prop(settings, "resin_roughness")
        layout.prop(settings, "micro_texture_enabled")
        if settings.micro_texture_enabled:
            row = layout.row(align=True); row.prop(settings, "micro_texture_size_um"); row.label(text="um")
            row = layout.row(align=True); row.prop(settings, "micro_texture_height_um"); row.label(text="um")
        layout.separator()
        layout.prop(settings, "light_power_w")
        layout.prop(settings, "light_angle_deg")


class LENTICULAR_PT_camera(Panel):
    bl_label = "Views"
    bl_idname = "LENTICULAR_PT_camera"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 7
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and context.scene.lenticular_sync.ui_workspace == "OUTPUT"

    def draw(self, context):
        layout = self.layout
        cam_list = _camera_objects()
        settings = context.scene.lenticular_sync
        viewport_areas = _view3d_areas_sorted(context)

        layout.label(text="Target Viewport")
        selector_grid = layout.grid_flow(columns=min(4, max(1, len(viewport_areas))), even_columns=True, align=True)
        selected_area = _selected_view3d_area(context)
        selected_ptr = 0
        try:
            selected_ptr = selected_area.as_pointer() if selected_area is not None else 0
        except Exception:
            selected_ptr = 0
        for viewport_index, viewport_area in enumerate(viewport_areas, 1):
            is_panel = False
            viewport_ptr = 0
            try:
                viewport_ptr = viewport_area.as_pointer()
                is_panel = context.area is not None and context.area.as_pointer() == viewport_ptr
            except Exception:
                pass
            label = f"Viewport {viewport_index}" + (" [Panel]" if is_panel else "")
            op = selector_grid.operator(
                "lenticular.select_target_viewport",
                text=label,
                depress=(selected_ptr != 0 and selected_ptr == viewport_ptr),
            )
            op.viewport_index = viewport_index
        target_row = layout.row(align=True)
        target_row.label(text="Selected: " + _target_viewport_label(context), icon="VIEW3D")
        target_row.operator("lenticular.use_panel_viewport", text="Use Panel Viewport", icon="PINNED")
        layout.label(text="Both control groups affect only the selected viewport.", icon="LOCKED")

        layout.separator()
        layout.label(text="Camera View")
        nav = layout.row(align=True)
        prev_op = nav.operator("lenticular.camera_step", text="Previous", icon="TRIA_LEFT"); prev_op.direction = -1
        nav.operator("lenticular.camera_center", text="Front", icon="CAMERA_DATA")
        next_op = nav.operator("lenticular.camera_step", text="Next", icon="TRIA_RIGHT"); next_op.direction = 1
        if cam_list:
            grid = layout.grid_flow(columns=3, even_columns=True, align=True)
            selected_camera_area = _selected_view3d_area(context)
            for idx, cam in enumerate(cam_list):
                label = _camera_position_label(idx, len(cam_list), context.scene.lenticular_sync.orientation == "VERTICAL")
                active = _area_is_camera_view(context.scene, selected_camera_area, cam)
                op = grid.operator("lenticular.select_camera", text=label, icon="RADIOBUT_ON" if active else "RADIOBUT_OFF")
                op.camera_name = cam.name
            layout.label(text="Camera View enters camera mode only in the selected viewport and also sets the render camera.", icon="INFO")

            layout.separator()
            layout.label(text="Viewport Match")
            layout.label(text="Viewport Match changes only the selected viewport and never changes the render camera.", icon="INFO")
            viewport_nav = layout.row(align=True)
            prev_view = viewport_nav.operator("lenticular.viewport_step", text="Previous", icon="TRIA_LEFT"); prev_view.direction = -1
            viewport_nav.operator("lenticular.viewport_center", text="Front", icon="VIEW3D")
            next_view = viewport_nav.operator("lenticular.viewport_step", text="Next", icon="TRIA_RIGHT"); next_view.direction = 1
            viewport_grid = layout.grid_flow(columns=3, even_columns=True, align=True)
            active_view_name = context.scene.lenticular_sync.active_viewport_camera_name
            for idx, cam in enumerate(cam_list):
                label = _camera_position_label(idx, len(cam_list), context.scene.lenticular_sync.orientation == "VERTICAL")
                active_view = active_view_name == cam.name
                op = viewport_grid.operator("lenticular.viewport_camera", text=label, icon="RADIOBUT_ON" if active_view else "RADIOBUT_OFF")
                op.camera_name = cam.name
            layout.label(text="The print stands upright in Front view. Vertical stripes use left/right viewing. Horizontal stripes use down/up viewing.", icon="INFO")
        else:
            layout.label(text="No view cameras yet - build or rebuild the lens scene", icon="INFO")


class LENTICULAR_PT_reference_heightmap(Panel):
    bl_label = "Reference Heightmap"
    bl_idname = "LENTICULAR_PT_reference_heightmap"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 5
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and _ui_workflow_tab(context.scene.lenticular_sync) == "PROJECT"

    def draw(self, context):
        layout, settings = self.layout, context.scene.lenticular_sync
        row=layout.row(align=True)
        row.operator("lenticular.import_reference_heightmap", text="Import Heightmap", icon="IMAGE_ZDEPTH")
        if not settings.reference_heightmap_path:
            layout.label(text="Import a grayscale PNG or TIFF")
            return
        row.operator("lenticular.clear_reference_heightmap", text="Clear", icon="X")
        _draw_image_thumbnail(layout, settings, settings.reference_heightmap_path, "Reference Heightmap", scale=4.0)
        info = _reference_info(settings)
        layout.label(text=Path(settings.reference_heightmap_path).name)
        layout.prop(settings,"reference_heightmap_width_mm",text="Width (mm)")
        layout.prop(settings,"reference_heightmap_height_mm",text="Height (mm)")
        layout.prop(settings,"reference_heightmap_thickness_mm")
        layout.prop(settings,"reference_heightmap_detection")
        col=layout.column(align=True)
        col.enabled=settings.reference_heightmap_detection == "Manual"
        col.prop(settings,"reference_heightmap_orientation",text="Lens Direction")
        col.prop(settings,"reference_heightmap_pitch_px")
        col.prop(settings,"reference_heightmap_phase_pitch",text="Reference registration (pitch)")
        if info.get("ok"):
            layout.label(text=f"Detected: {info.get('pitch_px',0):.6f} pixels/lens")
            layout.label(text=f"Confidence: {info.get('confidence',0)*100:.0f}%")
        else:
            layout.label(text="Detection needs review", icon="ERROR")
            layout.label(text="Set Manual direction, pitch and registration")
        if not info.get("width_mm") or not info.get("height_mm"):
            layout.label(text="No size metadata: verify physical dimensions", icon="INFO")
        if not info.get("scale_mm"):
            layout.label(text="No height scale: verify white-level height", icon="INFO")
        layout.prop(settings,"reference_heightmap_display_style",text="Display")
        layout.prop(settings,"reference_heightmap_show")
        row=layout.row(align=True)
        row.operator("lenticular.analyze_reference_heightmap",text="Detect Again")
        row.operator("lenticular.use_reference_heightmap",text="Build from Heightmap",depress=settings.workflow=="HEIGHTMAP")
        layout.label(text="Black = zero; white = entered height")
        layout.label(text="Original heightmap is preserved")


class LENTICULAR_PT_render(Panel):
    bl_label = "Render"
    bl_idname = "LENTICULAR_PT_render"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 8
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.scene, "lenticular_sync") and context.scene.lenticular_sync.ui_workspace == "OUTPUT"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lenticular_sync
        row = layout.row(align=True)
        row.operator("lenticular.rebuild", text="Rebuild Lens Scene")
        row.operator("lenticular.render_current", text="Render Current View")
        grid = layout.grid_flow(columns=2, even_columns=True, align=True)
        grid.prop(settings, "render_samples", text="Samples")
        grid.prop(settings, "render_width", text="Width")
        grid.prop(settings, "render_height", text="Height")
        layout.operator("lenticular.render_all", text="Render All Views")


class LENTICULAR_PT_help(Panel):
    bl_label = "Help & About"
    bl_idname = "LENTICULAR_PT_help"
    bl_parent_id = "LENTICULAR_PT_sync_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_order = 99
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Lenticulizer Blender Add-on v" + ".".join(str(part) for part in ADDON_VERSION), icon="INFO")
        layout.label(text="Use with Lenticulizer 3D Alpha 30 (or compatible earlier builds).")
        layout.label(text="Expand the sections below for usage help.")


class LENTICULAR_PT_help_quickstart(Panel):
    bl_label = "Quick Start"
    bl_idname = "LENTICULAR_PT_help_quickstart"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="1. Project & Images: connect and set print size.")
        layout.label(text="2. Add images, set view order and registration.")
        layout.label(text="3. Optics & Calibration: set lens, prism and backing.")
        layout.label(text="4. Expand Calibration there for test coupons.")
        layout.label(text="5. Output: generate, inspect and export files.")
        layout.label(text="Settings Mode buttons are shared across all tabs.")


class LENTICULAR_PT_help_images(Panel):
    bl_label = "Images & View Order"
    bl_idname = "LENTICULAR_PT_help_images"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Use Project & Images for image inputs and ordering.")
        layout.label(text="Phase is under Interlace & Registration.")
        layout.label(text="Source order controls which view is seen by angle.")
        layout.label(text="Vertical lenses use left-to-right ordering.")
        layout.label(text="Horizontal lenses use top-to-bottom ordering.")
        layout.label(text="Use Add, Remove, Up and Down to manage the list.")
        layout.label(text="The top Image Editor follows the selected source.")
        layout.label(text="Bottom-left shows the interlaced image.")
        layout.label(text="Bottom-right shows the height/depth map.")


class LENTICULAR_PT_help_optics(Panel):
    bl_label = "Optics & Inspection"
    bl_idname = "LENTICULAR_PT_help_optics"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="IOR appears once, under Resin & Viewing.")
        layout.label(text="Calibration expands within Optics & Calibration.")
        layout.label(text="Automatic chooses recommended optical values.")
        layout.label(text="Semi-Automatic exposes selected adjustments.")
        layout.label(text="Manual gives direct control of supported values.")
        layout.label(text="Use the lens/prism inspection viewports for profile detail.")
        layout.label(text="Use the main 3D viewport for overall viewing behavior.")
        layout.label(text="IOR affects lenticular refraction and lens geometry.")
        layout.label(text="Backing / support base is optional; thickness is remembered.")
        layout.label(text="Disabling backing does not change the lens base or heightmap.")


class LENTICULAR_PT_help_sync(Panel):
    bl_label = "App Sync & Projects"
    bl_idname = "LENTICULAR_PT_help_sync"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Import From App pulls the current desktop project state.")
        layout.label(text="Send To App publishes Blender-side setting changes.")
        layout.label(text="Auto Sync keeps connected projects synchronized.")
        layout.label(text="Live Update rebuilds the Blender scene when needed.")
        layout.label(text="Close Project disconnects the current live project.")
        layout.label(text="Use one Lenticulizer sync add-on at a time.")


class LENTICULAR_PT_help_troubleshooting(Panel):
    bl_label = "Troubleshooting"
    bl_idname = "LENTICULAR_PT_help_troubleshooting"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Wrong view order: verify source order and lens direction.")
        layout.label(text="Stale output: generate the image pair again.")
        layout.label(text="No app sync: verify the same project is connected.")
        layout.label(text="Unexpected scene: use the app's Reset Project Scene.")
        layout.label(text="Heightmap import: verify physical size and white height.")
        layout.label(text="If a project was closed, reconnect it explicitly.")


class LENTICULAR_PT_help_about(Panel):
    bl_label = "About, License & Attributions"
    bl_idname = "LENTICULAR_PT_help_about"
    bl_parent_id = "LENTICULAR_PT_help"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Lenticulizer"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.label(text="Lenticulizer prepares lenticular and lens-free print assets.")
        layout.label(text="Desktop compatibility: Lenticulizer 3D Alpha 30.")
        layout.separator()
        layout.label(text="Blender add-on license: GPL-3.0-or-later.")
        layout.label(text="Desktop app licensing is shown in the app Help page.")
        layout.separator()
        layout.label(text="Blender integration uses Blender's supported Python API.")
        layout.label(text="Blender is separate software from the Blender Foundation.")
        layout.label(text="Desktop runtime notices are available inside the app.")


classes = (
    LenticularSourceFrame,
    LenticularSyncSettings,
    LENTICULAR_OT_apply_workspace_layout,
    LENTICULAR_OT_open_image_viewer,
    LENTICULAR_OT_preview_zoom,
    LENTICULAR_OT_create_project,
    LENTICULAR_OT_add_source_images,
    LENTICULAR_OT_select_source_image,
    LENTICULAR_OT_remove_source_image,
    LENTICULAR_OT_move_source_image,
    LENTICULAR_OT_clear_source_images,
    LENTICULAR_OT_import_interlaced,
    LENTICULAR_OT_set_workflow,
    LENTICULAR_OT_build_interlaced,
    LENTICULAR_OT_export_interlaced,
    LENTICULAR_OT_export_heightmap,
    LENTICULAR_OT_export_assets,
    LENTICULAR_OT_export_test_set,
    LENTICULAR_OT_generate_calibration,
    LENTICULAR_OT_open_calibration_folder,
    LENTICULAR_OT_import_reference_heightmap,
    LENTICULAR_OT_analyze_reference_heightmap,
    LENTICULAR_OT_use_reference_heightmap,
    LENTICULAR_OT_preview_reference_heightmap,
    LENTICULAR_OT_clear_reference_heightmap,
    LENTICULAR_OT_select_camera,
    LENTICULAR_OT_camera_step,
    LENTICULAR_OT_camera_center,
    LENTICULAR_OT_select_target_viewport,
    LENTICULAR_OT_use_panel_viewport,
    LENTICULAR_OT_viewport_camera,
    LENTICULAR_OT_viewport_step,
    LENTICULAR_OT_viewport_center,
    LENTICULAR_OT_find_project,
    LENTICULAR_OT_pull,
    LENTICULAR_OT_send,
    LENTICULAR_OT_disconnect,
    LENTICULAR_OT_rebuild,
    LENTICULAR_OT_render_current,
    LENTICULAR_OT_render_all,
    LENTICULAR_PT_panel,
    LENTICULAR_PT_project,
    LENTICULAR_PT_images,
    LENTICULAR_PT_build,
    LENTICULAR_PT_optical,
    LENTICULAR_PT_relief,
    LENTICULAR_PT_interlace,
    LENTICULAR_PT_lens_shape,
    LENTICULAR_PT_resin_viewing,
    LENTICULAR_PT_backing,
    LENTICULAR_PT_prism_shape,
    LENTICULAR_PT_output,
    LENTICULAR_PT_test_output,
    LENTICULAR_PT_calibration,
    LENTICULAR_PT_material,
    LENTICULAR_PT_camera,
    LENTICULAR_PT_reference_heightmap,
    LENTICULAR_PT_render,
    LENTICULAR_PT_help,
    LENTICULAR_PT_help_quickstart,
    LENTICULAR_PT_help_images,
    LENTICULAR_PT_help_optics,
    LENTICULAR_PT_help_sync,
    LENTICULAR_PT_help_troubleshooting,
    LENTICULAR_PT_help_about,
)


def _start_viewport_tracker():
    if _state.get("viewport_tracker_running", False):
        return None
    try:
        wm = bpy.context.window_manager
        if wm is None:
            return 0.5
        for window in wm.windows:
            screen = window.screen
            if screen is None:
                continue
            for area in screen.areas:
                if area.type != "VIEW_3D":
                    continue
                region = _view3d_window_region(area)
                if region is None:
                    continue
                try:
                    with bpy.context.temp_override(window=window, area=area, region=region):
                        bpy.ops.lenticular.viewport_tracker('INVOKE_DEFAULT')
                    if _state.get("viewport_tracker_running", False):
                        return None
                except Exception:
                    continue
    except Exception:
        pass
    # Try again shortly if Blender was still initializing the workspace.
    return 0.5


def register():
    _ensure_preview_collection()
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lenticular_sync = PointerProperty(type=LenticularSyncSettings)
    if not bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.register(_timer_callback, first_interval=0.5, persistent=True)


def unregister():
    global _preview_collection
    if _preview_collection is not None:
        try:
            bpy.utils.previews.remove(_preview_collection)
        except Exception:
            pass
        _preview_collection = None
    if bpy.app.timers.is_registered(_timer_callback):
        bpy.app.timers.unregister(_timer_callback)
    if bpy.app.timers.is_registered(_run_output_mode_rebuild_once):
        bpy.app.timers.unregister(_run_output_mode_rebuild_once)
    _state["mode_rebuild_timer_registered"] = False
    if hasattr(bpy.types.Scene, "lenticular_sync"):
        del bpy.types.Scene.lenticular_sync
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
