# Real-time visualizer for the IDUN Guardian

## Overview

This repo visualizes real-time data and predictions from the IDUN Guardian, and synchronizes recorded sessions with a local backend for further analysis (`front_end/backend_client.py`).

Currently shown in the display window:
- **Filtered EEG signal**: real-time view of the filtered EEG channel.
- **Quality score**: signal quality reported by the SDK, used to gate which windows are usable for analysis.
- **FFT band z-scores**: per-band z-scores from the SDK's realtime predictions.
- **Absolute band power (Welch)**: client-side Welch estimate of absolute power per band (Delta/Theta/Alpha/Sigma/Beta/Gamma), computed from the filtered EEG buffer.

The following are still computed/captured in the code but currently **not shown** in the UI (disabled, not removed — see the corresponding comments in `front_end/` for how to bring them back):
- Cognitive Load Index (CLI) — calculation and axis both disabled.
- Jaw clench / horizontal eye movement (HEOG) classifiers — detection variables still populated, icon display commented out.
- IMU data (accelerometer, magnetometer, gyroscope) — samples still buffered, plots commented out.

## Prerequisites

- **Python 3.9** — this specific version, pinned in `Pipfile` (`python_version = "3.9"`). Newer Python versions are not supported by the dependencies as currently pinned. Download [here](https://www.python.org/downloads/release/python-3913/) if you don't already have it — python.org still hosts old releases even after end-of-life.
- **Pipenv**: install via `pip`:
  ```bash
  > pip install pipenv
  ```
- **Realtime predictions**: your IDUN account should have realtime predictions activated. If this is not the case, contact an IDUNian.

## Installation

1. **Create an empty virtual environment folder.** This makes pipenv create the venv *inside* the project instead of a global, harder-to-find location:
   ```bash
   > mkdir .venv
   ```

2. **Install dependencies** (runtime + dev/test tools):
   ```bash
   > pipenv install --dev
   ```
   `pipenv install` without `--dev` skips `pytest` and the other test-only dependencies — fine if you only want to run `main.py` and never touch `tests/`.

## Setup

Open `main.py` and configure your device address, API key, and any preferred recording parameters at the top of the script.

Backend and signal-processing constants (NTP server, upload chunk size, Welch window, band definitions, log folder, etc.) live in `front_end/config.py`.

## Usage

**Run the visualizer:**
```bash
> pipenv run python main.py
```
This is equivalent to running `pipenv shell` and then `python main.py`, but doesn't require activating a shell first — see Troubleshooting below if `pipenv shell` misbehaves on your machine.

**Run the test suite** (see `tests/`):
```bash
> pipenv run python -m pytest
```

**Run the test suite with coverage** (see `tests/`):
```bash
> pipenv run python -m pytest --cov=front_end --cov-report=term-missing
```

Run both from the repository root, and keep the `python -m` form: it puts the current directory on `sys.path`, which is how the tests find the `front_end` package. A bare `pipenv run pytest` fails at collection with `ModuleNotFoundError: No module named 'front_end'`.

**Session logs**: recorded sessions are written as CSV under `logs/`, created automatically on the first recording (click Start).