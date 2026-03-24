from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadResult:
    file_path: Path
    title: str


_YT_URL_RE = re.compile(r"^https?://")


def download_youtube_video(url: str, output_dir: Path, basename: str) -> DownloadResult:
    if not url or not _YT_URL_RE.match(url.strip()):
        raise ValueError("Invalid URL")

    output_dir.mkdir(parents=True, exist_ok=True)

    out_template = str((output_dir / f"{basename}.%(ext)s").resolve())

    title_proc = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--get-title",
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if title_proc.returncode != 0:
        raise RuntimeError((title_proc.stderr or title_proc.stdout or "yt-dlp failed").strip())

    title = (title_proc.stdout or "").strip() or "youtube"

    dl_proc = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "-f",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
            "--merge-output-format",
            "mp4",
            "-o",
            out_template,
            url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if dl_proc.returncode != 0:
        msg = (dl_proc.stderr or dl_proc.stdout or "yt-dlp failed").strip()
        raise RuntimeError(msg)

    mp4_path = (output_dir / f"{basename}.mp4")
    if not mp4_path.exists():
        candidates = sorted(output_dir.glob(f"{basename}.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            raise RuntimeError(f"Downloaded file is not mp4: {candidates[0].name}")
        raise RuntimeError("Download finished but output file not found")

    return DownloadResult(file_path=mp4_path, title=title)
