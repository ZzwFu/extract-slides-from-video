#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import importlib.util
import math
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def setup_runtime_paths() -> tuple[Path, Path, Path]:
    skill_dir = Path(__file__).resolve().parent
    workspace_root = skill_dir.parent.parent
    mvp_root = workspace_root / "projects" / "youtube-slides-mvp"

    node_local_bin = str(Path.home() / ".local" / "bin")
    current_path = os.environ.get("PATH", "")
    if node_local_bin not in current_path.split(":"):
        os.environ["PATH"] = f"{node_local_bin}:{current_path}" if current_path else node_local_bin

    local_libs = workspace_root / ".local-libs"
    if local_libs.is_dir() and str(local_libs) not in sys.path:
        sys.path.insert(0, str(local_libs))
    if local_libs.is_dir():
        existing_pythonpath = os.environ.get("PYTHONPATH", "")
        pythonpath_parts = [str(local_libs)]
        if existing_pythonpath:
            pythonpath_parts.append(existing_pythonpath)
        os.environ["PYTHONPATH"] = ":".join(pythonpath_parts)

    libs_bin = local_libs / "bin"
    if libs_bin.is_dir():
        bins_path = os.environ.get("PATH", "")
        if str(libs_bin) not in bins_path.split(":"):
            os.environ["PATH"] = f"{libs_bin}:{bins_path}" if bins_path else str(libs_bin)

    return workspace_root, mvp_root, local_libs


def run_and_stream(cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> int:
    print("Running:", " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
    proc.wait()
    return proc.returncode


def run_and_capture(cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> tuple[int, str]:
    print("Running:", " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdout is not None
    output_lines: list[str] = []
    for line in proc.stdout:
        output_lines.append(line)
        sys.stdout.write(line)
    proc.wait()
    return proc.returncode, "".join(output_lines)


def sanitize_filename(name: str, maxlen: int = 120) -> str:
    if not name:
        return "video-slides"
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "video-slides"
    if len(cleaned) > maxlen:
        cleaned = cleaned[:maxlen].rstrip()
    return cleaned or "video-slides"


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_upload_date(raw_date: str | None) -> str:
    if not raw_date:
        return ""
    raw_date = str(raw_date).strip()
    if len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return raw_date


def _format_count(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value).strip()


def _load_font(candidates: list[str], size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    from PIL import ImageFont

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _download_image(url: str) -> "Image.Image | None":
    from PIL import Image

    if not url or not url.startswith(("http://", "https://")):
        return None
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=15) as response:
        data = response.read()
    return Image.open(io.BytesIO(data)).convert("RGB")


def _pdf_page_size(pdf_path: Path) -> tuple[int, int]:
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        if doc.page_count < 1:
            raise ValueError(f"pdf has no pages: {pdf_path}")
        rect = doc[0].rect
        return max(1, int(round(rect.width))), max(1, int(round(rect.height)))
    finally:
        doc.close()


def _find_matching_run(root_dir: Path, url: str, fps: float) -> Path | None:
    candidates: list[Path] = []
    for manifest_path in root_dir.glob("*/manifest.json"):
        candidates.append(manifest_path)
    candidates.sort(key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)

    for manifest_path in candidates:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("url") != url:
            continue
        metadata = payload.get("metadata", {})
        extract = metadata.get("extract", {}) if isinstance(metadata, dict) else {}
        try:
            extract_fps = float(extract.get("fps"))
        except (TypeError, ValueError):
            continue
        if abs(extract_fps - float(fps)) > 1e-9:
            continue
        task_dir = manifest_path.parent
        if (task_dir / "frames_raw").is_dir() and (task_dir / "artifacts" / "frame_manifest.json").is_file():
            return task_dir
    return None


def _rerun_from_existing(source_run: Path, mvp_root: Path, env: dict[str, str]) -> tuple[Path, Path]:
    rerun_script = mvp_root / "scripts" / "rerun_d3_d10.py"
    if not rerun_script.exists():
        raise FileNotFoundError(f"rerun script not found: {rerun_script}")

    ret, output = run_and_capture(
        [sys.executable, str(rerun_script), str(source_run), "iterative", "confidence"],
        env=env,
        cwd=mvp_root,
    )
    if ret != 0:
        raise RuntimeError("rerun_d3_d10.py failed")

    task_id = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Task:"):
            task_id = line.split(":", 1)[1].strip()
            break
    if not task_id:
        raise RuntimeError("unable to determine rerun task id")

    task_dir = mvp_root / "runs" / task_id
    slides_pdf = task_dir / "pdf" / "slides.pdf"
    if not slides_pdf.exists():
        raise RuntimeError(f"rerun slides.pdf not found: {slides_pdf}")
    return task_dir, slides_pdf


def _parse_edit_list(values: list[str]) -> str | None:
    if not values:
        return None
    return ",".join(values)


def _apply_pdfpages_edits(
    *,
    slides_pdf: Path,
    env: dict[str, str],
    delete_spec: str | None,
    insert_specs: list[str],
    after_specs: list[int],
    replace_spec: str | None,
    source_pdf: Path | None,
    source_run: Path | None,
) -> Path:
    edit_tokens: list[str] = []
    if delete_spec:
        edit_tokens.extend(["--delete", delete_spec])

    if len(insert_specs) != len(after_specs):
        raise ValueError("each --pdfpages-insert must have a matching --pdfpages-after")

    for insert_spec, after_spec in zip(insert_specs, after_specs, strict=True):
        edit_tokens.extend(["--insert", insert_spec, "--after", str(after_spec)])

    if replace_spec:
        edit_tokens.extend(["--replace", replace_spec])

    if not edit_tokens:
        return slides_pdf

    output_pdf = slides_pdf.with_name(f"{slides_pdf.stem}.edited.pdf")
    cmd = [sys.executable, "-m", "youtube_slides_mvp.pdfpages_cli", str(slides_pdf)]
    if source_run is not None:
        cmd.extend(["--from-run", str(source_run)])
    elif source_pdf is not None:
        cmd.extend(["--from", str(source_pdf)])
    cmd.extend(edit_tokens)
    cmd.extend(["-o", str(output_pdf)])

    print("PDFPAGES CMD:", " ".join(shlex.quote(part) for part in cmd), file=sys.stderr)

    ret = run_and_stream(cmd, env=env)
    if ret != 0:
        raise RuntimeError("pdfpages edit command failed")
    if not output_pdf.exists():
        raise RuntimeError(f"pdfpages output not found: {output_pdf}")
    return output_pdf


def _import_modules(module_names: list[str]) -> tuple[bool, str]:
    for module_name in module_names:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            return False, f"{module_name} import failed: {exc}"
    return True, "python dependencies importable"


def _clear_module_cache(module_names: list[str]) -> None:
    names_to_clear: set[str] = set()
    for module_name in module_names:
        names_to_clear.add(module_name)
        prefix = f"{module_name}."
        names_to_clear.update(name for name in sys.modules if name.startswith(prefix))
    for module_name in names_to_clear:
        sys.modules.pop(module_name, None)


def _prepend_env_path(var_name: str, entry: str) -> None:
    current_value = os.environ.get(var_name, "")
    entries = current_value.split(":") if current_value else []
    if entry in entries:
        return
    os.environ[var_name] = f"{entry}:{current_value}" if current_value else entry


def fetch_video_metadata(url: str) -> dict[str, str]:
    if not url.startswith("http"):
        return {}
    try:
        proc = subprocess.run(
            ["yt-dlp", "--no-playlist", "-j", url],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return {}

        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            data = json.loads(line)
            title = str(data.get("title", "")).strip()
            uploader = str(
                data.get("channel")
                or data.get("uploader")
                or data.get("uploader_id")
                or data.get("channel_id")
                or ""
            ).strip()
            thumbnail = str(data.get("thumbnail") or "").strip()
            if not thumbnail and isinstance(data.get("thumbnails"), list):
                thumbnails = data.get("thumbnails") or []
                if thumbnails:
                    thumbnail = str(thumbnails[-1].get("url") or "").strip()
            metadata = {
                "title": title,
                "channel": uploader,
                "published": _format_upload_date(str(data.get("upload_date") or data.get("release_date") or "").strip()),
                "duration": _format_duration(data.get("duration")),
                "views": _format_count(data.get("view_count")),
                "likes": _format_count(data.get("like_count")),
                "thumbnail": thumbnail,
                "source": str(data.get("webpage_url") or url).strip(),
            }
            if metadata["title"]:
                return metadata
    except Exception:
        return {}
    return {}


def build_cover_page(metadata: dict[str, str], page_width: int, page_height: int) -> Image.Image:
    from PIL import Image, ImageDraw

    base_width, base_height = 1280, 720
    width = max(1, int(page_width))
    height = max(1, int(page_height))
    cover = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(cover)

    scale_x = width / base_width
    scale_y = height / base_height
    font_scale = max(0.65, min(1.4, math.sqrt(scale_x * scale_y)))

    def sx(value: float) -> int:
        return max(1, int(round(value * scale_x)))

    def sy(value: float) -> int:
        return max(1, int(round(value * scale_y)))

    def wrap_width(text_px: int, font_size: int) -> int:
        return max(12, int(text_px / max(1.0, font_size * 0.56)))

    draw.rectangle((0, 0, width, sy(18)), fill=(25, 28, 36))
    draw.rectangle((0, height - sy(24), width, height), fill=(245, 245, 245))

    title_font = _load_font(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
        ],
        max(14, int(round(38 * font_scale))),
    )
    body_font = _load_font(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ],
        max(12, int(round(20 * font_scale))),
    )
    small_font = _load_font(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ],
        max(10, int(round(16 * font_scale))),
    )

    thumb_box = (sx(40), sy(86), sx(520), sy(356))
    thumb_w = thumb_box[2] - thumb_box[0]
    thumb_h = thumb_box[3] - thumb_box[1]
    thumb_img = None
    try:
        thumb_img = _download_image(metadata.get("thumbnail", ""))
    except Exception:
        thumb_img = None

    if thumb_img is not None:
        thumb_img = thumb_img.copy()
        thumb_img.thumbnail((thumb_w, thumb_h))
        thumb_canvas = Image.new("RGB", (thumb_w, thumb_h), (240, 240, 240))
        offset = ((thumb_w - thumb_img.width) // 2, (thumb_h - thumb_img.height) // 2)
        thumb_canvas.paste(thumb_img, offset)
        cover.paste(thumb_canvas, (thumb_box[0], thumb_box[1]))
    else:
        draw.rectangle(thumb_box, fill=(240, 240, 240), outline=(210, 210, 210), width=2)
        placeholder_font = _load_font(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ],
            max(11, int(round(22 * font_scale))),
        )
        draw.text((thumb_box[0] + sx(24), thumb_box[1] + thumb_h // 2 - sy(12)), "Thumbnail unavailable", fill=(80, 80, 80), font=placeholder_font)

    draw.rectangle(thumb_box, outline=(225, 225, 225), width=2)

    title = metadata.get("title", "") or "Extracted Slides"
    x = sx(570)
    y = sy(92)
    title_wrap = wrap_width(width - x - sx(40), title_font.size if hasattr(title_font, "size") else max(14, int(round(38 * font_scale))))
    for line in textwrap.wrap(title, width=title_wrap) or [title]:
        draw.text((x, y), line, fill=(10, 10, 10), font=title_font)
        y += max(24, int(round(46 * font_scale)))

    y += max(6, int(round(10 * font_scale)))
    body_wrap = wrap_width(width - x - sx(40), body_font.size if hasattr(body_font, "size") else max(12, int(round(20 * font_scale))))
    fields = [
        ("Channel", metadata.get("channel", "")),
        ("Published", metadata.get("published", "")),
        ("Duration", metadata.get("duration", "")),
        ("Views", metadata.get("views", "")),
        ("Likes", metadata.get("likes", "")),
        ("Source", metadata.get("source", "")),
    ]
    for label, value in fields:
        if not value:
            continue
        lines = textwrap.wrap(value, width=body_wrap) or [value]
        draw.text((x, y), f"{label}: {lines[0]}", fill=(40, 40, 40), font=body_font)
        y += max(18, int(round(28 * font_scale)))
        for continuation in lines[1:]:
            draw.text((x + sx(86), y), continuation, fill=(40, 40, 40), font=body_font)
            y += max(18, int(round(28 * font_scale)))

    draw.text((sx(40), height - sy(84)), "Generated by extract-slides-from-video", fill=(90, 90, 90), font=small_font)
    return cover


def prepend_cover_page(slides_pdf: Path, output_path: Path, cover: Image.Image) -> None:
    import fitz

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cover_buffer = io.BytesIO()
    cover.save(cover_buffer, format="PNG")
    cover_bytes = cover_buffer.getvalue()

    slides_doc = fitz.open(str(slides_pdf))
    out_doc = fitz.open()
    out_doc.new_page(width=cover.width, height=cover.height)
    out_doc[0].insert_image(fitz.Rect(0, 0, cover.width, cover.height), stream=cover_bytes)
    out_doc.insert_pdf(slides_doc)
    out_doc.save(str(output_path))
    slides_doc.close()
    out_doc.close()


def _has_pdfpages_edits(args: argparse.Namespace) -> bool:
    return bool(
        args.pdfpages_delete
        or args.pdfpages_insert
        or args.pdfpages_replace
    )


def ensure_python_deps(mvp_root: Path, local_libs: Path) -> tuple[bool, str, Path]:
    required_modules = ["pydantic", "numpy", "PIL", "fitz", "pytesseract"]
    runtime_libs = Path("/tmp/extract-slides-from-video/.local-libs")
    candidate_libs = [runtime_libs]
    if runtime_libs != local_libs:
        candidate_libs.append(local_libs)

    for candidate_lib in candidate_libs:
        if not candidate_lib.exists():
            continue
        _clear_module_cache(required_modules)
        sys.path.insert(0, str(candidate_lib))
        _prepend_env_path("PYTHONPATH", str(candidate_lib))
        ok, msg = _import_modules(required_modules)
        if ok:
            _prepend_env_path("PATH", str(candidate_lib / "bin"))
            return True, msg, candidate_lib
        if str(candidate_lib) in sys.path:
            while str(candidate_lib) in sys.path:
                sys.path.remove(str(candidate_lib))

    runtime_libs.mkdir(parents=True, exist_ok=True)
    local_libs = runtime_libs

    requirements = mvp_root / "requirements.txt"
    if not requirements.exists():
        return False, f"requirements.txt not found: {requirements}", local_libs

    local_libs.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--root-user-action=ignore",
        "--upgrade",
        "--target",
        str(local_libs),
        "-r",
        str(requirements),
    ]
    ret = run_and_stream(cmd)
    if ret != 0:
        return False, "failed to install MVP python dependencies", local_libs

    if str(local_libs) not in sys.path:
        sys.path.insert(0, str(local_libs))
    _prepend_env_path("PYTHONPATH", str(local_libs))

    libs_bin = local_libs / "bin"
    if libs_bin.is_dir():
        _prepend_env_path("PATH", str(libs_bin))

    importlib.invalidate_caches()
    ok_after, msg_after = _import_modules(required_modules)
    if not ok_after:
        return False, f"still broken after install: {msg_after}", local_libs
    return True, "python dependencies installed", local_libs


def ensure_tools(required_tools: list[str]) -> tuple[bool, str]:
    missing = [name for name in required_tools if shutil.which(name) is None]
    if missing:
        return False, f"missing required tools: {', '.join(missing)}"
    return True, "tools available"


def unique_output_path(outdir: Path, title: str) -> Path:
    base = sanitize_filename(title)
    candidate = outdir / f"{base}.pdf"
    i = 1
    while candidate.exists():
        candidate = outdir / f"{base}-{i}.pdf"
        i += 1
    return candidate


def build_task_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"slide-{ts}-{uuid.uuid4().hex[:6]}"


def cleanup_task_artifacts(task_dir: Path) -> None:
    for name in ("video", "frames_raw", "frames_norm", "artifacts", "pdf"):
        path = task_dir / name
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="extract-slides-from-video handler")
    parser.add_argument("--url", required=True, help="YouTube URL")
    parser.add_argument("--outdir", default="/data/obsidian-vault/areas/trading", help="output directory")
    parser.add_argument("--fps", type=float, default=1.0, help="frame extraction rate")
    parser.add_argument("--ocr-lang", default="eng+chi_sim", help="OCR language")
    parser.add_argument("--skip-ocr", action="store_true", help="skip OCR stage")
    parser.add_argument("--expected-pages", type=int, default=None, help="expected slide count")
    parser.add_argument("--redownload", action="store_true", help="force a fresh download even if a matching run exists")
    parser.add_argument("--pdfpages-delete", default=None, help="delete page spec applied to the generated slides PDF before cover prepending")
    parser.add_argument("--pdfpages-insert", action="append", default=[], help="insert page spec applied to the generated slides PDF before cover prepending; repeat with --pdfpages-after")
    parser.add_argument("--pdfpages-after", action="append", type=int, default=[], help="page boundary for the preceding --pdfpages-insert")
    parser.add_argument("--pdfpages-replace", default=None, help="replace page spec applied to the generated slides PDF before cover prepending")
    parser.add_argument("--pdfpages-from", dest="pdfpages_from", default=None, help="source PDF for pdfpages insert/replace edits")
    parser.add_argument("--pdfpages-from-run", dest="pdfpages_from_run", default=None, help="run directory for pdfpages time-based or run-aware insert/replace edits")
    cleanup_group = parser.add_mutually_exclusive_group()
    cleanup_group.add_argument(
        "--cleanup-task",
        action="store_true",
        help="remove heavy task artifacts after export, while keeping manifest.json",
    )
    cleanup_group.add_argument(
        "--keep-task",
        action="store_true",
        help="keep full task artifacts (default)",
    )
    args = parser.parse_args()

    _, mvp_root, local_libs = setup_runtime_paths()

    if not mvp_root.exists():
        print(json.dumps({"ok": False, "error": f"MVP project not found: {mvp_root}"}, ensure_ascii=False))
        return 1

    ok, msg = ensure_tools(["ffmpeg", "yt-dlp"])
    if not ok:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        return 1

    ok, msg, runtime_libs = ensure_python_deps(mvp_root, local_libs)
    if not ok:
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    run_root = Path("/tmp/extract-slides-from-video") / "runs"
    run_root.mkdir(parents=True, exist_ok=True)

    effective_skip_ocr = bool(args.skip_ocr)
    if not effective_skip_ocr and shutil.which("tesseract") is None:
        effective_skip_ocr = True

    metadata = fetch_video_metadata(args.url)
    title = metadata.get("title", "")

    matched_run = None
    if not args.redownload:
        matched_run = _find_matching_run(run_root, args.url, args.fps)
        if matched_run is None:
            matched_run = _find_matching_run(mvp_root / "runs", args.url, args.fps)

    mvp_src = mvp_root / "src"
    if not mvp_src.exists():
        print(json.dumps({"ok": False, "error": f"MVP src not found: {mvp_src}"}, ensure_ascii=False))
        return 1

    env = os.environ.copy()
    pythonpath_parts = [str(mvp_src)]
    if runtime_libs.exists():
        pythonpath_parts.insert(0, str(runtime_libs))
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = ":".join(pythonpath_parts)

    task_dir: Path
    manifest_path: Path
    slides_pdf: Path
    has_pdf_edits = _has_pdfpages_edits(args)
    if matched_run is not None and has_pdf_edits:
        task_dir = matched_run
        manifest_path = task_dir / "manifest.json"
        slides_pdf = task_dir / "pdf" / "slides.pdf"
        if not slides_pdf.exists():
            print(f"existing slides.pdf missing, will regenerate: {slides_pdf}", file=sys.stderr)
            matched_run = None
        else:
            print(f"Using existing slides.pdf without rerun: {matched_run}", file=sys.stderr)
    if matched_run is not None and not has_pdf_edits:
        try:
            task_dir, slides_pdf = _rerun_from_existing(matched_run, mvp_root, env)
            manifest_path = task_dir / "manifest.json"
            print(f"Reused existing run without download: {matched_run}", file=sys.stderr)
        except Exception as exc:
            print(f"reuse failed, falling back to download: {exc}", file=sys.stderr)
            matched_run = None

    if matched_run is None:
        task_id = build_task_id()
        task_dir = run_root / task_id
        manifest_path = task_dir / "manifest.json"
        slides_pdf = task_dir / "pdf" / "slides.pdf"

    if matched_run is None:
        cmd = [
            sys.executable,
            "-m",
            "youtube_slides_mvp.cli",
            "run",
            "--url",
            args.url,
            "--outdir",
            str(run_root),
            "--task-id",
            task_id,
            "--fps",
            str(args.fps),
            "--ocr-lang",
            args.ocr_lang,
        ]
        if effective_skip_ocr:
            cmd.append("--skip-ocr")
        if args.expected_pages is not None:
            cmd.extend(["--expected-pages", str(args.expected_pages)])

        ret = run_and_stream(cmd, env=env)
        if ret != 0:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "youtube-slides-mvp run failed",
                        "ret": ret,
                        "manifest": str(manifest_path) if manifest_path.exists() else "",
                    },
                    ensure_ascii=False,
                )
            )
            return 1

        if not slides_pdf.exists():
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"slides.pdf not found at {slides_pdf}",
                        "manifest": str(manifest_path) if manifest_path.exists() else "",
                    },
                    ensure_ascii=False,
                )
            )
            return 1

    slides_for_cover = slides_pdf
    if has_pdf_edits:
        source_pdf = Path(args.pdfpages_from) if args.pdfpages_from else None
        source_run = Path(args.pdfpages_from_run) if args.pdfpages_from_run else None
        if source_pdf is None and source_run is None and (args.pdfpages_insert or args.pdfpages_replace):
            source_pdf = slides_pdf
        slides_for_cover = _apply_pdfpages_edits(
            slides_pdf=slides_pdf,
            env=env,
            delete_spec=_parse_edit_list([args.pdfpages_delete]) if args.pdfpages_delete else None,
            insert_specs=args.pdfpages_insert,
            after_specs=args.pdfpages_after,
            replace_spec=args.pdfpages_replace,
            source_pdf=source_pdf,
            source_run=source_run,
        )

    page_width, page_height = _pdf_page_size(slides_for_cover)
    output_path = unique_output_path(outdir, title or "video-slides")
    cover = build_cover_page(metadata, page_width, page_height)
    prepend_cover_page(slides_for_cover, output_path, cover)

    cleanup_task = bool(args.cleanup_task)
    if cleanup_task and has_pdf_edits and matched_run is not None:
        print("cleanup skipped for reused edit run", file=sys.stderr)
        cleanup_task = False
    if cleanup_task:
        cleanup_task_artifacts(task_dir)

    print(
        json.dumps(
            {
                "ok": True,
                "path": str(output_path),
                "manifest": str(manifest_path),
                "task_dir": str(task_dir),
                "title": title,
                "skip_ocr": effective_skip_ocr,
                "cleanup_task": cleanup_task,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
