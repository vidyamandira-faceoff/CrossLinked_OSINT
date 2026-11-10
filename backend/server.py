#!/usr/bin/env python3
"""
CrossLinked Backend Server
Provides the REST API and manages LinkedIn OSINT scraping tasks.
"""

import os
import sys
import json
import csv
import time
import logging
import threading
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# Add root directory to sys.path to import crosslinked
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Import CrossLinked modules
import crosslinked
from crosslinked import utils
from crosslinked.search import CrossLinked

nformatter = crosslinked.nformatter


class SearchState:
    """Manages the state and background execution of CrossLinked scrapes."""
    def __init__(self):
        self.lock = threading.RLock()
        self.is_running = False
        self.stop_requested = False
        self.current_target = ""
        self.current_format = "{first}.{last}@company.com"
        self.outfile = "names"
        self.logs = []
        self.results = []
        self.stats = {
            "total_scraped": 0,
            "unique_formatted": 0,
            "engines_used": [],
            "last_search_time": "",
            "status": "idle"
        }
        # Pre-load existing names.csv if present in project root
        self.load_existing_csv()

    def add_log(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            entry = {"time": timestamp, "message": str(message), "level": level}
            self.logs.append(entry)
            if len(self.logs) > 500:
                self.logs.pop(0)

    def load_existing_csv(self, filename="names.csv"):
        filepath = os.path.join(ROOT_DIR, filename)
        if not os.path.isfile(filepath):
            return
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                loaded = []
                idx = 1
                for row in reader:
                    if len(row) >= 5 and row[2].strip():
                        name = row[2].strip()
                        engine = row[1].strip() if len(row) > 1 else "csv"
                        title = row[3].strip() if len(row) > 3 else "N/A"
                        url = row[4].strip() if len(row) > 4 else ""
                        raw_text = row[5].strip() if len(row) > 5 else ""
                        formatted = nformatter(self.current_format, name) if name else ""
                        loaded.append({
                            "id": idx,
                            "name": name,
                            "title": title,
                            "url": url,
                            "engine": engine,
                            "raw_text": raw_text,
                            "formatted": formatted
                        })
                        idx += 1
                with self.lock:
                    self.results = loaded
                    self.update_stats(status="loaded")
                    self.add_log(f"Loaded {len(loaded)} records from {filename}", "info")
        except Exception as e:
            self.add_log(f"Error loading {filename}: {e}", "warn")

    def update_stats(self, status=None):
        unique_emails = {r["formatted"] for r in self.results if r.get("formatted")}
        self.stats["total_scraped"] = len(self.results)
        self.stats["unique_formatted"] = len(unique_emails)
        if status:
            self.stats["status"] = status

    def reformat_all(self, new_format):
        with self.lock:
            self.current_format = new_format
            seen = set()
            for r in self.results:
                r["formatted"] = nformatter(new_format, r["name"])
                if r["formatted"]:
                    seen.add(r["formatted"])
            self.stats["unique_formatted"] = len(seen)
            self.save_txt_file()
            self.add_log(f"Applied format '{new_format}' - {len(seen)} unique formatted names", "success")

    def save_txt_file(self):
        txt_path = os.path.join(ROOT_DIR, f"{self.outfile}.txt")
        seen = []
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                for r in self.results:
                    val = r.get("formatted")
                    if val and val not in seen:
                        f.write(val + "\n")
                        seen.append(val)
        except Exception as e:
            self.add_log(f"Error saving {txt_path}: {e}", "error")

    def save_csv_file(self):
        csv_path = os.path.join(ROOT_DIR, f"{self.outfile}.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Datetime", "Search", "Name", "Title", "URL", "rawText"])
                now_str = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
                for r in self.results:
                    writer.writerow([
                        now_str,
                        r.get("engine", "web"),
                        r.get("name", ""),
                        r.get("title", ""),
                        r.get("url", ""),
                        r.get("raw_text", "")
                    ])
        except Exception as e:
            self.add_log(f"Error saving {csv_path}: {e}", "error")

    def start_search(self, target, nformat, engines, timeout, jitter, proxies, outfile="names"):
        with self.lock:
            if self.is_running:
                return False, "A search is already in progress."
            self.is_running = True
            self.stop_requested = False
            self.current_target = target
            self.current_format = nformat
            self.outfile = outfile or "names"
            self.results = []
            self.logs = []
            self.stats["engines_used"] = engines
            self.stats["status"] = "searching"
            self.stats["last_search_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        thread = threading.Thread(
            target=self._run_search_thread,
            args=(target, nformat, engines, timeout, jitter, proxies),
            daemon=True
        )
        thread.start()
        return True, "Search started."

    def stop_search(self):
        with self.lock:
            if not self.is_running:
                return False, "No active search is running."
            self.stop_requested = True
            self.add_log("Stop signal requested by user...", "warn")
        return True, "Stopping search..."

    def _run_search_thread(self, target, nformat, engines, timeout, jitter, proxies):
        self.add_log(f"Initiating OSINT scrape for '{target}' on [{', '.join(engines)}]", "info")
        self.add_log(f"Format: {nformat} | Timeout: {timeout}s | Jitter: {jitter}s", "info")

        if proxies:
            self.add_log(f"Using {len(proxies)} proxy endpoints", "info")

        collected_results = []
        result_id = 1
        seen_urls = set()

        for engine in engines:
            if self.stop_requested:
                self.add_log("Scrape halted early by user request.", "warn")
                break

            self.add_log(f"Querying {engine.upper()} search engine...", "info")
            try:
                cl = CrossLinked(
                    search_engine=engine,
                    target=target,
                    timeout=float(timeout),
                    conn_timeout=5,
                    proxies=proxies,
                    jitter=float(jitter)
                )

                search_res = cl.search()
                new_count = 0
                for item in search_res:
                    url = item.get("url", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    name = item.get("name", "")
                    formatted = nformatter(nformat, name) if name else ""

                    record = {
                        "id": result_id,
                        "name": name,
                        "title": item.get("title", "N/A"),
                        "url": url,
                        "engine": engine,
                        "raw_text": item.get("text", ""),
                        "formatted": formatted
                    }
                    collected_results.append(record)
                    result_id += 1
                    new_count += 1

                with self.lock:
                    self.results = list(collected_results)
                    self.update_stats()

                self.add_log(f"Identified {new_count} valid LinkedIn profiles from {engine.upper()}", "success")

            except Exception as e:
                self.add_log(f"Error scraping {engine}: {e}", "error")

        with self.lock:
            self.is_running = False
            status = "stopped" if self.stop_requested else "completed"
            self.update_stats(status=status)
            self.save_csv_file()
            self.save_txt_file()
            self.add_log(
                f"Completed! Total profiles: {len(self.results)}, Unique formatted accounts: {self.stats['unique_formatted']}.",
                "success"
            )


# Global Search State
state = SearchState()


class BackendHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving Frontend assets and REST API endpoints."""

    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path, content_type="application/octet-stream", as_attachment=False, filename=None):
        if not os.path.isfile(file_path):
            self.send_error(404, f"File not found: {file_path}")
            return

        with open(file_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if as_attachment:
            disp_name = filename or os.path.basename(file_path)
            self.send_header("Content-Disposition", f'attachment; filename="{disp_name}"')
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # Serve Frontend UI
        if path in ("/", "/index.html"):
            index_path = os.path.join(FRONTEND_DIR, "index.html")
            self._send_file(index_path, content_type="text/html; charset=utf-8")
            return

        # REST API: Status & Logs
        if path == "/api/status":
            with state.lock:
                self._send_json({
                    "is_running": state.is_running,
                    "target": state.current_target,
                    "format": state.current_format,
                    "stats": state.stats,
                    "logs": state.logs[-60:]
                })
            return

        # REST API: Search Results
        if path == "/api/results":
            with state.lock:
                self._send_json({
                    "records": state.results,
                    "stats": state.stats,
                    "current_format": state.current_format,
                    "target": state.current_target,
                    "outfile": state.outfile
                })
            return

        # REST API: File Downloads
        if path == "/api/download":
            file_type = query.get("type", ["txt"])[0].lower()
            if file_type == "csv":
                filepath = os.path.join(ROOT_DIR, f"{state.outfile}.csv")
                self._send_file(filepath, content_type="text/csv", as_attachment=True, filename=f"{state.outfile}.csv")
            else:
                filepath = os.path.join(ROOT_DIR, f"{state.outfile}.txt")
                self._send_file(filepath, content_type="text/plain; charset=utf-8", as_attachment=True, filename=f"{state.outfile}.txt")
            return

        # Serve static assets from frontend/ (CSS, JS, SVG, images)
        safe_path = os.path.normpath(os.path.join(FRONTEND_DIR, path.lstrip("/")))
        if safe_path.startswith(FRONTEND_DIR) and os.path.isfile(safe_path):
            ct = "application/octet-stream"
            if safe_path.endswith(".css"): ct = "text/css"
            elif safe_path.endswith(".js"): ct = "application/javascript"
            elif safe_path.endswith(".svg"): ct = "image/svg+xml"
            elif safe_path.endswith(".png"): ct = "image/png"
            elif safe_path.endswith(".ico"): ct = "image/x-icon"
            self._send_file(safe_path, content_type=ct)
            return

        self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception as e:
            self._send_json({"success": False, "error": f"Invalid JSON payload: {e}"}, 400)
            return

        # API: Start search
        if path == "/api/search":
            target = payload.get("target", "").strip()
            nformat = payload.get("format", "{first}.{last}@company.com").strip()
            engines = payload.get("engines", ["google", "bing"])
            timeout = float(payload.get("timeout", 15))
            jitter = float(payload.get("jitter", 1))
            outfile = payload.get("outfile", "names").strip() or "names"
            proxies_input = payload.get("proxies", [])

            if not target:
                self._send_json({"success": False, "error": "Company Name is required."}, 400)
                return

            if not nformat:
                self._send_json({"success": False, "error": "Naming format pattern is required."}, 400)
                return

            if not engines:
                engines = ["google", "bing"]

            proxies = []
            if isinstance(proxies_input, str):
                proxies = [p.strip() for p in proxies_input.splitlines() if p.strip()]
            elif isinstance(proxies_input, list):
                proxies = [str(p).strip() for p in proxies_input if str(p).strip()]

            ok, msg = state.start_search(
                target=target,
                nformat=nformat,
                engines=engines,
                timeout=timeout,
                jitter=jitter,
                proxies=proxies,
                outfile=outfile
            )
            self._send_json({"success": ok, "message": msg})
            return

        # API: Stop search
        if path == "/api/stop":
            ok, msg = state.stop_search()
            self._send_json({"success": ok, "message": msg})
            return

        # API: Re-format loaded records
        if path == "/api/reformat":
            new_format = payload.get("format", "").strip()
            if not new_format:
                self._send_json({"success": False, "error": "New format string is required."}, 400)
                return
            state.reformat_all(new_format)
            self._send_json({
                "success": True,
                "message": f"All names reformatted with: {new_format}",
                "records": state.results,
                "stats": state.stats
            })
            return

        # API: Clear state
        if path == "/api/clear":
            with state.lock:
                state.results = []
                state.logs = []
                state.update_stats(status="idle")
                state.add_log("Dashboard cleared.", "info")
            self._send_json({"success": True, "message": "Cleared all results and logs."})
            return

        # API: Load CSV file
        if path == "/api/load_csv":
            filename = payload.get("filename", "names.csv").strip() or "names.csv"
            state.load_existing_csv(filename)
            self._send_json({
                "success": True,
                "message": f"Loaded {filename}",
                "records": state.results,
                "stats": state.stats
            })
            return

        self.send_error(404, "Endpoint Not Found")


def run_backend(port=8000, host="0.0.0.0"):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, BackendHandler)
    print("\n" + "="*60)
    print("🚀 CrossLinked Backend & Frontend Connected!")
    print(f"   Frontend Directory: {FRONTEND_DIR}")
    print(f"   Backend Directory:  {BACKEND_DIR}")
    print(f"   Dashboard URL:      http://localhost:{port}")
    print(f"   Network URL:        http://127.0.0.1:{port}")
    print("="*60 + "\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping backend server...")
        httpd.shutdown()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
    run_backend(port=port)

