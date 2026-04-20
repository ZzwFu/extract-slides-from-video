---
name: extract-slides-from-video
description: Extract a slides PDF with a mandatory cover page from a YouTube video by reusing youtube-slides-mvp. Use when the user sends /extract-slides-from-video with a YouTube URL.
---

# extract-slides-from-video

Use youtube-slides-mvp as backend pipeline and export a slides PDF with a mandatory cover page.

When to use
- Convert a YouTube presentation recording into a slides PDF with a mandatory cover page.
- Keep manifest path in response for debugging pipeline runs.

Trigger
- /extract-slides-from-video <YouTube URL>

What it does
1. Fetch video metadata via yt-dlp
2. Reuse a matching same-URL run via rerun_d3_d10.py when possible, unless --redownload is set
3. Run youtube-slides-mvp CLI pipeline when reuse is not possible
4. Read generated slides.pdf (pure slides only)
5. Optionally edit the generated slides PDF with pdfpages before cover prepending
6. Generate a cover page sized to match the slides PDF pages
7. Prepend the cover to the slides PDF
8. Rename output to video title
9. Save PDF into target output directory
10. Return JSON with output path and manifest path

Required cover page
- Auto-fetch video metadata (title/channel/published/duration/views/likes/source/thumbnail)
- Create a cover page with thumbnail (left) + metadata (right)
- Output always includes cover page as first page
- Cover page size matches the slides PDF page size

Handler arguments
- --url: YouTube URL (required)
- --outdir: destination directory (default /data/obsidian-vault/areas/trading)
- --fps: extraction fps (default 1.0)
- --ocr-lang: OCR languages (default eng+chi_sim)
- --skip-ocr: skip OCR stage
- --expected-pages: expected slide count for quality gate
- --redownload: force a fresh download even if a matching run exists
- --pdfpages-delete: delete page spec applied to the generated slides PDF before cover prepending
- --pdfpages-insert: insert page spec applied to the generated slides PDF before cover prepending; repeat with --pdfpages-after
- --pdfpages-after: page boundary for the preceding --pdfpages-insert
- --pdfpages-replace: replace page spec applied to the generated slides PDF before cover prepending
- --pdfpages-from: source PDF for pdfpages insert/replace edits
- --pdfpages-from-run: run directory for pdfpages time-based or run-aware insert/replace edits
- --cleanup-task: remove heavy task artifacts after export (manifest is kept)
- --keep-task: keep full task artifacts (default behavior)

Editing notes
- pdfpages edits are applied to the generated slides PDF before the cover page is prepended
- When insert/replace is used without --pdfpages-from or --pdfpages-from-run, the generated slides PDF is used as the source
- If a matching run already has slides.pdf and you pass pdfpages flags, the handler edits that existing slides.pdf directly instead of rerunning extraction

Output
- A renamed PDF with a generated cover page in --outdir
- JSON response includes:
  - ok
  - path
  - manifest
  - task_dir
  - title
  - skip_ocr

Dependencies
- yt-dlp
- ffmpeg
- python3
- youtube-slides-mvp project at workspace/projects/youtube-slides-mvp
- Python dependencies from youtube-slides-mvp requirements.txt (auto-installed to workspace/.local-libs when missing)

Local OpenClaw simulation
- `scripts/run_real_openclaw_sim.sh [YouTube URL | --url URL] [handler flags...]`
- Uses the live `openclaw-openclaw-gateway-1` container, its shared `/data` volume, and a persistent Linux-native dependency cache
