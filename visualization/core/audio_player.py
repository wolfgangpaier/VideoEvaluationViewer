"""Audio player module for video visualization tool.

Handles audio extraction from source video via ffmpeg, playback via PyAudio,
and sync with video timeline.
"""

from __future__ import annotations

import io
import logging
import subprocess
import threading
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pyaudio

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Handles audio extraction, playback, and sync with the video timeline.

    Extracts audio from source video via ffmpeg, plays segments on demand
    or continuously via PyAudio.
    """

    _CHUNK_SIZE = 1024

    def __init__(self) -> None:
        self._source_path: Path | None = None
        self._audio_data: np.ndarray | None = None
        self._sample_rate: int = 44100
        self._channels: int = 2
        self._fps: float = 30.0
        self._stream: pyaudio.Stream | None = None
        self._pa: pyaudio.PyAudio | None = None
        self._playback_pos: list[int] = []  # mutable, shared with callback
        self._playback_lock = threading.Lock()

        try:
            self._pa = pyaudio.PyAudio()
        except OSError as e:
            logger.warning("PyAudio initialization failed: %s. Audio disabled.", e)
            self._pa = None

    def set_source(self, video_path: Path, fps: float) -> None:
        """Extract audio from video_path using ffmpeg and load into memory.

        Args:
            video_path: Path to the source video file.
            fps: Video frames per second for frame-to-time conversion.
        """
        self.clear()

        if self._pa is None:
            return

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    "-f",
                    "wav",
                    "pipe:1",
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("ffmpeg not found. Audio extraction disabled.")
            self._audio_data = None
            return
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg audio extraction timed out for %s", video_path)
            self._audio_data = None
            return

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            logger.warning(
                "ffmpeg audio extraction failed for %s: %s",
                video_path,
                stderr[:500] if stderr else "unknown",
            )
            self._audio_data = None
            return

        if not result.stdout:
            logger.warning("ffmpeg produced no audio output for %s", video_path)
            self._audio_data = None
            return

        try:
            bio = io.BytesIO(result.stdout)
            with wave.open(bio, "rb") as wf:
                self._sample_rate = wf.getframerate()
                self._channels = wf.getnchannels()
                raw_frames = wf.readframes(wf.getnframes())
                if raw_frames:
                    self._audio_data = np.frombuffer(raw_frames, dtype=np.int16)
                else:
                    self._audio_data = None
        except Exception as e:
            logger.warning("Failed to parse audio data from %s: %s", video_path, e)
            self._audio_data = None
            return

        self._source_path = video_path
        self._fps = fps

    def clear(self) -> None:
        """Stop any playing stream and release audio data."""
        self.stop()
        self._source_path = None
        self._audio_data = None

    def play_snippet(self, frame_idx: int) -> None:
        """Play a short segment of audio (~1 frame duration) at the given frame.

        Args:
            frame_idx: Current video frame index.
        """
        if self._pa is None or self._audio_data is None:
            return

        t = frame_idx / self._fps
        sample_offset = int(t * self._sample_rate) * self._channels
        samples_per_frame = max(1, int(self._sample_rate / self._fps)) * self._channels
        start = sample_offset
        end = min(sample_offset + samples_per_frame, len(self._audio_data))

        if start >= end or start >= len(self._audio_data):
            return

        segment = self._audio_data[start:end]
        data = segment.tobytes()

        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._channels,
                rate=self._sample_rate,
                output=True,
            )
            stream.write(data)
            stream.stop_stream()
            stream.close()
        except Exception as e:
            logger.debug("play_snippet failed: %s", e)

    def play_from(self, frame_idx: int) -> None:
        """Start continuous playback from the given frame position.

        Args:
            frame_idx: Video frame index to start playback from.
        """
        if self._pa is None or self._audio_data is None:
            return

        self.stop()

        t = frame_idx / self._fps
        sample_offset = int(t * self._sample_rate) * self._channels
        if sample_offset >= len(self._audio_data):
            return

        self._playback_pos = [sample_offset]
        audio_data = self._audio_data
        channels = self._channels
        chunk_size = self._CHUNK_SIZE
        playback_lock = self._playback_lock

        def callback(
            in_data: bytes,
            frame_count: int,
            time_info: dict[str, Any],
            status: int,
        ) -> tuple[bytes, int]:
            with playback_lock:
                pos = self._playback_pos[0]
                total = len(audio_data)
                frames_needed = frame_count * channels
                end_pos = min(pos + frames_needed, total)
                if pos >= total:
                    return (b"", pyaudio.paComplete)

                chunk = audio_data[pos:end_pos]
                self._playback_pos[0] = end_pos

                if len(chunk) < frames_needed:
                    padding = np.zeros(frames_needed - len(chunk), dtype=np.int16)
                    chunk = np.concatenate([chunk, padding])

                if end_pos >= total:
                    return (chunk.tobytes(), pyaudio.paComplete)
                return (chunk.tobytes(), pyaudio.paContinue)

        try:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=chunk_size,
                stream_callback=callback,
            )
            self._stream.start_stream()
        except Exception as e:
            logger.warning("Failed to start audio playback: %s", e)
            self._stream = None

    def stop(self) -> None:
        """Stop the currently playing stream if any."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception as e:
                logger.debug("Error stopping audio stream: %s", e)
            self._stream = None

    @property
    def is_playing(self) -> bool:
        """Return True if audio is currently playing."""
        if self._pa is None or self._stream is None:
            return False
        try:
            return self._stream.is_active()
        except Exception:
            return False

    def cleanup(self) -> None:
        """Terminate PyAudio instance. Call on application exit."""
        self.stop()
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception as e:
                logger.debug("Error terminating PyAudio: %s", e)
            self._pa = None
