# ASCII Icon Manager

A Python utility for converting images into ASCII artwork and managing application icons in Steam libraries.

## Features

- Convert local images and remote image URLs into ASCII-rendered output.
- Support PNG, JPEG, BMP, WebP, TIFF, ICO and SVG image formats.
- Process individual images or batches of files from a directory.
- Detect installed Steam games across configured libraries.
- Retrieve artwork using local Steam assets and remote sources.
- Back up existing icons before replacement and keep a local change history.
- Restore original icons from the backup history.
- Import images using a URL, Steam URI or application ID.

## Requirements

- Python 3.10 or newer
- Pillow 10.0 or newer
- CairoSVG 2.7 or newer for SVG input and output

## Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/puskainrestpease/ASCII.git
cd ASCII

python -m venv .venv

# Windows
.venv\\Scripts\\activate

# Linux / macOS
source .venv/bin/activate

pip install -r req.txt
```

## Usage

Start the interactive utility:

```bash
python main.py
```

The main menu provides the following operations:

1. Convert images in a selected directory.
2. Find installed Steam games and manage their icons.
3. Import an image through a URL, Steam URI or AppID.
4. Restore previously replaced icons.
5. Review the operation history.

The application stores backups and its local SQLite history in the working directory. Keep these files if you need to restore previously replaced icons.

## Safety

Steam icon replacement is designed around local backups. Do not remove the backup directory or the SQLite database while you still need the restore history.

## Dependencies

- [Pillow](https://python-pillow.org/) — image loading, processing and export.
- [CairoSVG](https://cairosvg.org/) — SVG rasterization and rendering.
