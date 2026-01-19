import pyaudio
import cv2
import subprocess
import os
import sys
import threading
import time
import argparse
import ctypes
from ctypes import wintypes

# --- Configuration ---
OBS_IP = "127.0.0.1"
TARGET_PORT = 1337
AUDIO_CHUNK = 4096
AUDIO_FORMAT = pyaudio.paInt16
AUDIO_CHANNELS = 1
AUDIO_RATE = 44100
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30

# --- Named Pipe Constants ---
PIPE_ACCESS_OUTBOUND = 0x00000002
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
INVALID_HANDLE_VALUE = -1

class NamedPipe:
    """Helper class to create and write to a Windows Named Pipe."""
    def __init__(self, name):
        self.name = f"\\\\.\\pipe\\{name}"
        self.handle = None
        self._create_pipe()

    def _create_pipe(self):
        self.handle = ctypes.windll.kernel32.CreateNamedPipeW(
            self.name,
            PIPE_ACCESS_OUTBOUND,
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
            PIPE_UNLIMITED_INSTANCES,
            65536, # Out buffer size
            65536, # In buffer size
            0,
            None
        )
        if self.handle == INVALID_HANDLE_VALUE:
            raise Exception(f"Failed to create named pipe: {self.name} (Error: {ctypes.get_last_error()})")

    def connect(self):
        """Wait for a client (FFmpeg) to connect."""
        print(f"Waiting for connection on {self.name}...")
        connected = ctypes.windll.kernel32.ConnectNamedPipe(self.handle, None)
        if not connected and ctypes.get_last_error() != 535: # ERROR_PIPE_CONNECTED
             # If connect fails and it's not because it's already connected...
             pass
        print(f"Connected: {self.name}")

    def write(self, data):
        """Write bytes to the pipe."""
        if not self.handle:
            return
        
        written = wintypes.DWORD()
        success = ctypes.windll.kernel32.WriteFile(
            self.handle,
            data,
            len(data),
            ctypes.byref(written),
            None
        )
        if not success:
            raise IOError(f"Failed to write to pipe: {self.name}")

    def close(self):
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None

def get_ffmpeg_path():
    if shutil_which := __import__('shutil').which("ffmpeg"):
        return "ffmpeg"
    
    common_paths = [
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-7.0.1-full_build\bin\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"),
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None

def list_audio_devices(p):
    info = p.get_host_api_info_by_type(pyaudio.paMME)
    if not info:
        print("MME Host API not found")
        return []
    
    numdevices = info.get('deviceCount')
    devices = []
    print("\nAvailable Audio Input Devices (MME):")
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(info['index'], i).get('maxInputChannels')) > 0:
            dev_name = p.get_device_info_by_host_api_device_index(info['index'], i).get('name')
            if "Microsoft Sound Mapper" not in dev_name:
                print(f"Index {i}: {dev_name}")
                devices.append((i, dev_name))
    return devices

def list_video_devices():
    devices = []
    print("\nScanning Video Devices...")
    for i in range(5): # Scan first 5
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                print(f"Index {i}: Camera {i}")
                devices.append((i, f"Camera {i}"))
            cap.release()
    return devices

def audio_thread_func(p, device_index, pipe, stop_event):
    stream = p.open(format=AUDIO_FORMAT,
                    channels=AUDIO_CHANNELS,
                    rate=AUDIO_RATE,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=AUDIO_CHUNK)
    try:
        while not stop_event.is_set():
            data = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
            try:
                pipe.write(data)
            except IOError:
                break
    except Exception as e:
        print(f"Audio thread error: {e}")
    finally:
        stream.stop_stream()
        stream.close()
        pipe.close()
        print("Audio thread finished.")

def video_thread_func(device_index, pipe, stop_event):
    cap = cv2.VideoCapture(device_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, VIDEO_FPS)
    
    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            try:
                pipe.write(frame.tobytes())
            except IOError:
                break
    except Exception as e:
        print(f"Video thread error: {e}")
    finally:
        cap.release()
        pipe.close()
        print("Video thread finished.")

def main():
    parser = argparse.ArgumentParser(description="PyAvCast - Combined Audio/Video Streamer")
    parser.add_argument("--ip", default=OBS_IP, help="Target IP")
    parser.add_argument("--port", type=int, default=TARGET_PORT, help="Target Port")
    args = parser.parse_args()

    ffmpeg_bin = get_ffmpeg_path()
    if not ffmpeg_bin:
        print("FFmpeg not found.")
        return

    p = pyaudio.PyAudio()
    
    try:
        # Select Audio
        audio_devs = list_audio_devices(p)
        if not audio_devs:
            print("No audio devices.")
            return
        a_idx = int(input("Select Audio Device Index: "))
        
        # Select Video
        video_devs = list_video_devices()
        if not video_devs:
            print("No video devices.")
            return
        v_idx = int(input("Select Video Device Index: "))

        # Create Named Pipes
        pipe_video_name = "pyavcast_video"
        pipe_audio_name = "pyavcast_audio"
        
        pipe_video = NamedPipe(pipe_video_name)
        pipe_audio = NamedPipe(pipe_audio_name)

        # Threading Events
        stop_event = threading.Event()

        # Start Capture Threads
        t_audio = threading.Thread(target=audio_thread_func, args=(p, a_idx, pipe_audio, stop_event))
        t_video = threading.Thread(target=video_thread_func, args=(v_idx, pipe_video, stop_event))
        
        t_audio.start()
        t_video.start()
        
        # Wait for pipes to be ready (FFmpeg will connect to them)
        # Note: In Windows, CreateNamedPipe waits for client connection if we call ConnectNamedPipe.
        # However, to avoid blocking the main thread from launching FFmpeg, we should launch FFmpeg *first* 
        # or launch connection waiting in threads? 
        # Actually, standard practice: Create pipes, Launch FFmpeg (it opens pipes), then we write.
        # But ConnectNamedPipe blocks until client connects.
        
        # Let's launch connection waiters in threads or just rely on the fact that we can start writing? 
        # No, we must accept the connection.
        
        def connect_pipe(pipe):
            pipe.connect()
            
        t_conn_v = threading.Thread(target=connect_pipe, args=(pipe_video,))
        t_conn_a = threading.Thread(target=connect_pipe, args=(pipe_audio,))
        t_conn_v.start()
        t_conn_a.start()

        # Construct FFmpeg Command
        cmd = [
            ffmpeg_bin,
            '-y',
            # Video Input (Pipe)
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-s', f'{VIDEO_WIDTH}x{VIDEO_HEIGHT}',
            '-r', str(VIDEO_FPS),
            '-i', f'\\\\.\\pipe\\{pipe_video_name}',
            # Audio Input (Pipe)
            '-f', 's16le',
            '-ac', str(AUDIO_CHANNELS),
            '-ar', str(AUDIO_RATE),
            '-i', f'\\\\.\\pipe\\{pipe_audio_name}',
            # Encoding & Output
            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
            '-c:a', 'aac', '-b:a', '128k',
            '-f', 'mpegts',
            f'udp://{args.ip}:{args.port}?pkt_size=1316'
        ]
        
        print("Starting FFmpeg...")
        # print(" ".join(cmd))
        proc = subprocess.Popen(cmd)

        t_conn_v.join()
        t_conn_a.join()
        print("Pipes connected. Streaming...")

        try:
            while proc.poll() is None:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping...")
            stop_event.set()
            proc.terminate()
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        stop_event.set()
        p.terminate()
        cv2.destroyAllWindows()
        print("Exited.")

if __name__ == "__main__":
    main()
