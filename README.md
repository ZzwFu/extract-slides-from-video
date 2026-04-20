## One-click Install Script

你可以使用以下脚本自动完成依赖安装和 skill 注册（假设你已在 openclaw workspace 根目录下）：

```bash
# 一键安装 extract-slides-from-video 及其依赖
git clone <extract-slides-from-video-repo-url> skills/extract-slides-from-video
git clone <youtube-slides-mvp-repo-url> projects/youtube-slides-mvp
pip install -e ./projects/youtube-slides-mvp
# 可选：安装系统依赖
bash projects/youtube-slides-mvp/scripts/install_deps_mac.sh  # macOS
# Linux 用户请手动安装 ffmpeg、tesseract-ocr 等
# 注册 skill（如 openclaw 支持自动发现 skills 目录则无需手动注册）
# 若需手动注册，可在 openclaw 配置文件中添加：
#   skills/extract-slides-from-video/command.json
```

## Skill 注册说明

1. 确认 openclaw 配置文件（如 skills.json 或 config.yaml）支持自定义 skill 路径。
2. 添加如下条目（示例）：
    ```json
    {
       "handler": "skills/extract-slides-from-video/handler.py",
       "command": "/extract-slides-from-video",
       "public": true
    }
    ```
3. 重启 openclaw 服务。
4. 通过 `/extract-slides-from-video <YouTube URL>` 指令测试。
# extract-slides-from-video

Extract a slides PDF with a mandatory cover page from a YouTube video, using youtube-slides-mvp as the backend pipeline.

## Features
- Converts YouTube presentation recordings into slides PDFs with a cover page
- Auto-fetches video metadata (title, channel, published date, etc.)
- Reuses previous runs when possible for efficiency
- Supports PDF editing and cover page customization

## Dependencies
- [youtube-slides-mvp](https://github.com/your-org/youtube-slides-mvp) (must be cloned and installed)
- Python 3.10+
- ffmpeg, tesseract-ocr, yt-dlp (see youtube-slides-mvp for details)

## Installation

1. Clone both repositories:
   ```bash
   git clone <extract-slides-from-video-repo-url>
   git clone <youtube-slides-mvp-repo-url> projects/youtube-slides-mvp
   ```
2. Install youtube-slides-mvp as an editable package:
   ```bash
   pip install -e ./projects/youtube-slides-mvp
   ```
3. (Optional) Install system dependencies (see youtube-slides-mvp/README.md):
   ```bash
   bash projects/youtube-slides-mvp/scripts/install_deps_mac.sh  # macOS
   # or manually install ffmpeg, tesseract-ocr, etc. on Linux
   ```
4. Register this skill in your openclaw instance (see openclaw documentation).

## Usage

Trigger via:
```
/extract-slides-from-video <YouTube URL>
```

## Notes
- Ensure youtube-slides-mvp is installed and accessible in PYTHONPATH.
- For Dockerized environments, see youtube-slides-mvp/Dockerfile for base image setup.
- For troubleshooting, check logs and manifest paths returned in the JSON output.
