"""
MusiApp Pytube Server
Run with: uvicorn server:app --host 0.0.0.0 --port 8080
"""

import os
import uuid
import urllib.parse
import requests
import re
import socket
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pytubefix import YouTube, Playlist, Search

try:
    from zeroconf import ServiceInfo, Zeroconf
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False

app = FastAPI(title="MusiApp Server")

DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# --- mDNS Discovery (Zero-Config) ---
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

zc = None
if HAS_ZEROCONF:
    try:
        local_ip = get_local_ip()
        info = ServiceInfo(
            "_musiapp._tcp.local.",
            "MusiApp Server._musiapp._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=8080,
            properties={"version": "1.0"},
            server="musiapp.local.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        print(f"INFO [Discovery]: Broadcasting MusiApp Server at {local_ip}:8080 📡")
    except Exception as e:
        print(f"WARNING [Discovery]: Failed to start mDNS: {str(e)}")
else:
    print("WARNING [Discovery]: 'zeroconf' not installed. Auto-discovery disabled. ⚠️")


class DownloadRequest(BaseModel):
    url: str

@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.post("/playlist")
def get_playlist_info(req: DownloadRequest):
    """
    Returns the title and list of video URLs for a given YouTube playlist.
    """
    try:
        url = req.url
        # Normalize: if it's a watch link containing a list, convert to playlist URL
        if "list=" in url:
            list_id = url.split("list=")[1].split("&")[0]
            url = f"https://www.youtube.com/playlist?list={list_id}"
            
        pl = Playlist(url)
        return {
            "title": pl.title,
            "urls": list(pl.video_urls)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Playlist fetch failed: {str(e)}")


def resolve_spotify(url: str):
    """
    Scrapes metadata from an 'Open' Spotify page and finds matching YouTube URL(s).
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Spotify page unreachable ({response.status_code})")
    
    html = response.text
    
    # Try to extract track title and artist from meta tags
    # <meta property="og:title" content="Song Title" />
    # <meta property="og:description" content="Artist Name · Song · 2024" />
    title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
    
    if not title_match or not desc_match:
        raise Exception("Could not find metadata on Spotify page")
    
    track_title = title_match.group(1)
    # The description often contains "Artist Name · Song · Year"
    artist = desc_match.group(1).split(" · ")[0]
    
    query = f"{track_title} {artist} audio"
    s = Search(query)
    if not s.results:
        raise Exception("No matching YouTube video found")
    
    return {
        "title": track_title,
        "artist": artist,
        "youtube_url": s.results[0].watch_url
    }


@app.post("/spotify")
def spotify_info(req: DownloadRequest):
    """
    Resolves a Spotify song link to a YouTube URL.
    """
    try:
        if "/track/" in req.url:
            resolved = resolve_spotify(req.url)
            return {
                "type": "track",
                "title": resolved["title"],
                "urls": [resolved["youtube_url"]]
            }
        else:
            raise HTTPException(status_code=400, detail="MusiApp currently only supports single Spotify songs. Playlists coming soon!")
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def remove_file_safely(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

@app.post("/download")
def download_song(req: DownloadRequest, background_tasks: BackgroundTasks):
    """
    Downloads audio blisteringly fast using native python requests via pytubefix.
    Completely avoids yt-dlp overhead, JS engine chaos, and ffmpeg entirely.
    """
    song_id = str(uuid.uuid4())
    mp3_path = os.path.join(DOWNLOADS_DIR, f"{song_id}.mp3")

    try:
        # Fetch the video using the lightning fast Android client
        yt = YouTube(req.url)

        # Grab the highest quality native audio stream
        audio_stream = yt.streams.filter(only_audio=True).first()
        if not audio_stream:
            raise Exception("No audio stream found")

        # Download directly to our MP3 file path
        audio_stream.download(output_path=DOWNLOADS_DIR, filename=f"{song_id}.mp3")

        title = yt.title or "Unknown Title"
        artist = yt.author or "Unknown Artist"
        duration = yt.length or 0

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Pytube failed: {str(e)}")

    if not os.path.exists(mp3_path):
        raise HTTPException(status_code=500, detail="Audio file not written to disk.")

    background_tasks.add_task(remove_file_safely, mp3_path)

    return FileResponse(
        path=mp3_path,
        media_type="audio/mpeg",
        filename=f"{song_id}.mp3",
        headers={
            "X-Song-Title": urllib.parse.quote(title),
            "X-Song-Artist": urllib.parse.quote(artist),
            "X-Song-Duration": str(duration),
            "Access-Control-Expose-Headers": "X-Song-Title,X-Song-Artist,X-Song-Duration"
        }
    )