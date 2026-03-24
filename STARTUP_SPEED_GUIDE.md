# RTG Startup Speed Guide

This note explains what should be installed on a Windows machine to make RTG start faster and more reliably.

## Recommended Setup

For the fastest startup, do not use the packaged portable runtime as the primary mode.

Install these on the target computer:

1. Python 3.14 x64
2. Microsoft Visual C++ Redistributable 2015-2022 x64
3. Project dependencies from `requirements.txt`

Then run RTG in local Python mode instead of the bundled exe/runtime.

## Why This Is Faster

The packaged builds are convenient, but they start slower because they must:

- initialize an embedded runtime
- load bundled libraries from a packaged directory
- trigger extra Windows Defender scanning on first launch

A normal local Python install is usually faster because the system already trusts and caches the runtime.

## What To Install

### 1. Python

Install:

- Python 3.14 x64

Make sure these are enabled during install:

- `Add python.exe to PATH`
- `pip`
- `py launcher`

## 2. Visual C++ Runtime

Install:

- Microsoft Visual C++ Redistributable 2015-2022 x64

This helps native Python wheels and runtime libraries load correctly and consistently.

## 3. Python Packages

From the project root, install:

```powershell
pip install -r requirements.txt
```

Current required packages are:

- `beautifulsoup4`
- `fastapi`
- `httpx`
- `jinja2`
- `pytest`
- `uvicorn`

## Best Runtime Mode

After installing Python and dependencies, use this mode:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

This is usually faster than:

- portable runtime bundle
- packaged exe

## Security Software Advice

If startup is still slow, Windows Defender is often the main reason.

Add exclusions for:

- the RTG project folder
- the Python install folder
- the SQLite database file under `data/`

Typical folders:

- `E:\Program\RTG`
- `C:\Python314`

## Optional Improvements

These are not mandatory, but they often help:

- keep the project on an SSD
- avoid running directly from a ZIP extraction temp folder
- avoid very deep or network-mapped paths
- launch once, then relaunch again to benefit from file cache

## Recommended Workflow

1. Install Python 3.14 x64
2. Install VC++ Redistributable x64
3. Run `pip install -r requirements.txt`
4. Start with:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Bottom Line

If you want the best startup speed, the target machine should have:

- Python 3.14 x64
- VC++ Redistributable x64
- dependencies installed locally

The exe/portable build is best for convenience.
The local Python environment is best for speed.
