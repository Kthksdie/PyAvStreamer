import cv2
import subprocess
import os
import shutil
import sys
import time
import threading

# --- Configuration ---
OBS_IP = "127.0.0.1"  # Replace with the IP of the OBS machine
BASE_PORT = 12345
WIDTH = 1280
HEIGHT = 720
FPS = 30

def get_ffmpeg_path():
    # 1. Check PATH
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    
    # 2. Check common Windows paths (Winget)
    common_paths = [
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-7.0.1-full_build\bin\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
            
    return None

def list_video_devices():
    """
    Probes available video devices (indices 0-9).
    Returns a list of tuples: (index, str_name).
    """
    available_devices = []
    print("\nScanning for video devices (0-9)...")
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            # Try to read a frame to confirm it's working
            ret, _ = cap.read()
            if ret:
                print(f"Index {i}: Camera found")
                available_devices.append((i, f"Camera {i}"))
            cap.release()
            
    return available_devices

def select_video_device(devices):
    """
    Prompts the user to select a video device or stream all.
    Returns:
        int: device index
        str: "ALL"
    """
    if not devices:
        print("No video devices found.")
        sys.exit(1)

    print("A: Stream All Devices")

    while True:
        try:
            selection = input("\nEnter the Index of the camera to use (or 'A' for all): ").strip()

            if selection.upper() == 'A':
                return "ALL"

            index = int(selection)
            # Verify the index is in the valid list
            if any(d[0] == index for d in devices):
                return index
            else:
                print("Invalid index. Please try again.")
        except ValueError:
            print("Please enter a valid number or 'A'.")

def stream_video_task(device_index, device_name, port, stop_event):
    """
    Worker function to stream video from a specific device to a UDP port.
    """
    print(f"Stream for '{device_name}' starting...")
    print(f" - udp://{OBS_IP}:{port}")

    FFMPEG_BIN = get_ffmpeg_path()
    if not FFMPEG_BIN:
        print(f"Error: FFmpeg not found for {device_name}.")
        return

    # Open the video capture
    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        print(f"Failed to open camera index {device_index}")
        return

    # Set properties (optional)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # Read actual properties
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"{device_name} opened: {actual_width}x{actual_height} @ {actual_fps}fps")

    # FFmpeg command
    cmd = [
        FFMPEG_BIN,
        '-y',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',       # OpenCV uses BGR
        '-s', f'{actual_width}x{actual_height}',
        '-r', str(actual_fps) if actual_fps > 0 else str(FPS),
        '-i', '-',                 # Input from pipe
        '-c:v', 'libx264',         # Encode to H.264
        '-preset', 'ultrafast',    # Low latency preset
        '-tune', 'zerolatency',    # Low latency tuning
        '-f', 'mpegts',            # Container
        f'udp://{OBS_IP}:{port}?pkt_size=1316'
    ]

    proc = None
    try:
        # Silencing stderr to avoid console spam when multiple streams are running
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE) #, stderr=subprocess.DEVNULL)
        
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                if not stop_event.is_set():
                    print(f"Error reading frame from {device_name}.")
                break
                
            # Write raw frame to ffmpeg stdin
            try:
                proc.stdin.write(frame.tobytes())
            except Exception:
                if not stop_event.is_set():
                    print(f"FFmpeg process error for {device_name}")
                break
                
    except Exception as e:
        print(f"Exception in stream task {device_name}: {e}")
    finally:
        print(f"Stopping stream: {device_name}")
        cap.release()
        if proc:
            try:
                proc.stdin.close()
                proc.wait(timeout=2)
            except:
                proc.kill()


def main():
    # Verify FFmpeg first
    if not get_ffmpeg_path():
        print("Error: FFmpeg not found. Please install it or add it to your PATH.")
        sys.exit(1)

    devices = list_video_devices()
    selection = select_video_device(devices)
    
    stop_event = threading.Event()
    threads = []

    try:
        if selection == "ALL":
            for i, (device_index, device_name) in enumerate(devices):
                port = BASE_PORT + i
                t = threading.Thread(
                    target=stream_video_task,
                    args=(device_index, device_name, port, stop_event),
                    daemon=True
                )
                t.start()
                threads.append(t)
                time.sleep(0.5) # Stagger start
            
            print(f"\nStreaming {len(threads)} devices. Press Ctrl+C to stop.")

        else:
            # Single device selected
            device_index = selection
            # Find name
            device_name = next(name for idx, name in devices if idx == device_index)
            
            # Use BASE_PORT
            t = threading.Thread(
                target=stream_video_task,
                args=(device_index, device_name, BASE_PORT, stop_event),
                daemon=True
            )
            t.start()
            threads.append(t)
            
            print(f"\nStreaming '{device_name}' to udp://{OBS_IP}:{BASE_PORT}. Press Ctrl+C to stop.")

        # Keep main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping all streams...")
        stop_event.set()
        time.sleep(1)
        # cv2 windows are handled in threads usually but just in case
        cv2.destroyAllWindows()
        print("Done.")

if __name__ == "__main__":
    main()
