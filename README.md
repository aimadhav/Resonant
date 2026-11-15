# Intervals

Podcast listening app and operator studio with contextual advertising. **No Docker or Codex required.** The checkout contains advertiser fixtures, not private audio or credentials. It starts with an empty library.

## Start

Prerequisites: Python **3.11 or 3.12**, Git, FFmpeg and `ffprobe` on PATH. FFmpeg installation examples: `winget install Gyan.FFmpeg` (Windows), `brew install ffmpeg` (macOS), or `sudo apt install ffmpeg` (Debian/Ubuntu). Open a new terminal after changing PATH.

```bash
git clone <your-repository-url>
cd intervals
python setup.py
python run.py
```

Use `python3` if that is your Python command. Setup creates `.venv` and copies `.env.example` without overwriting existing settings. Activation is unnecessary. Listener: **http://127.0.0.1:5097/** · Studio: **http://127.0.0.1:5097/studio**. No API keys or Kaggle account are needed just to start, upload and listen.

## Local GPU processing — no Kaggle account

Local acceleration targets **NVIDIA CUDA**. CPU mode is supported, including on Macs; other GPU backends are not implemented. Install compatible drivers and CUDA libraries. The upstream [WhisperX guide](https://github.com/m-bain/whisperX#setup) documents CUDA 12.8; consult [PyTorch installation guidance](https://pytorch.org/get-started/locally/) for your hardware. Versions are pinned to the successful cloud run: WhisperX 3.8.6 and Torch 2.8.0.

```bash
python setup.py --processing --torch-index-url https://download.pytorch.org/whl/cu128
python run.py
```

This creates an isolated `.processor-venv` and prints the device PyTorch detects. In Studio → Episodes → Process this episode, choose **My device**, then **NVIDIA CUDA GPU** or Auto. Explicit CUDA mode fails if CUDA is unavailable rather than silently switching to CPU. First use downloads model weights from the internet.

For CPU:

```bash
python setup.py --processing --torch-index-url https://download.pytorch.org/whl/cpu
```

Choose CPU in Studio; long episodes can be slow. Use Small for lower GPU-memory requirements. `config.json` controls pipeline defaults. An existing compatible worker environment can be selected with `LOCAL_PROCESSOR_PYTHON` in `.env`.

### Standalone offline worker

Windows:

```powershell
.processor-venv\Scripts\python local_processor.py --check --device cuda
.processor-venv\Scripts\python local_processor.py --audio episode.mp3 --out results/my-episode --device cuda --model small
```

Linux/macOS:

```bash
.processor-venv/bin/python local_processor.py --check --device auto
.processor-venv/bin/python local_processor.py --audio episode.mp3 --out results/my-episode --device auto --model small
```

This runs the same decode, transcription, alignment, energy/VAD, embeddings and candidate pipeline used on Kaggle, directly on your device. Outputs include transcript/candidate data, `runtime.json`, `worker_status.json`, `compute_timings.json` and `compute.log`. Optional `--transcript existing-whisperx.json` reuses an aligned transcript. Studio additionally performs Gemini boundary review, ad generation and publishing.

## Ad API keys

Edit `.env`: set `GEMINI_API_KEY` and `GNANI_API_KEY`. Keep `PROCESSING_BACKEND=local` for local processing. Backup keys are optional. Local transcription/acoustic processing does not use these APIs; Gemini text reviews/writing and Gnani speech still require internet and their respective credentials. Never commit `.env`, voice samples, embeddings or private recordings.

## Optional Kaggle cloud

Run `python setup.py --kaggle` to install the optional CLI, set **your own** `KAGGLE_USERNAME` in `.env`, authenticate once, and select Kaggle cloud in Studio. On Windows use `login.ps1`. On Linux/macOS:

```bash
export KAGGLE_CONFIG_DIR="$PWD/.kaggle"
.venv/bin/kaggle auth login
python run.py
```

You need your own Kaggle compute access and quota. Upload, submission, polling and download are automatic. Local mode does not authenticate with or upload to Kaggle.

## Workflow and verification

Upload in Episodes → choose local/Kaggle processing → authorize Gemini transcript review → choose businesses and listener preferences in Campaigns → prepare → publish to listeners. Three slot teams run concurrently. Analysis stays cached across campaign/profile changes. Keep the app running during processing. Remote-running-job recovery remains limited.

```bash
python verify_clone.py
python -m unittest discover -s tests -p "test_*.py"
```

`verify_clone.py` tests empty startup, both frontends, upload and range-streaming using synthetic audio, with no provider calls. GPU routing and failure behavior have unit coverage; real CUDA inference must still be validated on the recipient's hardware because this development host has no available NVIDIA CUDA device.

Runtime data lives in ignored `cache/` and `jobs/` folders. The supplied tests require FFmpeg; some pipeline tests need the processing packages. Custom voices remain permission-scoped; publishing downloadable custom-voice editions is blocked. This is a localhost demo, not an authenticated public service.
