import pyaudio
import subprocess
import os
import shutil
import sys
import threading
import time

# --- Configuration ---
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
OBS_IP = "127.0.0.1"
BASE_PORT = 1337

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

def stream_device_task(pyaudio_instance, device_index, device_name, port, stop_event):
    """
    Worker function to stream audio from a specific device to a UDP port.
    """
    print(f"Stream for '{device_name}' starting...")
    print(f" - udp://{OBS_IP}:{port}")

    FFMPEG_BIN = get_ffmpeg_path()
    if not FFMPEG_BIN:
        print(f"Error: FFmpeg not found for {device_name}.")
        return

    try:
        # Open the microphone stream
        stream = pyaudio_instance.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK
        )
    except Exception as e:
        print(f"Failed to open stream for {device_name}: {e}")
        return

    # FFmpeg command
    cmd = [
        FFMPEG_BIN,
        '-f', 's16le',
        '-ar', str(RATE),
        '-ac', str(CHANNELS),
        '-i', 'pipe:0',
        '-c:a', 'libmp3lame',
        '-f', 'mpegts',
        f'udp://{OBS_IP}:{port}?pkt_size=1316'
    ]

    try:
        # Silencing stderr to avoid console spam when multiple streams are running
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Failed to start FFmpeg for {device_name}: {e}")
        stream.close()
        return

    try:
        while not stop_event.is_set():
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                proc.stdin.write(data)
            except Exception as e:
                # This can happen if the device is disconnected or stream is closed
                if not stop_event.is_set():
                    print(f"Error streaming {device_name}: {e}")
                break
    except Exception:
        pass
    finally:
        print(f"Stopping stream: {device_name}")
        stream.stop_stream()
        stream.close()
        try:
            proc.stdin.close()
            proc.wait(timeout=2)
        except:
            proc.kill()

def select_audio_device(devices):
    """
    Prompts the user to select an audio device or stream all.
    Returns:
        int: device index
        str: "ALL"
    """
    print("A: Stream All Devices")
    
    while True:
        try:
            selection = input("\nEnter the Index of the microphone to use (or 'A' for all): ").strip()
            
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

def main():
    # Verify FFmpeg first
    if not get_ffmpeg_path():
        print("Error: FFmpeg not found. Please install it or add it to your PATH.")
        sys.exit(1)

    p = pyaudio.PyAudio()

    try:
        devices = list_audio_devices(p)
        if not devices:
            print("No input devices found.")
            sys.exit(1)

        selection = select_audio_device(devices)
        
        stop_event = threading.Event()
        threads = []

        if selection == "ALL":
            for i, (device_index, device_name) in enumerate(devices):
                port = BASE_PORT + i
                t = threading.Thread(
                    target=stream_device_task,
                    args=(p, device_index, device_name, port, stop_event),
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
            
            # Use BASE_PORT (1337) as requested
            t = threading.Thread(
                target=stream_device_task,
                args=(p, device_index, device_name, BASE_PORT, stop_event),
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
        # Wait a bit for threads to clean up
        time.sleep(1)
    finally:
        p.terminate()
        print("Done.")

if __name__ == "__main__":
    main()
