#!/usr/bin/env python3
"""Video Visualization & Comparison Tool.

Sample calls:
    # Launch GUI with two videos
    python -m visualization.visualize --videos clip_a.mp4 clip_b.mp4

    # Launch GUI with custom captions and a filter
    python -m visualization.visualize --videos ref.mp4 render.mp4 \
        --captions "Reference,Render" --filters "1:Difference Heatmap:ref=0"

    # Headless export (no GUI)
    python -m visualization.visualize --videos ref.mp4 render.mp4 \
        --filters "1:Difference Heatmap:ref=0" --export output.mp4 --no_gui

    # Export with custom resolution and 2-row layout
    python -m visualization.visualize --videos a.mp4 b.mp4 c.mp4 d.mp4 \
        --rows 2 --export_width 1920 --export comparison.mp4 --no_gui
"""

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_filters(filter_str: str) -> list[dict]:
    """Parse CLI filter specification string.

    Format: "<video_id>:<filter_name>[:<param>=<value>,...], ..."
    Example: "1:Difference Heatmap:ref=0, 2:Difference Heatmap:ref=0"
    """
    specs = []
    for part in filter_str.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(":")
        if len(tokens) < 2:
            logger.warning("Ignoring malformed filter spec: %s", part)
            continue
        video_id = int(tokens[0].strip())
        filter_name = tokens[1].strip()
        params = {}
        for kv in tokens[2:]:
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k.strip()] = v.strip()
        specs.append({"video_id": video_id, "name": filter_name, "params": params})
    return specs


def _apply_cli_filters(video_manager, filter_specs: list[dict]) -> None:
    """Apply filter specifications parsed from CLI to loaded videos."""
    from visualization.filters import FilterRegistry

    for spec in filter_specs:
        entry = video_manager.get_video(spec["video_id"])
        if entry is None:
            logger.warning("Filter: video ID %d not found, skipping.", spec["video_id"])
            continue
        if spec["name"].lower() == "none":
            entry.filter = None
            continue
        try:
            flt = FilterRegistry.create_filter(spec["name"])
        except KeyError:
            logger.warning("Unknown filter '%s', skipping.", spec["name"])
            continue
        ref_id = spec["params"].get("ref")
        if ref_id is not None:
            flt.ref_video_id = int(ref_id)
        flt.configure(spec["params"])
        entry.filter = flt


def _apply_cli_captions(video_manager, captions_str: str) -> None:
    """Apply comma-separated captions to loaded videos in order."""
    captions = [c.strip() for c in captions_str.split(",")]
    for i, caption in enumerate(captions):
        entry = video_manager.get_video(i)
        if entry is not None and caption:
            entry.label = caption


def _run_headless_export(args, video_manager, frame_cache) -> int:
    """Perform export without opening a GUI window."""
    from visualization.core.audio_player import AudioPlayer
    from visualization.core.exporter import Exporter

    if not args.export:
        logger.error("--export is required for headless mode (--no_gui).")
        return 1

    audio_path = None
    if args.audio_source is not None:
        entry = video_manager.get_video(args.audio_source)
        if entry and entry.info.has_audio:
            audio_path = entry.info.path

    exporter = Exporter(video_manager, frame_cache)
    total = video_manager.max_frame_count

    def progress(frame_idx: int, total_frames: int) -> None:
        if total_frames > 0:
            pct = (frame_idx + 1) / total_frames * 100
            print(f"\rExporting: {pct:5.1f}% ({frame_idx + 1}/{total_frames})", end="", flush=True)

    try:
        exporter.export(
            output_path=args.export,
            export_width=args.export_width,
            export_height=args.export_height,
            audio_source_path=audio_path,
            rows=args.rows,
            progress_callback=progress,
        )
        print(f"\nExport complete: {args.export}")
        return 0
    except Exception as e:
        print(f"\nExport failed: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Video Visualization & Comparison Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--videos", nargs="+", metavar="PATH",
        help="One or more video file paths to load.",
    )
    parser.add_argument(
        "--captions", type=str, default=None,
        help="Comma-separated custom captions matching --videos order.",
    )
    parser.add_argument(
        "--filters", type=str, default=None,
        help='Per-video filter spec, e.g. "1:Difference Heatmap:ref=0".',
    )
    parser.add_argument(
        "--audio_source", type=int, default=0,
        help="Video ID to use as audio source (default: 0).",
    )
    parser.add_argument(
        "--export", type=str, default=None, metavar="PATH",
        help="Output path for export. Triggers export.",
    )
    parser.add_argument(
        "--export_width", type=int, default=None,
        help="Export width in pixels (height computed from aspect ratio).",
    )
    parser.add_argument(
        "--export_height", type=int, default=None,
        help="Export height in pixels (width computed from aspect ratio).",
    )
    parser.add_argument(
        "--rows", type=int, default=1,
        help="Number of rows for the video grid layout (default: 1).",
    )
    parser.add_argument(
        "--no_gui", action="store_true",
        help="Run headless (CLI-only export, no window).",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from visualization.core.video_manager import FrameCache, VideoManager

    video_manager = VideoManager()
    frame_cache = FrameCache()

    if args.videos:
        for p in args.videos:
            try:
                video_manager.load_video(p)
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                logger.error("Cannot load '%s': %s", p, e)
                return 1

    if args.captions:
        _apply_cli_captions(video_manager, args.captions)

    if args.filters:
        _apply_cli_filters(video_manager, _parse_filters(args.filters))

    if args.no_gui:
        rc = _run_headless_export(args, video_manager, frame_cache)
        video_manager.clear()
        return rc

    from PySide6.QtWidgets import QApplication

    from visualization.core.audio_player import AudioPlayer
    from visualization.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    audio_player = AudioPlayer()

    if args.audio_source is not None:
        entry = video_manager.get_video(args.audio_source)
        if entry and entry.info.has_audio:
            audio_player.set_source(entry.info.path, entry.info.fps)

    window = MainWindow(
        video_manager=video_manager,
        frame_cache=frame_cache,
        audio_player=audio_player,
        rows=args.rows,
    )
    window.show()

    if args.export:
        from visualization.core.exporter import Exporter

        exporter = Exporter(video_manager, frame_cache)
        audio_path = audio_player._source_path
        try:
            exporter.export(
                output_path=args.export,
                export_width=args.export_width,
                export_height=args.export_height,
                audio_source_path=audio_path,
                rows=args.rows,
            )
            logger.info("Export complete: %s", args.export)
        except Exception as e:
            logger.error("Export failed: %s", e)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
