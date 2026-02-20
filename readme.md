# Video Visualization & Comparison Tool

Side-by-side video comparison with interactive scrubbing, per-video filters, ROI zoom, audio playback, and export.

## Requirements

- Python 3.9+
- ffmpeg / ffprobe on PATH

```
pip install -r visualization/requirements.txt
```

## Quick Start

```bash
# Launch the GUI
python -m visualization

# Launch with videos pre-loaded
python -m visualization --videos ref.mp4 render.mp4

# Headless export (no window)
python -m visualization --videos ref.mp4 render.mp4 --export out.mp4 --no_gui
```

## UI Functions

### Loading Videos

- **Drag and drop** video files onto the window.
- **File → Load Videos** opens a multi-file dialog.
- **View → Clear Videos** removes all loaded videos.
- All videos must share the same frame rate.

### Navigation & Playback

- **Scroll bar** at the bottom scrubs to any frame.
- **Left / Right arrow keys** step one frame at a time.
- **Play / Pause button** starts continuous playback.
- **Speed spinner** adjusts playback speed (0.10x – 10.00x).
- The status bar shows the current frame number and time.

### Video Labels

Each video panel displays a label at the top (default: `<ID>: <filename>`).
Right-click a video → **Set Caption** to change it.
Long labels auto-shrink to fit the panel width.

### Filters

Right-click a video → **Set Filter** to open the filter dialog.

- Choose a filter from the dropdown (e.g. **Difference Heatmap**).
- For filters that need a reference, select a reference video (defaults to video 0).
- Check **"Apply to all videos except the reference"** to apply in bulk.
- Right-click → **Clear Filter** removes the filter from one video.
- Right-click → **Clear Filter (All)** removes all filters.

### ROI Zoom & Pan

- **Left-click and drag** on any video to zoom into a region of interest.
- **Mouse wheel** zooms continuously — forward to zoom in, backward to zoom out. The zoom is anchored to the cursor position (the point under the cursor stays fixed). Zoom out stops at the original size.
- **Middle-click and drag** pans the view while zoomed in.
- The zoom applies to all panels in normalised coordinates.
- Drag again within a zoomed view to refine.
- **Double-click** or right-click → **Reset Zoom** to return to the full frame.

### Audio

- Audio from the default source (video 0) plays in sync with the video.
- Right-click a video → **Set Playback Audio** to switch the audio source.
- Frame-by-frame scrubbing plays a short audio snippet at the current position.

### Export

- **Export** (menu bar) opens the export dialog.
- Renders the full side-by-side view (with active filters, labels, ROI crop, and frame number overlay) to an H.264 `.mp4` file.
- Default resolution: full (max input resolution). Custom width/height can be specified.

## CLI Reference

| Flag | Description | Default |
|------|-------------|---------|
| `--videos` | One or more video file paths | – |
| `--captions` | Comma-separated custom captions (positional) | `<ID>: <filename>` |
| `--filters` | Per-video filter spec (see below) | none |
| `--audio_source` | Video ID for audio playback | `0` |
| `--export` | Output file path (triggers export) | – |
| `--export_width` | Export width in pixels | max input width |
| `--export_height` | Export height in pixels | max input height |
| `--rows` | Number of grid rows | `1` |
| `--no_gui` | Headless mode (export and exit, no window) | off |

### Filter Syntax

```
--filters "<video_id>:<filter_name>[:<param>=<value>], ..."
```

Examples:

```bash
# Difference heatmap on video 1, referencing video 0
--filters "1:Difference Heatmap:ref=0"

# Heatmap on videos 1 and 2, both referencing video 0
--filters "1:Difference Heatmap:ref=0, 2:Difference Heatmap:ref=0"
```

### Full Example

```bash
python -m visualization \
    --videos reference.mp4 render_a.mp4 render_b.mp4 \
    --captions "Reference,Render A,Render B" \
    --filters "1:Difference Heatmap:ref=0, 2:Difference Heatmap:ref=0" \
    --rows 1 \
    --export comparison.mp4 \
    --no_gui
```
