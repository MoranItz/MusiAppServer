from fastapi import FastAPI
import yt_dlp, os, uuid

app = FastAPI()


@app.post("/download")
def download(url: str):
    filename = f"{uuid.uuid4()}.mp3"
    output_path = f"downloads/{filename}"

    yt_dlp.YoutubeDL({
        "format": "bestaudio",
        "outtmpl": output_path,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    }).download([url])

    # Return metadata + the file
    return FileResponse(output_path, ...)

# That's essentially the core of it
