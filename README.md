# Android Emulator Proxy Manager

Ứng dụng **Python GUI (PySide6)** quản lý máy ảo Android và tích hợp proxy tự động.
Hỗ trợ **mỗi máy ảo một địa chỉ IP proxy riêng**.

## Tính năng

- **Liệt kê máy ảo (AVD)**: Hiển thị số lượng AVD, trạng thái (chạy/tắt), serial, proxy hiện tại.
- **Tích hợp proxy riêng cho từng máy ảo**:
  - Nhập proxy dạng `host:port:user:pass` (SOCKS5).
  - Mỗi máy ảo được gán một proxy => tự động tạo một bridge riêng (cổng riêng) => **IP thoát ra khác nhau**.
  - Khởi động / gán proxy / gỡ proxy / kiểm tra IP qua proxy.
- **Tự động hóa (Supervisor)**: Giám sát nền liên tục để đảm bảo:
  - Các bridge HTTP→SOCKS5 **luôn chạy** (tự khởi động lại nếu tắt).
  - Proxy của từng máy ảo **tự đặt lại** sau khi máy ảo tắt/bật lại (theo đúng proxy đã gán).

## Cấu trúc

```
emulator_proxy_manager.py   # Entry point + GUI (chạy chính)
core/
  emulator.py               # Liệt kê AVD, detect trạng thái, boot
  proxy.py                  # Đọc/ghi/gỡ/test proxy
  bridge.py                 # BridgeManager (1 bridge) + BridgePool (nhiều bridge, mỗi AVD 1 IP)
  autostart.py              # Supervisor tự phục hồi (thread nền)
config.json                 # Cấu hình (SDK path, proxy SOCKS5, port...)
```

## Cài đặt

```powershell
pip install PySide6 requests
```

## Chạy

```powershell
cd "D:\doithontinthietbi\New folder"
python emulator_proxy_manager.py
```

## Cấu hình (`config.json`)

| Khóa | Ý nghĩa |
|---|---|
| `sdk_path` | Đường dẫn Android SDK (chứa adb + emulator) |
| `bridge_script` | Đường dẫn script cầu nối HTTP→SOCKS5 |
| `bridge_port` | Cổng bridge mặc định (8080) |
| `port_base` | Cổng khởi đầu cho pool proxy riêng (8081, 8082...) |
| `default_proxy` | Proxy mặc định (`10.0.2.2:8080`) |
| `socks5` | Thông tin proxy SOCKS5 mặc định |
| `supervisor_interval_sec` | Chu kỳ giám sát nền (giây) |
| `boot_timeout_sec` | Thời gian chờ máy ảo boot (giây) |

## Cách dùng GUI

1. Mở ứng dụng → bảng máy ảo tự nạp danh sách AVD.
2. Chọn một máy ảo.
3. Ở ô **"Proxy SOCKS5"** nhập proxy dạng `host:port:user:pass`
   (vd `14.224.225.153:51653:yAEnTj:KMKoCt`).
4. Bấm **"Gán proxy (IP riêng)"** → một bridge riêng (cổng mới) tự tạo, proxy gán cho máy ảo đó.
5. Bấm **"Kiểm tra IP qua proxy"** để xem IP thoát ra.
6. Lặp lại với máy ảo khác và proxy khác => mỗi máy ảo có IP riêng.
7. Bật **Supervisor** để tự động hóa (proxy bền vững sau reboot).

## Ghi chú

- Mỗi proxy SOCKS5 khác nhau sẽ chiếm một cổng bridge riêng (8081, 8082...).
- Nếu 2 máy ảo dùng **cùng** một proxy, chúng dùng chung bridge (cùng IP).
- Phạm vi proxy: HTTP/HTTPS (giới hạn của cơ chế `http_proxy` Android).

