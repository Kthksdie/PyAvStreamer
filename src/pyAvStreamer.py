import pyaudio
import cv2
import subprocess
import os
import shutil
import sys
import threading
import time
import argparse
import ctypes
import queue

# --- Configuration ---
OBS_IP = "127.0.0.1"
BASE_PORT_AUDIO = 1337
BASE_PORT_VIDEO = 1729
CHUNK = 4096
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE = 44100
VIDEO_WIDTH = 0
VIDEO_HEIGHT = 0
VIDEO_FPS = 0
USE_MAX_QUALITY = False

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

def set_high_priority():
    """Sets the process priority to High on Windows."""
    try:
        # HIGH_PRIORITY_CLASS = 0x00000080
        pid = os.getpid()
        kernel32 = ctypes.windll.kernel32
        
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.SetPriorityClass.restype = ctypes.c_bool
        
        handle = kernel32.GetCurrentProcess()
        
        # Enable extended error info if needed, but usually just GetLastError works if called immediately.
        success = kernel32.SetPriorityClass(handle, 0x00000080)
        
        if not success:
            err_code = kernel32.GetLastError()
            print(f"Warning: Failed to set process priority to HIGH. Error code: {err_code}")
        else:
            print("Process priority set to HIGH.")
    except Exception as e:
        print(f"Warning: Failed to set process priority: {e}")

# --- Audio Functions ---

def list_audio_devices(pyaudio_instance):
    """
    Lists available audio input devices using the MME host API.
    Returns a list of tuples: (index, name).
    """
    # Find the MME Host API index
    mme_index = -1
    for i in range(pyaudio_instance.get_host_api_count()):
        info = pyaudio_instance.get_host_api_info_by_index(i)
        if info.get('name') == 'MME':
            mme_index = i
            break

    if mme_index == -1:
        print("Error: MME Host API not found.")
        return []

    devices = []
    print("\nAvailable Audio Input Devices:")
    for i in range(pyaudio_instance.get_device_count()):
        try:
            device_info = pyaudio_instance.get_device_info_by_index(i)
            # Filter for Input devices on MME API
            if (device_info.get('maxInputChannels') > 0 and 
                device_info.get('hostApi') == mme_index):
                
                name = device_info.get('name')
                # Exclude the mapper
                if name != "Microsoft Sound Mapper - Input":
                    print(f"Index {i}: {name}")
                    devices.append((i, name))
                    
        except Exception as e:
            print(f"Error reading device {i}: {e}")
            
    return devices

def stream_audio_task(pyaudio_instance, device_index, device_name, port, stop_event):
    """
    Worker function to stream audio from a specific device to a UDP port.
    """
    print(f"[Audio] Stream for '{device_name}' starting...")
    print(f" - srt://@:{port}?mode=listener&latency=50000")

    FFMPEG_BIN = get_ffmpeg_path()
    if not FFMPEG_BIN:
        print(f"Error: FFmpeg not found for {device_name}.")
        return

    try:
        # Open the microphone stream
        stream = pyaudio_instance.open(
            format=AUDIO_FORMAT,
            channels=AUDIO_CHANNELS,
            rate=AUDIO_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK
        )
    except Exception as e:
        print(f"Failed to open audio stream for {device_name}: {e}")
        return

    # FFmpeg command
    cmd = [
        FFMPEG_BIN,
        '-use_wallclock_as_timestamps', '1',
        '-f', 's16le',
        '-ar', str(AUDIO_RATE),
        '-ac', str(AUDIO_CHANNELS),
        '-i', 'pipe:0',
        # --- New Optimization Flags ---
        '-probesize', '32',           # Minimal data analysis before starting
        '-analyzeduration', '0',      # Start streaming instantly
        '-fflags', 'nobuffer+genpts', # Disable FFmpeg's internal buffer
        '-flush_packets', '1',        # Push every packet to the network immediately
        # ------------------------------
        '-c:a', 'libmp3lame',
        '-b:a', '128k',               # Explicit bitrate helps maintain steady flow
        '-f', 'mpegts',
        f'srt://{OBS_IP}:{port}?mode=caller&latency=50000'
    ]

    try:
        # Silencing stderr to avoid console spam
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Failed to start FFmpeg for {device_name}: {e}")
        stream.close()
        return

    audio_queue = queue.Queue(maxsize=50)
    local_stop_event = threading.Event()

    def read_mic():
        """Reads data from microphone and puts into queue."""
        try:
            while not stop_event.is_set() and not local_stop_event.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    if not data:
                        break
                    audio_queue.put(data)
                except Exception as e:
                    if not stop_event.is_set() and not local_stop_event.is_set():
                        print(f"Error reading audio {device_name}: {e}")
                    local_stop_event.set()
                    break
        except Exception:
            local_stop_event.set()

    def write_ffmpeg():
        """Reads data from queue and writes to FFmpeg stdin."""
        try:
            while not stop_event.is_set() and not local_stop_event.is_set():
                try:
                    data = audio_queue.get(timeout=0.5)
                    try:
                        proc.stdin.write(data)
                    except Exception as e:
                        if not stop_event.is_set() and not local_stop_event.is_set():
                            print(f"Error writing audio to ffmpeg {device_name}: {e}")
                        local_stop_event.set()
                        break
                    finally:
                        audio_queue.task_done()
                except queue.Empty:
                    continue
        except Exception:
            local_stop_event.set()

    reader_thread = threading.Thread(target=read_mic, daemon=True)
    writer_thread = threading.Thread(target=write_ffmpeg, daemon=True)

    reader_thread.start()
    writer_thread.start()

    # Wait until global stop or local error
    while not stop_event.is_set() and not local_stop_event.is_set():
        time.sleep(0.5)

    print(f"Stopping audio stream: {device_name}")
    
    # Ensure threads stop
    local_stop_event.set()

    # Cleanup
    try:
        stream.stop_stream()
        stream.close()
    except:
        pass

    try:
        proc.stdin.close()
        proc.wait(timeout=2)
    except:
        proc.kill()


# --- Video Functions ---

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

def stream_video_task(device_index, device_name, port, stop_event):
    """
    Worker function to stream video from a specific device to a UDP port.
    """
    print(f"[Video] Stream for '{device_name}' starting...")
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

    # Set properties
    if USE_MAX_QUALITY:
        print(f"Attempting to set max quality for {device_name}...")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
        cap.set(cv2.CAP_PROP_FPS, 60)
    else:
        if VIDEO_WIDTH > 0:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
        if VIDEO_HEIGHT > 0:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
        if VIDEO_FPS > 0:
            cap.set(cv2.CAP_PROP_FPS, VIDEO_FPS)

    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)

    print(f"{device_name} opened: {actual_width}x{actual_height} @ {actual_fps}fps")

    # FFmpeg command
    cmd = [
        FFMPEG_BIN,
        '-y',
        '-use_wallclock_as_timestamps', '1',
        '-f', 'rawvideo',
        '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24',       # OpenCV uses BGR
        '-s', f'{actual_width}x{actual_height}',
        '-r', str(actual_fps) if actual_fps > 0 else (str(VIDEO_FPS) if VIDEO_FPS > 0 else "30"),
        '-i', '-',                 # Input from pipe
        '-c:v', 'libx264',         # Encode to H.264
        '-preset', 'ultrafast',    # Low latency preset
        '-tune', 'zerolatency',    # Low latency tuning
        '-fflags', '+genpts',
        '-f', 'mpegts',            # Container
        f'udp://{OBS_IP}:{port}?pkt_size=1316'
    ]

    try:
        # Silencing stderr to avoid console spam
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                if not stop_event.is_set():
                    print(f"Error reading frame from {device_name}.")
                break
                
            try:
                proc.stdin.write(frame.tobytes())
            except Exception:
                if not stop_event.is_set():
                    print(f"FFmpeg process error for {device_name}")
                break
                
    except Exception as e:
        print(f"Exception in video stream task {device_name}: {e}")
    finally:
        print(f"Stopping video stream: {device_name}")
        cap.release()
        try:
            if proc:
                proc.stdin.close()
                proc.wait(timeout=2)
        except:
            if proc:
                proc.kill()

# --- Main App ---

def main():
    global OBS_IP, BASE_PORT_AUDIO, BASE_PORT_VIDEO, USE_MAX_QUALITY

    set_high_priority()

    if not get_ffmpeg_path():
        print("Error: FFmpeg not found. Please install it or add it to your PATH.")
        sys.exit(1)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="PyAvStreamer - Audio/Video Streaming Tool")
    parser.add_argument("--obs-ip", default=OBS_IP, help=f"IP address of the OBS machine (default: {OBS_IP})")
    parser.add_argument("--base-port-audio", type=int, default=BASE_PORT_AUDIO, help=f"Base UDP port for audio (default: {BASE_PORT_AUDIO})")
    parser.add_argument("--base-port-video", type=int, default=BASE_PORT_VIDEO, help=f"Base UDP port for video (default: {BASE_PORT_VIDEO})")
    parser.add_argument("--stream-type", choices=['audio', 'video', 'both'], default=None, help="Stream type to enable (audio or video). Default: Manual selection")
    parser.add_argument("--max-quality", action="store_true", help="Attempt to use the maximum resolution and FPS supported by the camera")
    args = parser.parse_args()

    # Update globals with arguments
    OBS_IP = args.obs_ip
    BASE_PORT_AUDIO = args.base_port_audio
    BASE_PORT_VIDEO = args.base_port_video
    USE_MAX_QUALITY = args.max_quality
    
    # Logic: If specific type provided, filter menu AND auto-execute. If None, show all.
    STREAM_TYPE = args.stream_type if args.stream_type else 'both'

    p = pyaudio.PyAudio()
    active_threads = []
    audio_offset = 0
    video_offset = 0
    stop_event = threading.Event()
    
    # Auto-start logic
    auto_choices = []
    if args.stream_type == 'audio':
        auto_choices = ["1"]
    elif args.stream_type == 'video':
        auto_choices = ["2"]
    elif args.stream_type == 'both':
        auto_choices = ["1", "2"]

    try:
        while True:
            choice = None
            if auto_choices:
                choice = auto_choices.pop(0)
            else:
                print("\n=== PyAvStreamer ===")
                print(f"Active Streams: {len(active_threads)}")
                
                if STREAM_TYPE in ['audio', 'both']:
                    print("1. Add Audio Stream")
                if STREAM_TYPE in ['video', 'both']:
                    print("2. Add Video Stream")
                print("3. Stop All and Exit")
                
                choice = input("Select option: ").strip()

            if choice == "1":
                if STREAM_TYPE not in ['audio', 'both']:
                    print("Audio streaming is disabled in this mode.")
                    continue
                    
                devices = list_audio_devices(p)
                if not devices:
                    print("No audio devices found.")
                    continue
                
                if args.stream_type:
                    print("Auto-selecting ALL audio devices per --stream-type argument.")
                    sel = 'A'
                else:
                    sel = input("Enter Audio Device Index (or 'A' for All): ").strip()
                to_start = []
                
                if sel.upper() == 'A':
                    from_port = BASE_PORT_AUDIO + audio_offset
                    for i, (idx, name) in enumerate(devices):
                        to_start.append((idx, name, from_port + i))
                else:
                    try:
                        idx = int(sel)
                        name = next((n for i, n in devices if i == idx), None)
                        if name:
                            port = BASE_PORT_AUDIO + audio_offset
                            to_start.append((idx, name, port))
                        else:
                            print("Invalid index.")
                    except ValueError:
                        print("Invalid input.")

                audio_offset += len(to_start)
                for idx, name, port in to_start:
                    t = threading.Thread(
                        target=stream_audio_task,
                        args=(p, idx, name, port, stop_event),
                        daemon=True
                    )
                    t.start()
                    active_threads.append(t)
                    time.sleep(0.5)

            elif choice == "2":
                if STREAM_TYPE not in ['video', 'both']:
                    print("Video streaming is disabled in this mode.")
                    continue

                devices = list_video_devices()
                if not devices:
                    print("No video devices found.")
                    continue

                if args.stream_type:
                    print("Auto-selecting ALL video devices per --stream-type argument.")
                    sel = 'A'
                else:
                    sel = input("Enter Video Device Index (or 'A' for All): ").strip()
                to_start = []
                
                if sel.upper() == 'A':
                    from_port = BASE_PORT_VIDEO + video_offset
                    for i, (idx, name) in enumerate(devices):
                        to_start.append((idx, name, from_port + i))
                else:
                    try:
                        idx = int(sel)
                        name = next((n for i, n in devices if i == idx), None)
                        if name:
                            port = BASE_PORT_VIDEO + video_offset
                            to_start.append((idx, name, port))
                        else:
                            print("Invalid index.")
                    except ValueError:
                        print("Invalid input.")

                video_offset += len(to_start)
                for idx, name, port in to_start:
                    t = threading.Thread(
                        target=stream_video_task,
                        args=(idx, name, port, stop_event),
                        daemon=True
                    )
                    t.start()
                    active_threads.append(t)
                    time.sleep(0.5)

            elif choice == "3":
                break
            
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        stop_event.set()
        time.sleep(1)
        p.terminate()
        cv2.destroyAllWindows()
        print("Done.")

if __name__ == "__main__":
    main()
