# private-project

## Wi-Fi FPS web server

This repo includes `wifi_fps_server.py`, a Python script that:

1. Tries to connect to Wi-Fi SSID `MV-GUEST` (Linux + `nmcli`).
2. Detects your local network IP address.
3. Starts a Flask website on that IP.
4. Shows your live camera feed and FPS in the page.

### Install

```bash
pip install flask opencv-python
```

### Run

```bash
python3 wifi_fps_server.py
```

Optional flags:

```bash
python3 wifi_fps_server.py --ssid MV-GUEST --password "your_password" --port 5000 --camera-index 0
```

Then open the printed URL, like:

`http://192.168.1.10:5000`

> If Wi-Fi auto-connect fails, connect manually and run the script again.
