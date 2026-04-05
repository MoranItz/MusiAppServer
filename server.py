"""
MusiApp Download Server
Run with: uvicorn server:app --host 0.0.0.0 --port 8080
Requires: pip install fastapi uvicorn yt-dlp
Requires: ffmpeg installed and on PATH (https://ffmpeg.org/download.html)
"""

import os
import uuid
import json
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="MusiApp Server")

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class DownloadRequest(BaseModel):
    url: str


@app.get("/ping")
def ping():
    """Health check — the app calls this to verify the server is reachable."""
    return {"status": "ok"}


@app.post("/download")
def download_song(req: DownloadRequest):
    """
    Accepts a YouTube URL, downloads audio as MP3 via yt-dlp,
    and returns the file with song metadata in response headers.
    """
    song_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOADS_DIR, f"{song_id}.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "writeinfojson": True,
        "quiet": True,
        "ffmpeg_location": r"C:\Users\adren\Downloads\ffmpeg-master-latest-win64-gpl-shared\ffmpeg-master-latest-win64-gpl-shared\bin",
    }

    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([req.url])
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {str(e)}")

    mp3_path = os.path.join(DOWNLOADS_DIR, f"{song_id}.mp3")
    info_path = os.path.join(DOWNLOADS_DIR, f"{song_id}.info.json")

    if not os.path.exists(mp3_path):
        raise HTTPException(status_code=500, detail="MP3 not found after download.")

    # Read title/artist/duration from the sidecar JSON yt-dlp writes
    title, artist, duration = "Unknown Title", "Unknown Artist", 0
    if os.path.exists(info_path):
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)
            title    = info.get("title", title)
            artist   = info.get("uploader", artist)
            duration = int(info.get("duration", 0))

        # Return the MP3 with metadata packed into custom response headers
        return FileResponse(
            path=mp3_path,
            media_type="audio/mpeg",
            filename=f"{song_id}.mp3",  # Safer to use song_id here avoid header injection
            headers={
                "X-Song-Title": urllib.parse.quote(title),
                "X-Song-Artist": urllib.parse.quote(artist),
                "X-Song-Duration": str(duration),
                "Access-Control-Expose-Headers": "X-Song-Title,X-Song-Artist,X-Song-Duration",
            }
        )
