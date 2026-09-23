import os
import re
import requests
from time import time
from pathlib import Path
from PIL import Image


def sanitize_file_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*¿¡!@#$%^&(){}\[\];,+=]+', "", name)
    name = re.sub(r"\s+", "-", name)
    return name.strip().lower()


def modify_google_drive_url(drive_url: str) -> str:
    match = re.search(r"(?:/d/|id=)([\w-]+)", drive_url)
    if not match:
        raise ValueError("Invalid Google Drive URL")
    return f"https://drive.google.com/uc?id={match.group(1)}&export=download"


def safe_delete(path: Path) -> None:
    try:
        if path.exists():
            temp_path = path.with_suffix(path.suffix + f".{int(time())}.del")
            path.rename(temp_path)
            temp_path.unlink()
    except Exception as e:
        print(f"Error deleting file: {str(e)}")


def download_and_resize(url: str, output_dir: str, title_post: str) -> Path:
    sanitized = sanitize_file_name(title_post)
    original_filename = f"{sanitized.upper()}-ORIGI.webp"
    resized_filename = f"{sanitized.lower()}.webp"

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    original_path = output_path / original_filename
    resized_path = output_path / resized_filename

    try:
        download_url = modify_google_drive_url(url)
        with requests.get(download_url, timeout=(10, 60), stream=True) as response:
            response.raise_for_status()
            safe_delete(original_path)
            safe_delete(resized_path)

            with open(original_path, "wb") as f:
                total = 0
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > 25 * 1024 * 1024:
                        raise ValueError("La imagen de origen supera el límite de 25 MB")
                    f.write(chunk)

        # Resize the image
        with Image.open(original_path) as img:
            img = img.convert("RGB")
            img.thumbnail((700, 400), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (700, 400), "white")
            canvas.paste(img, ((700 - img.width) // 2, (400 - img.height) // 2))
            resized = canvas
            resized.save(resized_path, format="webp")

        return resized_path, original_path
    except Exception as e:
        safe_delete(original_path)
        safe_delete(resized_path)
        print(f"Error downloading and resizing image: {str(e)}")
        raise


def delete_files(file1: str, file2: str):
    if os.path.exists(file1):
        os.remove(file1)
    if os.path.exists(file2):
        os.remove(file2)
