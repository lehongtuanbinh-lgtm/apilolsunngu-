import asyncio
import websockets
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, jsonify
from flask_cors import CORS
import os
import signal
import sys
import socket
import requests
import re

app = Flask(__name__)
CORS(app)

# Render cấp PORT qua biến môi trường, mặc định là 10000 nếu chạy local
PORT = int(os.environ.get('PORT', 10000))

# Global variables
current_result = {
    "phien": None,
    "xuc_xac_1": None,
    "xuc_xac_2": None,
    "xuc_xac_3": None,
    "tong": None,
    "ket_qua": "",
    "thoi_gian": ""
}

current_session_id = None
ws_connection = None
websocket_task = None
reconnect_delay = 5.0  # Tăng lên 5s để tránh spam khi Render tự restart
start_time = time.time()

def get_vietnam_time():
    """Hàm lấy thời gian Việt Nam (UTC+7)"""
    utc7_time = datetime.utcnow() + timedelta(hours=7)
    return utc7_time.strftime("%d-%m-%Y %H:%M:%S") + " UTC+7"

def parse_token_data(token_text):
    """Parse token data từ file token.txt"""
    try:
        info_match = re.search(r'"info"\x07([^"]+?)"?', token_text)
        if info_match:
            info_str = info_match.group(1)
            info_str = info_str.replace('\x04', '').replace('\x07', '').replace('\x05', '').replace('\x06', '')
            info_data = json.loads(info_str)
            return info_data
        
        json_match = re.search(r'\{[^{}]*"ipAddress"[^{}]*\}', token_text)
        if json_match:
            return json.loads(json_match.group())
        
        return None
    except Exception as e:
        print(f"[❌] Lỗi parse token: {e}")
        return None

def load_token():
    """Load token từ file token.txt"""
    try:
        if not os.path.exists('token.txt'):
            print("[⚠️] Không tìm thấy file token.txt trên server")
            return None
            
        with open('token.txt', 'r', encoding='utf-8') as f:
            token_data = f.read().strip()
        
        if not token_data:
            print("[❌] File token.txt trống")
            return None
        
        parsed_data = parse_token_data(token_data)
        if parsed_data:
            print("[✅] Đã load token thành công")
            return parsed_data
        else:
            print("[❌] Không thể parse token")
            return None
    except Exception as e:
        print(f"[❌] Lỗi đọc token.txt: {e}")
        return None

# Khởi tạo cấu hình ban đầu
TOKEN_DATA = load_token()

if TOKEN_DATA:
    WEBSOCKET_URL = f"wss://websocket.azhkthg1.net/websocket?token={TOKEN_DATA.get('wsToken', '')}"
    WS_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Origin": "https://play.sun.pw"
    }
    initial_messages = [
        [
            1, "MiniGame", TOKEN_DATA.get('username', 'GM_quapotjz'), "quapit",
            {
                "signature": "05915B436159B8F4E4DFF537639BD014D54EBEFA18CF62A8EB205B4074010AD72AEA9A780D5A8A4E1BD59BBBAFE03902C594B5DA56FD60D099F1FDDCCD48385FCC2760B5B0B4B8E75D39B8E40DF8CB7C01EA58DBEDA32805927473AB71FA9B798B0C2EDC445C3E36E47EF0AAFAD45601D99AAD1EC642FD2B63573A0401D6EC69",
                "expireIn": TOKEN_DATA.get('timestamp', 1774138177205),
                "wsToken": TOKEN_DATA.get('wsToken', ''),
                "accessToken": "7e9a9ecbff1b4a6393b48346f6d8b709",
                "message": "Thành công",
                "refreshToken": TOKEN_DATA.get('refreshToken', ''),
                "info": TOKEN_DATA
            }
        ],
        [6, "MiniGame", "taixiuPlugin", {"cmd": 1005}],
        [6, "MiniGame", "lobbyPlugin", {"cmd": 10001}]
    ]
else:
    # Fallback khi chưa có file token (Tránh sập app khi deploy lần đầu)
    WEBSOCKET_URL = "wss://websocket.azhkthg1.net/websocket?token=dummy_token"
    WS_HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://play.sun.pw"}
    initial_messages = []

def get_network_info():
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        return {'localIP': local_ip}
    except Exception:
        return {'localIP': '127.0.0.1'}

def handle_error(context, error):
    error_msg = f"Lỗi - {context}: {str(error)}"
    print(f"[❌] {error_msg}")
    return error_msg

async def connect_websocket():
    global ws_connection, current_session_id, current_result
    
    while True:
        try:
            if not TOKEN_DATA:
                print("[⚠️] Đang chạy không có Token hợp lệ. Vui lòng cập nhật token.txt!")
                await asyncio.sleep(10)
                continue
                
            print("[🔄] Đang kết nối WebSocket...")
            ws_connection = await websockets.connect(
                WEBSOCKET_URL,
                extra_headers=WS_HEADERS,
                ping_interval=15,
                ping_timeout=10
            )
            print("[✅] WebSocket connected thành công")
            
            for i, msg in enumerate(initial_messages):
                await asyncio.sleep(i * 0.6)
                await ws_connection.send(json.dumps(msg))
            
            async for message in ws_connection:
                try:
                    data = json.loads(message)
                    if not isinstance(data, list) or len(data) < 2:
                        continue
                    
                    if isinstance(data[1], dict):
                        cmd = data[1].get('cmd')
                        sid = data[1].get('sid')
                        d1 = data[1].get('d1')
                        d2 = data[1].get('d2')
                        d3 = data[1].get('d3')
                        gBB = data[1].get('gBB')
                        
                        if cmd == 1008 and sid:
                            current_session_id = sid
                            print(f"[🎮] Phiên mới: {sid}")
                        
                        if cmd == 1003 and gBB:
                            if d1 is None or d2 is None or d3 is None:
                                continue
                            
                            total = d1 + d2 + d3
                            result = "Tài" if total > 10 else "Xỉu"
                            
                            current_result = {
                                "phien": current_session_id,
                                "xuc_xac_1": d1,
                                "xuc_xac_2": d2,
                                "xuc_xac_3": d3,
                                "tong": total,
                                "ket_qua": result,
                                "thoi_gian": get_vietnam_time()
                            }
                            print(f"[🎲] Phiên {current_result['phien']}: {d1}-{d2}-{d3} = {total} ({result})")
                            current_session_id = None
                            
                except json.JSONDecodeError as e:
                    handle_error("Parse JSON", e)
                except Exception as e:
                    handle_error("Xử lý message", e)
                    
        except websockets.exceptions.ConnectionClosed as e:
            handle_error("WebSocket đóng", e)
            await asyncio.sleep(reconnect_delay)
        except Exception as e:
            handle_error("Kết nối WebSocket", e)
            await asyncio.sleep(reconnect_delay)

# Flask routes
@app.route('/api/tx', methods=['GET'])
def get_tx_result():
    return jsonify(current_result)

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "status": "online",
        "project": "by hoàng",
        "thoi_gian": get_vietnam_time(),
        "current_user": TOKEN_DATA.get('username') if TOKEN_DATA else "Chưa cấu hình Token"
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint không tồn tại. Dùng /api/tx"}), 404

def run_flask():
    try:
        # Tắt debug và reloader để tránh lỗi xung đột thread trên Render
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        handle_error("Flask server", e)

async def main():
    network_info = get_network_info()
    print(f"[📡] Server khởi chạy tại Port: {PORT}")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    await connect_websocket()

def signal_handler(sig, frame):
    print("\n[👋] Đang tắt server...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[👋] Server dừng bởi user")
    except Exception as e:
        handle_error("Main", e)