"""Unix socket IPC server and client."""
import json, logging, os, socket, threading

logger = logging.getLogger("iridia")

class IPCServer(threading.Thread):
    def __init__(self, socket_path, daemon):
        super().__init__(daemon=True, name="iridia-ipc")
        self.socket_path = socket_path
        self.daemon = daemon
        self.server = None
        self._running = False

    def run(self):
        self._running = True
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # Create the socket as 0600 from the start: binding with the normal umask
        # and chmodding afterwards leaves a moment where other users could connect
        # (it matters when XDG_RUNTIME_DIR is unset and the socket lands in /tmp).
        old_umask = os.umask(0o177)
        try:
            self.server.bind(self.socket_path)
        finally:
            os.umask(old_umask)
        self.server.listen(5)
        os.chmod(self.socket_path, 0o600)
        while self._running:
            try:
                self.server.settimeout(1.0)
                conn, _ = self.server.accept()
                handler = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                handler.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def stop(self):
        self._running = False
        if self.server:
            try:
                self.server.close()
            except OSError:
                pass
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

    def _handle_client(self, conn):
        req = None
        try:
            conn.settimeout(2.0)
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            req = json.loads(data.decode("utf-8"))
            resp = self.daemon.handle_command(req)
            conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
        except Exception as e:
            # Without this, an exception here is only ever visible to
            # whichever client happened to trigger it (via the error
            # response below) — it would never show up in the daemon's
            # own log, which is the main thing this project's
            # troubleshooting has relied on so far.
            logger.error(f"IPC command {req.get('cmd') if isinstance(req, dict) else '?'} "
                        f"failed: {type(e).__name__}: {e}")
            try:
                conn.sendall(json.dumps({"ok": False, "error": str(e)}).encode("utf-8") + b"\n")
            except OSError:
                pass
        finally:
            conn.close()

class IPCClient:
    def __init__(self, socket_path, timeout=2.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def send(self, cmd):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.socket_path)
            sock.sendall(json.dumps(cmd).encode("utf-8") + b"\n")
            data = b""
            while b"\n" not in data:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                data += chunk
            return json.loads(data.decode("utf-8"))
        except (socket.timeout, ConnectionRefusedError, FileNotFoundError):
            return {"ok": False, "error": "daemon not running"}
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"bad response: {e}"}
        except OSError as e:
            return {"ok": False, "error": f"connection error: {type(e).__name__}: {e}"}
        finally:
            sock.close()

    def is_alive(self):
        resp = self.send({"cmd": "ping"})
        return resp.get("ok", False)
