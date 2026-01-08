# PyAvStreamer

PyAvStreamer is a comprehensive Python application that streams both audio and video from your local devices (microphones and cameras) to a destination (e.g., OBS) over UDP using FFmpeg.

## Prerequisites

- Python 3.8+
    - Windows: `winget install --id Python.Python.3.13 -v 3.13.0`
- [FFmpeg](https://ffmpeg.org/download.html) installed and operational in your system's PATH.
    - Windows: `winget install Gyan.FFmpeg`

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd PyAvStreamer
    ```

2.  **Create a virtual environment (optional but recommended):**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Usage

The project now runs a single unified script: `src/pyAvStreamer.py`.

### Basic Usage

Run the application with default settings:
```bash
python src/pyAvStreamer.py
```
Follow the interactive menu to add Video or Audio streams.

### CLI Arguments

You can customize the behavior using command-line arguments:

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--obs-ip` | IP address of the OBS machine. | `127.0.0.1` |
| `--base-port-audio` | Base UDP port for audio streams. | `1337` |
| `--base-port-video` | Base UDP port for video streams. | `1729` |
| `--stream-type` | Stream type to enable (`audio`, `video`, `both`). | Manual selection |
| `--max-quality` | Attempt to use the maximum resolution and FPS supported by the camera. | `False` |

### Examples

**Stream video only, automatically selecting all cameras:**
```bash
python src/pyAvStreamer.py --stream-type video
```

**Stream audio only, automatically selecting all microphones:**
```bash
python src/pyAvStreamer.py --stream-type audio
```

**Send to a specific OBS IP address:**
```bash
python src/pyAvStreamer.py --obs-ip 192.168.1.50
```

## Receive in OBS

### Audio
1. Add a **"Media Source"**.
2. Uncheck **"Local File"**.
3. Set **"Input"** to:
    - **Device 1**: `udp://127.0.0.1:1337`
    - **Device 2**: `udp://127.0.0.1:1338`
    - (and so on, incrementing port by 1)
4. Set **"Input Format"** to `mpegts`.

### Video
1.  Add a **"Media Source"**.
2.  Uncheck **"Local File"**.
3.  Set **"Input"** to:
    - **Camera 1**: `udp://127.0.0.1:1729`
    - **Camera 2**: `udp://127.0.0.1:1730`
    - (and so on, incrementing port by 1)
4.  Set **"Input Format"** to `mpegts`.
5.  (Optional) Uncheck "Use hardware decoding" if you experience issues.

## Configuration Details

-   **Audio Codec:** `libmp3lame` (low latency).
-   **Video Codec:** `libx264` (ultrafast preset, zerolatency tune).
-   **Container:** `mpegts`.
-   **Video Pixel Format:** `bgr24` (raw video piped from OpenCV).
