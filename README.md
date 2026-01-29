# Axis Timelapse2 Downloader Tool

A robust Python command-line utility for downloading timelapse archives from an Axis IP camera running the excellent [Timelapse2](https://github.com/pandosme/Timelapse2) ACAP application by [Fred Juhlin](http://juhlin.me/).

I created this application because I was faced with downloading the daily timelapse video files from a 9 month construction project and did not feel like clicking in the browser to download that many files.

## Features

- **Automatic Archive Discovery**: Fetches the list of timelapse archives directly from the camera API
- **HTTP Digest Authentication**: Secure authentication with username/password
- **Rate Limiting**: Configurable download speed limit (default: 90 Mbps)
- **Automatic Retries**: Retry failed downloads on server errors (5xx) and network issues
- **Progress Bar**: Real-time download progress with speed and ETA
- **Atomic Downloads**: Uses temporary files to prevent partial downloads
- **File Size Verification**: Optional size checking to detect incomplete downloads
- **Resumable**: Skip already downloaded files
- **Graceful Interruption**: Ctrl+C support with clean shutdown
- **Zero Dependencies**: Uses only the Python standard library

## Requirements

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Installation

### Using uv (recommended)

```bash
# Install from the project directory
uv tool install .

# Or install in a project as a dependency
uv add timelapse2-dl
```

### Using pip

```bash
pip install .
```

### Development install

```bash
# Clone the repository
git clone <repo-url>
cd timelapse2_dl

# Create venv and install in editable mode
uv sync
```

## Usage

### Basic Usage

```bash
timelapse2-dl --user USERNAME --pass PASSWORD --host 192.168.0.90
```

The tool will automatically fetch the list of available timelapse archives from the camera and download them.

### Command-Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--host` | string | `192.168.0.90` | Camera hostname or IP address |
| `--outdir` | string | `.` | Directory to save downloaded files |
| `--user` | string | *required* | Username for HTTP Digest authentication |
| `--pass` | string | *required* | Password for HTTP Digest authentication |
| `--timeout` | int | `60` | HTTP timeout in seconds |
| `--rate-limit` | float | `90.0` | Download rate limit in Mbps |
| `--max-retries` | int | `3` | Maximum retry attempts for failed downloads |
| `--retry-delay` | int | `5` | Delay in seconds between retry attempts |
| `--check-size` | flag | `false` | Check remote file size before skipping existing files |
| `--no-progress` | flag | `false` | Disable progress bar display |
| `--overwrite` | flag | `false` | Overwrite existing files |

### Examples

#### Download with default settings (from default IP)
```bash
timelapse2-dl --user root --pass 'mypassword'
```

#### Download from specific camera IP
```bash
timelapse2-dl \
    --user root \
    --pass 'mypassword' \
    --host 192.168.1.100
```

#### Download to specific directory with rate limit
```bash
timelapse2-dl \
    --user root \
    --pass 'mypassword' \
    --host 192.168.0.90 \
    --outdir downloads \
    --rate-limit 50
```

#### Enable size checking and increase retries
```bash
timelapse2-dl \
    --user root \
    --pass 'mypassword' \
    --host 192.168.0.90 \
    --check-size \
    --max-retries 5 \
    --retry-delay 10
```

#### Disable progress bar (for logging/automation)
```bash
timelapse2-dl \
    --user root \
    --pass 'mypassword' \
    --host 192.168.0.90 \
    --no-progress
```

#### Force re-download all files
```bash
timelapse2-dl \
    --user root \
    --pass 'mypassword' \
    --host 192.168.0.90 \
    --overwrite
```

## How It Works

1. **Archive Discovery**: The tool connects to the camera's API endpoint at `http://{host}/local/timelapseme/archives` and retrieves a JSON list of available timelapse archives.

2. **URL Construction**: For each archive in the JSON response, the tool constructs a download URL using the archive's ID and filename:
   ```
   http://{host}/local/timelapseme/archives?export={id}&file={filename}
   ```

3. **Download**: Each file is downloaded with HTTP Digest authentication, progress tracking, and automatic retry on failure.

## Output Filename Extraction

The tool intelligently extracts filenames from URLs:
1. Uses the `file` query parameter if present (e.g., `?file=archive.zip` → `archive.zip`)
2. Falls back to the last path segment (e.g., `/path/to/file.zip` → `file.zip`)
3. Uses `download.bin` as a last resort

## Features in Detail

### Rate Limiting

Controls download speed to avoid overwhelming the network or server:
- Specified in Mbps (megabits per second)
- Throttles downloads at the chunk level
- Default: 90 Mbps

```bash
# Limit to 50 Mbps
timelapse2-dl --user root --pass 'pwd' --host 192.168.0.90 --rate-limit 50

# No rate limit (set very high value)
timelapse2-dl --user root --pass 'pwd' --host 192.168.0.90 --rate-limit 10000
```

### Automatic Retries

Handles unreliable servers and network issues:
- Retries on HTTP 5xx server errors (500, 502, 503, etc.)
- Retries on network errors (timeouts, connection issues)
- Does NOT retry on 4xx client errors (401, 403, 404, etc.)
- Configurable delay between retries

### Progress Bar

Real-time download feedback showing:
- Visual progress bar
- Percentage complete
- Downloaded size / Total size
- Current download speed
- Estimated time remaining (ETA)

**Example output:**
```
GET   http://camera.example.com/export.cgi?file=timelapse.zip
SAVE  downloads/timelapse.zip
      [===========================>-----------------------] 54.2% 127.45 MB/235.00 MB 10.23 MB/s ETA: 10s
```

### Atomic Downloads

Prevents partial files from appearing in the output directory:
- Downloads to a temporary `.part` file
- Only renames to final filename on successful completion
- Automatically cleans up `.part` files on failure
- Allows safe concurrent runs

### File Size Verification

The `--check-size` flag enables intelligent skip logic:
- Performs HEAD request to get remote file size
- Compares with local file size
- Re-downloads if sizes don't match (incomplete download detected)
- Useful for resuming after interrupted batch downloads

**Example with size checking:**
```
SKIP  file1.zip (already exists, size matches: 12345678 bytes)
INFO  file2.zip exists but size mismatch (local: 1000000, remote: 12345678), re-downloading
SKIP  file3.zip (already exists, cannot verify size)
```

## Exit Codes

- `0`: Success (all downloads completed or skipped)
- `1`: Partial failure (some downloads failed)
- `2`: Failed to fetch archives from camera API
- `130`: Interrupted by user (Ctrl+C)

## Error Handling

The tool provides detailed error messages:
- **SKIP**: File already exists (skipped)
- **INFO**: Informational message (e.g., size mismatch)
- **FAIL**: Download failed after all retries

Failed downloads are reported at the end:
```
Done. downloaded=15 skipped=3 failed=2
```

## Tips and Best Practices

1. **Graceful interruption**: Press Ctrl+C once to gracefully stop after the current download completes. Press Ctrl+C twice to force immediate exit.

2. **Use `--check-size` for resumable downloads**: If you're downloading a large batch and the process gets interrupted, use `--check-size` to detect and re-download incomplete files.

3. **Adjust rate limits for bandwidth management**: Set `--rate-limit` based on your network capacity and server capabilities.

4. **Increase retries for unreliable servers**: Use `--max-retries 5` or higher for servers with frequent 500 errors.

5. **Disable progress bar for logging**: Use `--no-progress` when redirecting output to a log file.

6. **Use quotes for passwords**: Always quote passwords containing special characters: `--pass 'p@ssw0rd!'`

7. **Organize with output directories**: Use `--outdir` to keep downloads organized by date or camera.

8. **Multiple cameras**: Run multiple instances with different `--host` and `--outdir` values to download from multiple cameras simultaneously.

## Troubleshooting

### Cannot Fetch Archives from Camera
- Verify the camera IP address is correct: `--host 192.168.x.x`
- Ensure the camera is running the Timelapse2 ACAP application
- Check that you can access the camera's web interface
- Verify network connectivity to the camera

### Authentication Failures (401/403)
- Verify username and password are correct
- Check that the server supports HTTP Digest authentication
- Ensure credentials have permission to access the files

### Timeout Errors
- Increase timeout: `--timeout 120`
- Check network connectivity to the camera
- Verify the camera is responding

### Rate Limit Issues
- Lower the rate limit: `--rate-limit 50`
- Camera may be throttling connections

### HTTP 500 Errors
- Increase retries and delay: `--max-retries 5 --retry-delay 10`
- Camera may be temporarily overloaded
- Try downloading at a different time

## License

This tool is provided as-is for downloading timelapse archives from Axis cameras running the Timelapse2 ACAP.

## Contributing

Feel free to submit issues and enhancement requests.
