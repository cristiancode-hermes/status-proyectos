#!/usr/bin/env python3
"""Port forwarder that runs INSIDE the container.
Binds to all required ports and forwards to the container's own services.
This works alongside Docker's existing port mappings.
"""
import socket, threading, os, time, signal, sys

SERVICES = {
    32768: 8787,   # WebUI (alias)
    32770: 3333,   # Dashboard RT
    32771: 4860,   # Dashboard
    32772: 5200,   # DevSnips
}

LOG = "/opt/data/logs/port-forwarder.log"

def log(msg):
    t = time.strftime("%H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[forwarder {t}] {msg}\n")

def forward(src, dst, name):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except (ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle_client(client, target_port, listen_port):
    try:
        backend = socket.create_connection(("127.0.0.1", target_port), timeout=5)
        threading.Thread(target=forward, args=(client, backend, f"c{listen_port}"), daemon=True).start()
        threading.Thread(target=forward, args=(backend, client, f"b{listen_port}"), daemon=True).start()
    except Exception as e:
        log(f"  :{listen_port} → :{target_port} FAILED: {e}")
        try: client.close()
        except: pass

def start_listener(listen_port, target_port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", listen_port))
        sock.listen(128)
        log(f"✅ :{listen_port} → 127.0.0.1:{target_port}")
        while True:
            try:
                client, addr = sock.accept()
                threading.Thread(target=handle_client, args=(client, target_port, listen_port), daemon=True).start()
            except: break
    except Exception as e:
        log(f"❌ :{listen_port} bind failed: {e}")
    finally:
        sock.close()

def main():
    log("="*40)
    log("Starting port forwarder")
    
    threads = []
    for listen_port, target_port in SERVICES.items():
        t = threading.Thread(target=start_listener, args=(listen_port, target_port), daemon=True)
        t.start()
        threads.append(t)
        time.sleep(0.1)

    log(f"Forwarder running with {len(SERVICES)} mappings")
    
    # Keep alive
    signal.pause()

if __name__ == "__main__":
    main()
