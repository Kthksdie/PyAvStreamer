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

The project contains two main scripts: `audioCast.py` for audio streaming and `videoCast.py` for video streaming.

### Audio Streaming (`audioCast.py`)

1.  Run the application:
    ```bash
    python audioCast.py
    ```

2.  **Select Audio Source:**
    -   Enter the **Index** of a specific microphone to stream just that device.
    -   Enter **'A'** to stream **ALL** detected input devices simultaneously.

### Video Streaming (`videoCast.py`)

1.  Run the application:
    ```bash
    python videoCast.py
    ```

2.  **Select Video Source:**
    -   Enter the **Index** of a specific camera to stream just that device.
    -   Enter **'A'** to stream **ALL** detected video devices simultaneously.

## Receive in OBS
### Audio
1. Add a "Media Source".
2. Uncheck "Local File".
3. Set "Input" to:
    - **Single Device**: `udp://127.0.0.1:1337`
    - **All Devices**:
        - Device 1: `udp://127.0.0.1:1337`
        - Device 2: `udp://127.0.0.1:1338`
        - (and so on...)
4. Set "Input Format" to `mpegts`.

### Video
1.  Add a **"Media Source"**.
2.  Uncheck **"Local File"**.
3.  Set **"Input"** to:
    - **Single Device**: `udp://127.0.0.1:12345`
    - **All Devices**:
        - Camera 1: `udp://127.0.0.1:12345`
        - Camera 2: `udp://127.0.0.1:12346`
        - (and so on...)
4.  Set **"Input Format"** to `mpegts`.
5.  (Optional) Uncheck "Use hardware decoding" if you experience issues.

## Configuration

-   **Audio Codec:** Uses `libmp3lame` for low latency.
-   **Video Codec:** `libx264` (ultrafast preset, zerolatency tune).
-   **Container:** `mpegts`.
-   **Video Pixel Format:** `bgr24` (raw video piped from OpenCV).


