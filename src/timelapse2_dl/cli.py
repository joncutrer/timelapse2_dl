#!/usr/bin/env python3
"""
Download timelapse archives from an Axis camera running timelapse2 ACAP using HTTP Digest Auth.

Example:
  python download_timelapse.py --user root --pass '******' \
      --host 192.168.0.90 --outdir downloads
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError
from typing import List, Optional


def format_bytes(bytes_val: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} TB"


def print_progress_bar(downloaded: int, total: int, start_time: float, bar_length: int = 50) -> None:
    """Print a progress bar for download status."""
    if total > 0:
        percent = (downloaded / total) * 100
        filled_length = int(bar_length * downloaded // total)
        bar = '=' * filled_length + '-' * (bar_length - filled_length)

        elapsed = time.time() - start_time
        if elapsed > 0 and downloaded > 0:
            speed = downloaded / elapsed
            eta = (total - downloaded) / speed if speed > 0 else 0
            eta_str = f"{int(eta)}s"
            speed_str = format_bytes(speed) + "/s"
        else:
            eta_str = "?"
            speed_str = "?"

        sys.stdout.write(f'\r      [{bar}] {percent:.1f}% {format_bytes(downloaded)}/{format_bytes(total)} {speed_str} ETA: {eta_str}')
        sys.stdout.flush()
    else:
        # Unknown total size
        sys.stdout.write(f'\r      Downloaded: {format_bytes(downloaded)}')
        sys.stdout.flush()


def fetch_timelapse_archives(host: str, username: str, password: str, timeout: int = 60) -> List[str]:
    """
    Fetch the list of timelapse archive URLs from the camera API.

    Args:
        host: Camera hostname or IP address
        username: Username for digest auth
        password: Password for digest auth
        timeout: HTTP timeout in seconds

    Returns:
        List of archive file URLs
    """
    # Build the archives API endpoint
    api_url = f"http://{host}/local/timelapseme/archives?_={int(time.time() * 1000)}"

    # Set up HTTP Digest authentication
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(realm=None, uri=api_url, user=username, passwd=password)
    auth_handler = urllib.request.HTTPDigestAuthHandler(pm)
    opener = urllib.request.build_opener(auth_handler)

    try:
        req = urllib.request.Request(api_url, method="GET")
        with opener.open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                raise HTTPError(api_url, status, f"HTTP {status}", resp.headers, None)

            # Read and parse JSON response
            data = json.loads(resp.read().decode('utf-8'))

            # Parse the JSON to extract file URLs
            # Response format: list of objects with 'id' and 'filename' fields
            urls = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and 'id' in item and 'filename' in item:
                        archive_id = item['id']
                        filename = item['filename']
                        # Construct download URL: archives?export={id}&file={filename}
                        download_url = f"http://{host}/local/timelapseme/archives?export={archive_id}&file={urllib.parse.quote(filename)}"
                        urls.append(download_url)

            return urls

    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse JSON response from {api_url}: {e}", file=sys.stderr)
        raise
    except (HTTPError, URLError) as e:
        print(f"ERROR: Failed to fetch archives from {api_url}: {e}", file=sys.stderr)
        raise


def filename_from_url(url: str) -> str:
    """Prefer the 'file' query parameter; else fall back to the URL path basename."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "file" in qs and qs["file"]:
        # take first value
        return os.path.basename(qs["file"][0])
    # fallback: last path segment
    return os.path.basename(parsed.path) or "download.bin"


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_remote_file_size(url: str, username: str, password: str, timeout: int = 60) -> Optional[int]:
    """
    Get the remote file size using HEAD request with HTTP Digest authentication.

    Returns:
        File size in bytes, or None if Content-Length header is not available
    """
    try:
        pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        pm.add_password(realm=None, uri=url, user=username, passwd=password)
        auth_handler = urllib.request.HTTPDigestAuthHandler(pm)
        opener = urllib.request.build_opener(auth_handler)

        req = urllib.request.Request(url, method="HEAD")
        with opener.open(req, timeout=timeout) as resp:
            content_length = resp.headers.get("Content-Length")
            if content_length:
                return int(content_length)
    except (HTTPError, URLError, ValueError):
        pass
    return None


def download_with_digest(url: str, username: str, password: str, out_path: str, timeout: int = 60, rate_limit_mbps: Optional[float] = None, max_retries: int = 3, retry_delay: int = 5, show_progress: bool = True) -> None:
    """
    Download a URL using HTTP Digest authentication and stream to out_path.

    Args:
        url: URL to download
        username: Username for digest auth
        password: Password for digest auth
        out_path: Path to save the file
        timeout: HTTP timeout in seconds
        rate_limit_mbps: Optional rate limit in Mbps (megabits per second)
        max_retries: Maximum number of retry attempts for failed downloads
        retry_delay: Delay in seconds between retry attempts
        show_progress: Show progress bar during download
    """
    last_error = None
    tmp_path = out_path + ".part"

    for attempt in range(max_retries):
        try:
            # Clean up any existing partial file from previous failed attempts
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            # Build a password manager / auth handler for digest auth
            pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            # Use the full URL as the "top-level URL" for credential matching
            pm.add_password(realm=None, uri=url, user=username, passwd=password)

            auth_handler = urllib.request.HTTPDigestAuthHandler(pm)

            # Build an opener for this request (keeps it simple per-call)
            opener = urllib.request.build_opener(auth_handler)

            req = urllib.request.Request(url, method="GET")

            with opener.open(req, timeout=timeout) as resp:
                # Basic success check
                status = getattr(resp, "status", 200)
                if status >= 400:
                    raise HTTPError(url, status, f"HTTP {status}", resp.headers, None)

                # Get total file size from Content-Length header
                content_length = resp.headers.get("Content-Length")
                total_size = int(content_length) if content_length else 0

                # Stream to disk
                # Use a temp file then atomic rename to avoid partial files on interruption
                # Rate limiting setup
                chunk_size = 1024 * 1024  # 1 MiB
                if rate_limit_mbps:
                    # Convert Mbps to bytes per second
                    max_bytes_per_sec = (rate_limit_mbps * 1_000_000) / 8

                with open(tmp_path, "wb") as f:
                    start_time = time.time()
                    total_bytes = 0

                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        total_bytes += len(chunk)

                        # Show progress bar
                        if show_progress:
                            print_progress_bar(total_bytes, total_size, start_time)

                        # Apply rate limiting
                        if rate_limit_mbps:
                            elapsed = time.time() - start_time
                            expected_time = total_bytes / max_bytes_per_sec

                            if elapsed < expected_time:
                                time.sleep(expected_time - elapsed)

                # Clear progress bar and print newline
                if show_progress:
                    sys.stdout.write('\n')
                    sys.stdout.flush()

                # Atomic rename: only happens if download completed successfully
                os.replace(tmp_path, out_path)
                return  # Success, exit the function

        except (HTTPError, URLError) as e:
            last_error = e
            # Clean up partial file on error
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass  # Ignore cleanup errors

            # Check if it's a retryable error
            is_retryable = False
            if isinstance(e, HTTPError):
                # Retry on 5xx server errors
                is_retryable = 500 <= e.code < 600
            elif isinstance(e, URLError):
                # Retry on network errors
                is_retryable = True

            if is_retryable and attempt < max_retries - 1:
                print(f"      Attempt {attempt + 1}/{max_retries} failed: {e}", file=sys.stderr)
                print(f"      Retrying in {retry_delay} seconds...", file=sys.stderr)
                time.sleep(retry_delay)
            else:
                # Last attempt or non-retryable error
                raise
        except Exception:
            # Clean up partial file on any exception
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass  # Ignore cleanup errors
            # Non-retryable exceptions, re-raise immediately
            raise

    # If we exhausted all retries
    if last_error:
        raise last_error


def main() -> int:
    # Set up signal handler for graceful exit on Ctrl+C
    interrupted = False

    def signal_handler(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            print("\n\nInterrupted by user (Ctrl+C). Cleaning up and exiting gracefully...", file=sys.stderr)
            print("Press Ctrl+C again to force exit.", file=sys.stderr)
        else:
            print("\nForce exit!", file=sys.stderr)
            sys.exit(130)

    signal.signal(signal.SIGINT, signal_handler)

    ap = argparse.ArgumentParser(description="Download timelapse files from Axis camera via HTTP Digest Auth.")
    ap.add_argument("--host", default="192.168.0.90", help="Camera hostname or IP address (default: 192.168.0.90)")
    ap.add_argument("--outdir", default=".", help="Directory to save downloaded files (default: current directory)")
    ap.add_argument("--user", required=True, help="Username for digest auth (e.g., root)")
    ap.add_argument("--pass", dest="password", required=True, help="Password for digest auth")
    ap.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds (default: 60)")
    ap.add_argument("--rate-limit", type=float, default=90.0, help="Download rate limit in Mbps (default: 90)")
    ap.add_argument("--max-retries", type=int, default=3, help="Maximum retry attempts for failed downloads (default: 3)")
    ap.add_argument("--retry-delay", type=int, default=5, help="Delay in seconds between retries (default: 5)")
    ap.add_argument("--check-size", action="store_true", help="Check remote file size before skipping existing files (default: false)")
    ap.add_argument("--no-progress", action="store_true", help="Disable progress bar display (default: show progress)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing files (default: skip existing)")
    args = ap.parse_args()

    ensure_dir(args.outdir)

    # Fetch timelapse archives from camera API
    print(f"Fetching timelapse archives from {args.host}...")
    try:
        urls = fetch_timelapse_archives(args.host, args.user, args.password, timeout=args.timeout)
    except Exception as e:
        print(f"ERROR: Failed to fetch archives: {e}", file=sys.stderr)
        return 2

    if not urls:
        print("No timelapse archives found on camera.")
        return 0

    print(f"Found {len(urls)} timelapse archive(s) to download.\n")

    ok = 0
    skipped = 0
    failed = 0

    for url in urls:
        # Check if interrupted by Ctrl+C
        if interrupted:
            print("\nStopping download process...", file=sys.stderr)
            break

        try:
            fname = filename_from_url(url)
            out_path = os.path.join(args.outdir, fname)

            if os.path.exists(out_path) and not args.overwrite:
                # Check file size if requested
                if args.check_size:
                    local_size = os.path.getsize(out_path)
                    remote_size = get_remote_file_size(url, args.user, args.password, timeout=args.timeout)

                    if remote_size is not None:
                        if local_size == remote_size:
                            print(f"SKIP  {fname} (already exists, size matches: {local_size} bytes)")
                            skipped += 1
                            continue
                        else:
                            print(f"INFO  {fname} exists but size mismatch (local: {local_size}, remote: {remote_size}), re-downloading")
                    else:
                        # Cannot determine remote size, skip anyway
                        print(f"SKIP  {fname} (already exists, cannot verify size)")
                        skipped += 1
                        continue
                else:
                    # No size check, skip based on existence only
                    print(f"SKIP  {fname} (already exists)")
                    skipped += 1
                    continue

            print(f"GET   {url}")
            print(f"SAVE  {out_path}")
            download_with_digest(
                url,
                args.user,
                args.password,
                out_path,
                timeout=args.timeout,
                rate_limit_mbps=args.rate_limit,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
                show_progress=not args.no_progress
            )
            ok += 1

        except (HTTPError, URLError) as e:
            print(f"FAIL  {url}\n      {e}", file=sys.stderr)
            failed += 1
        except Exception as e:
            print(f"FAIL  {url}\n      {type(e).__name__}: {e}", file=sys.stderr)
            failed += 1

    status_msg = "Interrupted" if interrupted else "Done"
    print(f"\n{status_msg}. downloaded={ok} skipped={skipped} failed={failed}")

    if interrupted:
        return 130  # Standard exit code for SIGINT
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
