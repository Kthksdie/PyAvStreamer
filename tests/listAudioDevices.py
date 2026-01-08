import pyaudio

p = pyaudio.PyAudio()

print("Available Audio Input Devices:")

# Find the MME Host API index
mme_index = -1
for i in range(p.get_host_api_count()):
    info = p.get_host_api_info_by_index(i)
    if info.get('name') == 'MME':
        mme_index = i
        break

if mme_index == -1:
    print("Error: MME Host API not found.")
else:
    for i in range(p.get_device_count()):
        try:
            device_info = p.get_device_info_by_index(i)
            # Filter for Input devices on MME API
            if (device_info.get('maxInputChannels') > 0 and 
                device_info.get('hostApi') == mme_index):
                
                name = device_info.get('name')
                # Exclude the mapper
                if name != "Microsoft Sound Mapper - Input":
                    print(f"Index {i}: {name}")
                    
        except Exception as e:
            print(f"Error reading device {i}: {e}")

p.terminate()