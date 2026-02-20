# SPEC: Video Visualization & Comparison Tool

**Project:** Batch Renderer  
**Owner:** wolfgang.paier@pipio.ai  
**Date:** <2026-02-19>  
**Status:** Implemented  
**Target Repo Path:** `./visualization/`

---

## 1) Objective

Build a Python UI tool for side-by-side visual comparison of one or more videos.
The tool supports interactive scrubbing, per-video filters, audio playback,
and export of the composed comparison view. All UI actions are also available
via CLI for headless / scripted workflows.

---

## 2) Scope

### In scope

- Desktop GUI for loading, viewing, and comparing videos side-by-side.
- Interactive frame-accurate scrubbing (mouse + keyboard).
- Per-video visualization filters (starting with a difference-heatmap).
- Synchronized audio playback from a selectable source video.
- Export of the composed side-by-side view to a video file.
- Full CLI interface mirroring all UI actions.

### Out of scope

- Video editing (trimming, cutting, compositing beyond side-by-side).
- Streaming / network video sources.
- Multi-window or detachable panel layouts.

---

## 3) Users & Primary Use Case

**User:** ML engineer / content pipeline operator  
**Use case:** "Compare rendered video outputs against a reference to verify quality, apply a difference heatmap to highlight artifacts, and export the comparison for review."

---

## 4) Proposed Module Structure

```
visualization/
    visualize.py              # main entry point (CLI parsing + UI launch)
    __init__.py
    ui/
        __init__.py
        main_window.py        # top-level window, menu bar, status bar, layout
        video_canvas.py       # composite canvas rendering all video panels
        context_menu.py       # right-click context menu on a video panel
        filter_dialog.py      # filter selection & configuration dialog
        export_dialog.py      # export settings dialog
    core/
        __init__.py
        video_manager.py      # video loading, decoding, frame cache, ID assignment
        audio_player.py       # audio extraction, playback, sync
        exporter.py           # side-by-side export rendering
    filters/
        __init__.py           # filter registry & base class
        base.py               # abstract base filter
        difference_heatmap.py # pixel-difference heatmap filter
```

---

## 5) Inputs / Outputs

### Inputs (GUI)

| Action | Description |
|--------|-------------|
| Drag-and-drop | Drop one or more video files onto the window to load them. |
| File → Load Videos | Opens a multi-file dialog to select videos. |
| View → Clear Videos | Unloads all currently opened videos. |
| Export (menu) | Opens a save-file dialog, then triggers export. |
| Scroll bar / Left-Right keys | Scrub to an arbitrary frame position. |
| Right-click context menu | Per-video actions (caption, filter, audio source). |

### Inputs (CLI)

| Flag | Description | Default |
|------|-------------|---------|
| `--videos` | One or more paths to video files to load | – |
| `--captions` | Comma-separated list of custom captions (positional, matching `--videos` order) | filenames |
| `--filters` | Per-video filter specification, e.g. `0:none,1:diff_heatmap:ref=0` | none |
| `--audio_source` | Video ID to use as audio source | `0` |
| `--export` | Output path for export; triggers headless export and exit | – |
| `--export_width` | Export width in pixels (height computed from aspect ratio) | max input width |
| `--export_height` | Export height in pixels (width computed from aspect ratio) | max input height |
| `--rows` | Number of rows for the video grid layout | `1` |
| `--no_gui` | Run headless (CLI-only export, no window) | `false` |

### Outputs

- Interactive UI window displaying videos side-by-side.
- Exported `.mp4` video file of the composed view.

---

## 6) Functional Requirements

### FR-1 Video Loading

- Videos are loaded via drag-and-drop onto the window **or** via the File → Load Videos menu entry which opens a multi-file dialog.
- Each loaded video is assigned a sequential **video ID** starting at `0`.
- All loaded videos **must** share the same frame rate. If a newly loaded video has a different frame rate from the already loaded set, the tool shall reject it and show an error message.
- There is no maximum number of simultaneously loaded videos.

### FR-2 Video Display

- Videos are displayed **side-by-side in a single row** by default. The number of rows is configurable via the View menu and the `--rows` CLI flag.
- Videos with different resolutions are resized (aspect-ratio preserving) so that all panels have the **same height**.
- Each video panel displays a **label** centered at the top of the panel. The default label is the video's ID followed by a colon and the filename including extension (e.g. `0: clip_v2v_seed42.mp4`).
- Label font size is **auto-scaled** to fit within the panel width when the text is too long. The font shrinks down to a minimum readable size to prevent overflow.

### FR-3 Scrubbing & Navigation

- A horizontal scroll bar at the bottom of the window represents the full video timeline.
- The scroll bar is controllable by mouse (click / drag) and by Left / Right arrow keys.
- Pressing Left / Right shall advance by exactly **one frame** in the respective direction.
- The scroll bar range is determined by the **longest** loaded video. If the current position exceeds a shorter video's range, its last frame is shown.
- A **play / pause button** and a **playback speed input field** are placed to the left of the scroll bar.
- No additional keyboard shortcuts beyond Left / Right arrow keys are required.

### FR-4 Status Bar

- A status bar at the bottom of the window (above or integrated with the scroll bar) displays:
  - Current **frame number** (0-based).
  - Current **video time** in `MM:SS.mmm` format.

### FR-5 Resizable Window

- The window is freely resizable. Video panels scale proportionally to fill the available width.

### FR-6 Video Context Menu

Right-clicking on a video panel opens a context menu with the following entries:

| Entry | Behaviour |
|-------|-----------|
| **Set Caption** | Opens a text-input dialog pre-filled with the current label. User edits and confirms to update the label. |
| **Set Filter** | Opens the filter configuration dialog (see FR-8). |
| **Clear Filter** | Removes the filter from this video. **Greyed out / disabled** if no filter is active on the video. |
| **Clear Filter (All)** | Removes filters from all loaded videos. |
| **Reset Zoom** | Resets the ROI zoom to show the full frame (see FR-11). |
| **Set Playback Audio** | Sets the audio source to this video's ID. This entry is **greyed out / disabled** if the video has no audio track. |

### FR-7 Audio Playback

- If any loaded video has an audio track, audio is played in sync with the current frame position.
- Default audio source is the video with **ID 0**. If video 0 has no audio, no audio plays until the user selects a source.
- The audio source is changeable via the context menu (FR-6, "Set Playback Audio").
- Audio remains in sync during frame-by-frame scrubbing: the audio seeks to the matching position and plays a **short snippet** (approximately one frame's worth of audio) so the user hears the corresponding audio content.
- Audio/video synchronisation during continuous playback uses a **wall-clock based** mechanism: the expected frame is computed from real elapsed time rather than fixed timer ticks, so playback maintains real-time speed even when rendering is slow.
- When resuming playback after scrubbing, the audio position is correctly re-synchronised to the current frame.

### FR-8 Visualization Filters

- The filter system is **plugin-based**: a base filter class defines the interface, and concrete filters are registered in a filter registry.
- Initial filter: **Difference Heatmap** — computes per-pixel absolute difference between the current video frame and a reference video frame, mapped to a colour heatmap.
- The filter configuration dialog (opened via FR-6 "Set Filter") contains:
  - A **dropdown / list** of available filters (including "None" to remove a filter).
  - A **configuration panel** on the right side for filter-specific parameters.
- Filters that require a reference video (e.g. Difference Heatmap) show a **reference video selector** listing loaded videos as `<ID>: <label>`. The reference selector **defaults to video 0**.
- An **"Apply to all videos except the reference"** checkbox is available for filters that require a reference. When checked, the filter is applied to every loaded video except the chosen reference.
- Filters are applied per-video; each video can independently have a different filter (or none).
- Filters can be cleared via the context menu (see FR-6) using "Clear Filter" (single video) or "Clear Filter (All)".

#### Filter Base Class Interface

```python
class BaseFilter(ABC):
    name: str                          # display name in the filter list
    def configure(self, params): ...   # apply user-supplied parameters
    def get_config_ui(self) -> Widget: # return Qt widget for config panel
    def apply(self, frame, ref_frame=None) -> ndarray: ...  # process a frame
```

### FR-9 Export

- The Export menu entry opens a **save-file dialog** for the user to choose the output path.
- Export renders the **side-by-side composed view** of all loaded videos into a single output video file.
- Default export resolution: **full resolution** — every video panel is upscaled to the maximum resolution among all loaded videos (aspect-ratio preserving).
- Alternatively, the user may specify a target resolution. The non-specified dimension is computed automatically for aspect-ratio preservation.
- The export draws the current **frame number** in the **top-left corner** of the output video. Text is rendered as **white with a thin black outline** for readability at various resolutions.
- Filters, captions, and the **active ROI zoom** (see FR-11) are all reflected in the export. If an ROI is active, the exported panels show only the cropped region.
- Export codec is **H.264** in an **`.mp4`** container.
- The exported video includes the **audio track** from the currently selected audio source, if one is active.

### FR-11 ROI Zoom, Continuous Zoom & Pan

- The user can **left-click and drag** on any video panel to select a rectangular region of interest.
- The ROI is stored in **normalised coordinates** (0.0–1.0 range) relative to the original frame dimensions, ensuring it applies uniformly to videos of different resolutions.
- When an ROI is active, **all loaded video panels** display only the cropped region instead of the full frame.
- The user can **refine** the zoom by dragging within an already-zoomed view; the selection is mapped back to absolute frame coordinates.
- **Mouse-wheel zoom:** scrolling forward zooms in, scrolling backward zooms out. Zoom is anchored to the cursor position — the point under the cursor remains stationary. Zoom out stops at the original (full-frame) size. The ROI aspect ratio is preserved.
- **Middle-button pan:** pressing and dragging the middle mouse button pans (translates) the ROI across the frame without changing the zoom level. Panning stops at the frame edges and is only active when zoomed in.
- **Reset** the zoom to the full frame by:
  - **Double-clicking** on the canvas, or
  - Selecting **Reset Zoom** from the right-click context menu (FR-6).
- The ROI is applied in the rendering pipeline **before** filters, so filters only process the cropped region (reducing computation).
- The ROI is also reflected in the **export** (FR-9): exported panels show the cropped region.

### FR-10 CLI Interface

- All GUI-accessible functionality shall also be available through CLI flags so the tool can run in a headless / scripted fashion.
- When `--export` is provided with `--no_gui`, the tool loads videos, applies the specified captions and filters, exports, and exits without opening a window.
- CLI filter syntax: `--filters "<video_id>:<filter_name>[:<param>=<value>,...], ..."`.

---

## 7) Non-Functional Requirements

### NFR-1 Performance

- Scrubbing through the video shall be fast and responsive.
- Implementation strategies:
  - Maintain a **frame cache** (LRU, per-video) around the current position to allow instant access to nearby frames.
  - Resize frames for display at screen resolution, not at full resolution, to reduce rendering cost.
  - **Sequential read optimisation:** during continuous playback the video decoder tracks the next expected frame index and skips the expensive `cv2.VideoCapture.set()` seek. A seek is only performed for non-sequential access (e.g. scrubbing, jumping). This prevents the progressive slowdown that would otherwise occur with H.264 seek-from-keyframe on every frame.
  - **Processing pipeline order:** frames are cropped to the active ROI *before* filters are applied and before display-resize, minimising the number of pixels processed by filters and resize operations.

### NFR-2 Portability

- Target platforms: Windows and Linux.
- Use `pathlib` for all file path operations.
- Avoid OS-specific APIs outside of well-abstracted library calls.

### NFR-3 Extensibility

- The filter collection must be easily extendable: adding a new filter should require only creating a new subclass of `BaseFilter` and registering it. No changes to core UI code.

---

## 8) Technology Choices

| Component | Library | Rationale |
|-----------|---------|-----------|
| GUI framework | **PySide6** (Qt 6) | Mature widget toolkit, supports drag-and-drop, context menus, dialogs, and cross-platform. |
| Video decoding | **OpenCV** (`cv2.VideoCapture`) | Fast frame-accurate random access; widely available. |
| Audio playback | **PyAudio** | Low-latency audio output with seek support. |
| Image processing / filters | **NumPy** + **OpenCV** | Efficient per-pixel operations for heatmap and future filters. |
| Video export | **OpenCV** (`cv2.VideoWriter`) | H.264 encoding into `.mp4`. |
| CLI parsing | **argparse** | Stdlib, consistent with project convention. |

---

## 9) UI Layout

```
┌──────────────────────────────────────────────────────────────┐
│  File   View   Export                              [Menu Bar]│
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  caption_0   │  │  caption_1   │  │  caption_2   │       │
│  │              │  │              │  │              │       │
│  │   Video 0    │  │   Video 1    │  │   Video 2    │       │
│  │              │  │              │  │              │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  [▶] [1.0x]  ═══════════════════╪════════════════════════    │
├──────────────────────────────────────────────────────────────┤
│  Frame: 127 / 300    Time: 00:05.080                         │
└──────────────────────────────────────────────────────────────┘
```

- **Menu bar** at the top.
- **Video canvas** occupies the majority of the window; panels arranged left-to-right.
- **Scroll bar** with play/pause and speed controls spans the bottom.
- **Status bar** at the very bottom showing frame number and time.

---

## 10) Error Handling Rules

- **Unsupported file dropped / opened:** show a warning dialog, ignore the file, continue.
- **Frame-rate mismatch on load:** show an error dialog, reject the file, keep existing session intact.
- **Video decode failure mid-session:** show a warning, display a placeholder frame (e.g. black or last-good frame).
- **Audio extraction failure:** log a warning, disable audio for that video.
- **Export failure (disk full, codec error):** show an error dialog with the message.
- **No videos loaded when Export is triggered:** disable / grey out the Export menu entry.

---

## 11) Dependencies

| Dependency | Purpose |
|------------|---------|
| Python 3.9+ | Runtime |
| PySide6 | GUI framework |
| OpenCV (`opencv-python`) | Video decoding, image processing, export |
| NumPy | Frame data manipulation, filter computation |
| PyAudio | Audio playback |
| ffmpeg / ffprobe (on PATH) | Audio track extraction, metadata queries |
| argparse (stdlib) | CLI parsing |

---
