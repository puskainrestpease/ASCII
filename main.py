from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import shutil
import sqlite3
import struct
import tempfile
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, UnidentifiedImageError

try:
    import cairosvg
except Exception:
    cairosvg = None

BASE = Path(__file__).resolve().parent
BACKUP = BASE / "backup"
DB = BASE / "ascii_icon_backups.sqlite3"
URL_DIR = BASE / "url_imports"
RAMP = " .'`^\",:;Il!i~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".ico", ".svg"}
ICON_EXT = {".ico", ".svg", ".png", ".jpg", ".jpeg", ".webp"}
APP_MARKERS = ("dedicated server", "steamvr", "wallpaper engine", "easyanticheat", "easy anti-cheat", "sdk", "redistributable", "ovr dynamic resolution")
MAX_DOWNLOAD = 25 * 1024 * 1024


def font(size: int):
    paths = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "consola.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "cour.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        Path("/System/Library/Fonts/Menlo.ttc"),
    ]
    for path in paths:
        try:
            if path.is_file():
                return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default()


def svg_image(data: bytes) -> Image.Image:
    if cairosvg is None:
        raise RuntimeError("Для SVG установите CairoSVG: py -m pip install CairoSVG")
    png = cairosvg.svg2png(bytestring=data, output_width=1200)
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGBA")


def load_image(source: Path | bytes) -> Image.Image:
    data = source.read_bytes() if isinstance(source, Path) else source
    if data.lstrip().startswith(b"<svg") or (data.lstrip().startswith(b"<?xml") and b"<svg" in data[:4096]):
        return svg_image(data)
    try:
        with Image.open(io.BytesIO(data)) as image:
            if (image.format or "").upper() == "ICO":
                sizes = sorted(image.ico.sizes(), key=lambda s: s[0] * s[1], reverse=True)
                return image.ico.getimage(sizes[0]).convert("RGBA") if sizes else image.convert("RGBA")
            image.seek(0)
            return image.convert("RGBA")
    except UnidentifiedImageError as exc:
        raise ValueError("Файл не является поддерживаемым изображением") from exc


def ascii_grid(source: Image.Image, columns: int = 72):
    image = source.convert("RGBA")
    background = Image.new("RGBA", image.size, (0, 0, 0, 255))
    background.alpha_composite(image)
    rgb = ImageEnhance.Contrast(background.convert("RGB")).enhance(1.25)
    rgb = ImageEnhance.Brightness(rgb).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.12)
    face = font(12)
    box = face.getbbox("Mg")
    cell_h = max(1, box[3] - box[1] + 2)
    cell_w = max(1, round(face.getlength("M")))
    rows = max(1, round(columns * cell_w / cell_h * rgb.height / rgb.width))
    small = rgb.resize((columns, rows), Image.Resampling.LANCZOS)
    return small, face, cell_w, cell_h, rows


def ascii_raster(source: Image.Image, columns: int = 72) -> Image.Image:
    pixels, face, cw, ch, rows = ascii_grid(source, columns)
    out = Image.new("RGB", (columns * cw, rows * ch), "black")
    draw = ImageDraw.Draw(out)
    top = -face.getbbox("Mg")[1]
    for y in range(rows):
        for x in range(columns):
            r, g, b = pixels.getpixel((x, y))
            light = int(.2126 * r + .7152 * g + .0722 * b)
            if light < 7:
                continue
            char = RAMP[min(len(RAMP) - 1, light * (len(RAMP) - 1) // 255)]
            if char != " ":
                draw.text((x * cw, y * ch + top), char, font=face, fill=(r, g, b))
    return out


def save_ascii(source: Image.Image, target: Path, columns: int | None = None):
    target.parent.mkdir(parents=True, exist_ok=True)
    ext = target.suffix.lower()
    if columns is None:
        columns = 48 if ext == ".ico" or target.name.endswith("_icon.jpg") else 88
    if ext == ".svg":
        pixels, face, cw, ch, rows = ascii_grid(source, columns)
        width, height = columns * cw, rows * ch
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#000"/><g font-family="Consolas,monospace" font-size="12">']
        baseline = 10
        for y in range(rows):
            for x in range(columns):
                r, g, b = pixels.getpixel((x, y))
                light = int(.2126 * r + .7152 * g + .0722 * b)
                if light < 7:
                    continue
                char = RAMP[min(len(RAMP) - 1, light * (len(RAMP) - 1) // 255)]
                if char != " ":
                    parts.append(f'<text x="{x*cw}" y="{y*ch+baseline}" fill="#{r:02x}{g:02x}{b:02x}">{html.escape(char)}</text>')
        parts.append("</g></svg>")
        target.write_text("".join(parts), encoding="utf-8")
        return
    art = ascii_raster(source, columns)
    if ext == ".ico":
        square = Image.new("RGBA", (256, 256), (0, 0, 0, 255))
        fitted = ImageOps.contain(art.convert("RGBA"), (248, 248), Image.Resampling.LANCZOS)
        square.alpha_composite(fitted, ((256 - fitted.width) // 2, (256 - fitted.height) // 2))
        square.save(target, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
    elif ext in {".jpg", ".jpeg"}:
        art.save(target, format="JPEG", quality=94, optimize=True)
    elif ext == ".webp":
        art.save(target, format="WEBP", quality=95, method=6)
    elif ext in {".tif", ".tiff"}:
        art.save(target, format="TIFF")
    elif ext == ".bmp":
        art.save(target, format="BMP")
    else:
        art.save(target, format="PNG", optimize=True)


def db():
    BACKUP.mkdir(exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS replacements(id INTEGER PRIMARY KEY AUTOINCREMENT, original_path TEXT NOT NULL, backup_path TEXT, original_existed INTEGER NOT NULL, created_at TEXT NOT NULL, source_type TEXT NOT NULL, source_url TEXT, sha256_before TEXT, sha256_after TEXT, status TEXT NOT NULL DEFAULT 'active', source_label TEXT)")
    fields = {row[1] for row in con.execute("PRAGMA table_info(replacements)")}
    if "source_label" not in fields:
        con.execute("ALTER TABLE replacements ADD COLUMN source_label TEXT")
    con.execute("CREATE INDEX IF NOT EXISTS idx_replacements_path ON replacements(original_path)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_replacements_status ON replacements(status)")
    con.commit()
    return con


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def apply(target: Path, image: Image.Image, label: str, source: str = "game") -> bool:
    target = target.expanduser()
    if target.is_symlink() or target.suffix.lower() not in IMAGE_EXT:
        print(f"Пропуск: {target}")
        return False
    target = target.resolve()
    con = db()
    temp = None
    try:
        if con.execute("SELECT 1 FROM replacements WHERE original_path=? AND status='active' LIMIT 1", (str(target),)).fetchone():
            print(f"Уже заменено: {target.name}")
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{target.stem}_{uuid.uuid4().hex[:6]}_", suffix=target.suffix, dir=target.parent)
        os.close(fd)
        temp = Path(name)
        save_ascii(image, temp)
        existed = target.is_file()
        backup = None
        if existed:
            next_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM replacements").fetchone()[0]
            backup = BACKUP / f"backup_{next_id:06d}{target.suffix.lower()}"
            shutil.copy2(target, backup)
        before = digest(target) if existed else None
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO replacements(original_path,backup_path,original_existed,created_at,source_type,sha256_before,status,source_label) VALUES(?,?,?,?,?,?, 'active', ?)", (str(target), str(backup) if backup else None, int(existed), datetime.now().astimezone().isoformat(timespec="seconds"), source, before, label))
        os.replace(temp, target)
        temp = None
        con.commit()
        print(f"OK  {label}: {target}")
        return True
    except PermissionError:
        con.rollback()
        print(f"Нет доступа: {target} (закрой Steam/игру или запусти от администратора)")
        return False
    except Exception as exc:
        con.rollback()
        print(f"Ошибка {target}: {exc}")
        return False
    finally:
        if temp and temp.exists():
            temp.unlink(missing_ok=True)
        con.close()


def restore():
    con = db()
    rows = con.execute("SELECT * FROM replacements WHERE status='active' ORDER BY id DESC").fetchall()
    done = 0
    for row in rows:
        target = Path(row["original_path"])
        try:
            if row["original_existed"]:
                backup = Path(row["backup_path"])
                if not backup.is_file():
                    raise FileNotFoundError(backup)
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=".restore_", suffix=target.suffix, dir=target.parent)
                os.close(fd)
                temp = Path(name)
                try:
                    shutil.copy2(backup, temp)
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
            con.execute("UPDATE replacements SET status='restored' WHERE id=?", (row["id"],))
            con.commit()
            done += 1
        except Exception as exc:
            con.rollback()
            print(f"Не восстановлен {target}: {exc}")
    con.close()
    print(f"Восстановлено: {done}/{len(rows)}")


def history():
    con = db()
    rows = con.execute("SELECT id,original_path,backup_path,source_label,created_at,status FROM replacements ORDER BY id DESC LIMIT 30").fetchall()
    con.close()
    for row in rows:
        print(f"#{row['id']} [{row['status']}] {row['source_label'] or ''}\n{row['original_path']}\n{row['backup_path'] or 'без исходника'}")


def choose_folder(title="Выберите папку") -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        value = filedialog.askdirectory(title=title)
        root.destroy()
        if value:
            return Path(value).resolve()
    except Exception:
        pass
    value = input(f"{title}: ").strip().strip('"')
    path = Path(value).expanduser()
    return path.resolve() if path.is_dir() else None


def batch_mode():
    folder = choose_folder("Папка с изображениями")
    if not folder:
        return
    recursive = input("Включить подпапки? [д/н, Enter=д]: ").strip().lower() not in {"н", "no", "n"}
    output = folder / "ascii_output"
    files = folder.rglob("*") if recursive else folder.iterdir()
    selected = [p for p in files if p.is_file() and p.suffix.lower() in IMAGE_EXT and output not in p.parents and not p.stem.lower().endswith("_ascii")]
    print(f"Файлов: {len(selected)}")
    for i, path in enumerate(selected, 1):
        dest = (output / path.relative_to(folder)).with_name(path.stem + "_ascii" + path.suffix.lower())
        try:
            save_ascii(load_image(path), dest)
            print(f"[{i}/{len(selected)}] {path.name}")
        except Exception as exc:
            print(f"Ошибка {path}: {exc}")


def steam_roots() -> list[Path]:
    found = []
    def add(value):
        try:
            p = Path(str(value).strip().strip('"')).expanduser()
            if p.is_file():
                p = p.parent
            p = p.resolve()
            if p.is_dir() and ((p / "steam.exe").exists() or (p / "steamapps").is_dir()) and p not in found:
                found.append(p)
        except Exception:
            pass
    if os.name == "nt":
        try:
            import winreg
            for key_path in (r"Software\Valve\Steam", r"Software\WOW6432Node\Valve\Steam"):
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                        for item in ("SteamPath", "InstallPath"):
                            try:
                                add(winreg.QueryValueEx(key, item)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except Exception:
            pass
    add(Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam")
    add(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Steam")
    if os.name != "nt":
        add(Path.home() / ".steam/steam")
        add(Path.home() / ".local/share/Steam")
    return found


def libraries(root: Path) -> list[Path]:
    result = [root]
    file = root / "steamapps/libraryfolders.vdf"
    if file.is_file():
        text = file.read_text(encoding="utf-8", errors="ignore")
        for raw in re.findall(r'"path"\s*"((?:\\.|[^"\\])*)"', text, re.I):
            value = raw.replace("\\\\", "\\").replace("\\\"", '"')
            path = Path(value)
            if path.is_dir() and path not in result:
                result.append(path)
    return result


def manifest(path: Path) -> dict[str, str] | None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    def get(key):
        m = re.search(r'"' + re.escape(key) + r'"\s*"((?:\\.|[^"\\])*)"', text, re.I)
        return m.group(1).replace("\\\\", "\\") if m else ""
    appid = get("appid") or re.sub(r"\D", "", path.stem)
    name, folder = get("name"), get("installdir")
    if not appid.isdigit() or not folder:
        return None
    return {"appid": appid, "name": name or f"App {appid}", "folder": folder}


def cstring(data: bytes, pos: int, end: int):
    stop = data.find(b"\0", pos, end)
    if stop < 0:
        raise ValueError("Invalid string")
    return data[pos:stop].decode("utf-8", "replace"), stop + 1


def parse_kv(data: bytes, pos: int, end: int, table: list[str] | None, depth=0):
    if depth > 64:
        raise ValueError("VDF nested too deep")
    result = {}
    while pos < end:
        kind = data[pos]
        pos += 1
        if kind == 8:
            return result, pos
        if table is not None:
            if pos + 4 > end:
                raise ValueError("Bad key index")
            index = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            key = table[index] if index < len(table) else str(index)
        else:
            key, pos = cstring(data, pos, end)
        if kind == 0:
            value, pos = parse_kv(data, pos, end, table, depth + 1)
        elif kind == 1:
            value, pos = cstring(data, pos, end)
        elif kind == 2:
            value = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        elif kind == 3:
            value = struct.unpack_from("<f", data, pos)[0]
            pos += 4
        elif kind == 4:
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        elif kind == 5:
            stop = pos
            while stop + 1 < end and data[stop:stop + 2] != b"\0\0":
                stop += 2
            value = data[pos:stop].decode("utf-16le", "replace")
            pos = stop + 2
        elif kind == 6:
            value = data[pos:pos + 4]
            pos += 4
        elif kind == 7:
            value = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        elif kind == 10:
            value = struct.unpack_from("<q", data, pos)[0]
            pos += 8
        else:
            raise ValueError(f"Unknown VDF type {kind}")
        if pos > end:
            raise ValueError("VDF record overflow")
        result[key] = value
    return result, pos


def appinfo(root: Path, wanted: set[str]) -> dict[str, dict[str, str]]:
    path = root / "appcache/appinfo.vdf"
    if not path.is_file():
        return {}
    data = path.read_bytes()
    if len(data) < 8 or data[1:4] != b"DV\x07":
        return {}
    version = data[0]
    if version not in {39, 40, 41}:
        return {}
    if version == 41:
        if len(data) < 16:
            return {}
        limit = struct.unpack_from("<Q", data, 8)[0]
        if limit < 16 or limit + 4 > len(data):
            return {}
        count = struct.unpack_from("<I", data, limit)[0]
        pos_table, table = limit + 4, []
        for _ in range(min(count, 100000)):
            value, pos_table = cstring(data, pos_table, len(data))
            table.append(value)
        pos = 16
    else:
        limit, table, pos = len(data), None, 8
    result = {}
    fixed = 60 if version >= 40 else 40
    while pos + 8 <= limit:
        appid, size = struct.unpack_from("<II", data, pos)
        pos += 8
        if appid == 0:
            break
        end = pos + size
        if size <= fixed or end > limit:
            break
        if str(appid) in wanted:
            try:
                tree, _ = parse_kv(data, pos + fixed, end, table)
                app = tree.get("appinfo", tree)
                common = next((v for k, v in app.items() if str(k).casefold() == "common" and isinstance(v, dict)), {})
                values = {str(k).casefold(): str(v) for k, v in common.items() if not isinstance(v, dict)}
                result[str(appid)] = {"type": values.get("type", "").casefold(), "clienticon": values.get("clienticon", "").lower()}
            except Exception:
                pass
        pos = end
    return result


def installed_games(roots: list[Path]):
    games = {}
    for root in roots:
        for library in libraries(root):
            apps = library / "steamapps"
            if not apps.is_dir():
                continue
            for file in apps.glob("appmanifest_*.acf"):
                try:
                    data = manifest(file)
                    if not data:
                        continue
                    folder = apps / "common" / data["folder"]
                    if not folder.is_dir():
                        continue
                    if any(marker in data["name"].casefold() for marker in APP_MARKERS):
                        continue
                    games[data["appid"]] = {**data, "path": folder, "library": library}
                except OSError:
                    pass
    for root in roots:
        meta = appinfo(root, set(games))
        for appid, game in list(games.items()):
            game.update(meta.get(appid, {}))
            if game.get("type") in {"tool", "application", "demo", "dlc", "music", "video", "config", "driver"}:
                games.pop(appid, None)
    return sorted(games.values(), key=lambda x: x["name"].casefold())


def local_icon(appid: str, roots: list[Path], clienticon: str = "") -> Path | None:
    found = []
    for root in roots:
        cache = root / "appcache/librarycache"
        for pattern in (f"{appid}_icon.*", f"{appid}-icon.*"):
            found.extend(p for p in cache.glob(pattern) if p.is_file() and p.suffix.lower() in ICON_EXT)
        nested = cache / appid
        if nested.is_dir():
            found.extend(p for p in nested.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".ico"} and re.fullmatch(r"[a-f0-9]{40}\.(jpg|jpeg|png|ico)", p.name, re.I))
        users = root / "userdata"
        if users.is_dir():
            for grid in users.glob("*/config/grid"):
                for pattern in (f"{appid}_icon.*", f"{appid}-icon.*"):
                    found.extend(p for p in grid.glob(pattern) if p.is_file() and p.suffix.lower() in ICON_EXT)
        if clienticon and re.fullmatch(r"[a-f0-9]{40}", clienticon):
            icon = root / "steam/games" / f"{clienticon}.ico"
            if icon.is_file():
                found.append(icon)
    if not found:
        return None
    def rank(path):
        text = str(path).casefold()
        return (0 if "librarycache" in text and path.parent.name == "librarycache" else 1 if "librarycache" in text else 2 if "config" in text else 3, path.suffix.lower() not in {".ico", ".jpg", ".png"}, str(path).casefold())
    return sorted(set(p.resolve() for p in found), key=rank)[0]


def request_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ASCIIIconManager/2.0"})
    with urllib.request.urlopen(req, timeout=18) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("Download too large")
    return data


def icon_hash_from_api(appid: str) -> str:
    try:
        data = request_bytes(f"https://steamicons.adriansteffan.com/{appid}")
        text = data.decode("utf-8", "ignore")
        try:
            obj = json.loads(text)
            def walk(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if "icon" in str(key).casefold() and isinstance(item, str) and re.fullmatch(r"[a-f0-9]{40}", item, re.I):
                            return item.lower()
                    for item in value.values():
                        result = walk(item)
                        if result:
                            return result
                if isinstance(value, list):
                    for item in value:
                        result = walk(item)
                        if result:
                            return result
                return None
            value = walk(obj)
            if value:
                return value
        except json.JSONDecodeError:
            pass
        match = re.search(r"\b[a-f0-9]{40}\b", text, re.I)
        return match.group(0).lower() if match else ""
    except Exception:
        return ""


def square_pad(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 255))
    fitted = ImageOps.contain(image, (side, side), Image.Resampling.LANCZOS)
    canvas.alpha_composite(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return canvas


def download_game_image(appid: str, clienticon: str = "") -> tuple[Image.Image, str]:
    hashes = [clienticon] if re.fullmatch(r"[a-f0-9]{40}", clienticon or "", re.I) else []
    if not hashes:
        found = icon_hash_from_api(appid)
        if found:
            hashes.append(found)
    for icon_hash in hashes:
        for host in ("https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps", "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps", "https://shared.fastly.steamstatic.com/community_assets/images/apps"):
            for ext in (".ico", ".jpg", ".png"):
                try:
                    image = load_image(request_bytes(f"{host}/{appid}/{icon_hash}{ext}"))
                    return image, f"Steam icon {icon_hash}"
                except Exception:
                    pass
    try:
        details = json.loads(request_bytes(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=english").decode("utf-8-sig"))
        app = (details.get(str(appid)) or {}).get("data") or {}
        for key in ("header_image", "capsule_image", "capsule_imagev5"):
            url = app.get(key)
            if url:
                return square_pad(load_image(request_bytes(url))), f"Steam Store: {app.get('name', appid)}"
    except Exception:
        pass
    raise RuntimeError("Иконка не найдена локально и не загрузилась из Steam. Проверь интернет или обнови кэш Steam.")


def binary_shortcuts(data: bytes):
    tree, _ = parse_kv(data, 0, len(data), None)
    return tree


def steam_shortcuts(roots: list[Path]):
    result = {}
    for root in roots:
        users = root / "userdata"
        if not users.is_dir():
            continue
        for user in users.iterdir():
            file = user / "config/shortcuts.vdf"
            if not file.is_file():
                continue
            try:
                tree = binary_shortcuts(file.read_bytes())
                shortcuts = next((v for k, v in tree.items() if str(k).casefold() == "shortcuts"), {})
                if not isinstance(shortcuts, dict):
                    continue
                for entry in shortcuts.values():
                    if not isinstance(entry, dict):
                        continue
                    values = {str(k).casefold(): v for k, v in entry.items()}
                    name = str(values.get("appname", "")).strip()
                    icon = str(values.get("icon", "")).strip().strip('"')
                    if not name or not icon:
                        continue
                    path = Path(os.path.expandvars(icon)).expanduser()
                    if not path.is_file():
                        path = root / "steam/games" / Path(icon.replace("\\", "/")).name
                    if path.is_file() and path.suffix.lower() in ICON_EXT:
                        result[path.resolve()] = name
            except Exception:
                pass
    return result


def game_folder_icons(game: dict[str, Any]):
    stems = {"icon", "app", "appicon", "app_icon", "game", "gameicon", "game_icon"}
    try:
        return [p.resolve() for p in game["path"].iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in ICON_EXT and p.stem.casefold() in stems]
    except OSError:
        return []


def scan_custom_folder(folder: Path):
    stems = {"icon", "app", "appicon", "app_icon", "game", "gameicon", "game_icon"}
    result = []
    roots = [folder]
    try:
        roots += [p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()]
    except OSError:
        pass
    for root in roots:
        try:
            for path in root.iterdir():
                if path.is_file() and not path.is_symlink() and path.suffix.lower() in ICON_EXT and path.stem.casefold() in stems:
                    result.append((path.resolve(), root.name if root != folder else folder.name))
        except OSError:
            pass
    return result


def steam_mode():
    roots = steam_roots()
    if not roots:
        print("Steam не найден.")
        return
    games = installed_games(roots)
    shortcut_icons = steam_shortcuts(roots)
    if not games and not shortcut_icons:
        print("Игры и ярлыки Steam не найдены.")
        return
    print(f"Игры: {len(games)} | сторонние ярлыки с иконками: {len(shortcut_icons)}")
    for i, game in enumerate(games, 1):
        print(f"{i}. {game['name']} [{game['appid']}]")
    if input("Обработать найденное? [д/н]: ").strip().casefold() not in {"д", "да", "y", "yes"}:
        return
    done = failed = 0
    for i, game in enumerate(games, 1):
        appid, label = game["appid"], game["name"]
        try:
            target = local_icon(appid, roots, game.get("clienticon", ""))
            source = "steam-local"
            if target:
                image = load_image(target)
            else:
                image, source = download_game_image(appid, game.get("clienticon", ""))
                target = roots[0] / "appcache/librarycache" / f"{appid}_icon.jpg"
            target_label = f"{label} [{appid}]"
            if apply(target, image, target_label, source):
                done += 1
            else:
                failed += 1
            for extra in game_folder_icons(game):
                if apply(extra, load_image(extra), f"{label} [{appid}] / {extra.name}", "game-folder"):
                    done += 1
        except Exception as exc:
            failed += 1
            print(f"{i}/{len(games)} {label}: {exc}")
    for path, label in shortcut_icons.items():
        try:
            if apply(path, load_image(path), label, "steam-shortcut"):
                done += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            print(f"{label}: {exc}")
    if input("Проверить дополнительную папку с играми? [д/н]: ").strip().casefold() in {"д", "да", "y", "yes"}:
        folder = choose_folder("Папка игры или библиотека")
        if folder:
            for path, label in scan_custom_folder(folder):
                try:
                    if apply(path, load_image(path), label, "custom-game-folder"):
                        done += 1
                except Exception as exc:
                    failed += 1
                    print(f"{path}: {exc}")
    print(f"Готово: {done}; пропущено/ошибок: {failed}")


def extract_appid(value: str) -> str | None:
    value = value.strip().strip('"').strip("'")
    for pattern in (r"^steam://(?:rungameid|run|install)/(\d+)", r"^https?://store\.steampowered\.com/app/(\d+)"):
        match = re.search(pattern, value, re.I)
        if match:
            return match.group(1)
    return value if value.isdigit() else None


def url_mode():
    value = input("URL изображения / Steam URI / AppID: ").strip()
    appid = extract_appid(value)
    if appid:
        roots = steam_roots()
        local = local_icon(appid, roots) if roots else None
        try:
            image = load_image(local) if local else download_game_image(appid)[0]
            target = local or ((roots[0] / "appcache/librarycache" / f"{appid}_icon.jpg") if roots else URL_DIR / f"{appid}_ascii.png")
            if input("Установить в Steam? [д/н]: ").strip().casefold() in {"д", "да", "y", "yes"} and roots:
                apply(target, image, f"Steam AppID {appid}", "steam-url")
            else:
                target = URL_DIR / f"{appid}_ascii.png"
                save_ascii(image, target)
                print(target)
        except Exception as exc:
            print(exc)
        return
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        print("Нужна прямая ссылка http(s) на картинку или Steam URI.")
        return
    try:
        image = load_image(request_bytes(value))
        name = Path(parsed.path).stem or "image"
        URL_DIR.mkdir(exist_ok=True)
        output = URL_DIR / f"{name}_ascii.png"
        save_ascii(image, output)
        print(output)
    except Exception as exc:
        print(f"Не удалось загрузить изображение: {exc}")


def main():
    while True:
        print("\nASCII ICON MANAGER\n1. Конвертировать папку\n2. Иконки установленных Steam-игр\n3. URL / Steam AppID\n4. Восстановить оригиналы\n5. История\n0. Выход")
        choice = input("Выбор: ").strip()
        if choice == "1":
            batch_mode()
        elif choice == "2":
            steam_mode()
        elif choice == "3":
            url_mode()
        elif choice == "4":
            if input("Восстановить все оригиналы? [д/н]: ").strip().casefold() in {"д", "да", "y", "yes"}:
                restore()
        elif choice == "5":
            history()
        elif choice == "0":
            break
        else:
            print("Неизвестный пункт.")
        input("Enter для продолжения...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nВыход.")
