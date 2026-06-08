#!/usr/bin/env python3
# IwannaseeManga — one-command Japanese→Korean manga translation.
# Copyright (C) 2026  IwannaseeManga contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""IwannaseeManga — point it at a folder of manga images and get translated images back.

It is a thin automation layer around BallonsTranslator (the engine):
  1. copies the input images into a private scratch project (outside any cloud-synced folder),
  2. runs BallonsTranslator headlessly (detect → OCR → translate → inpaint → typeset),
  3. collects the rendered pages into your output folder, and
  4. wipes every intermediate trace — project JSON (OCR text + translations),
     masks, inpainted layers, run logs, scratch config — so ONLY the finished
     images remain.

BallonsTranslator (https://github.com/dmMaze/BallonsTranslator) is GPLv3; this
wrapper is a separate program that invokes it and is also GPLv3. See LICENSE.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/"
DEFAULT_MODEL = "claude-sonnet-4-6"   # balanced; claude-opus-4-8 = best, claude-haiku-4-5 = cheapest
DEFAULT_SOURCE = "日本語"
DEFAULT_TARGET = "한국어"


def log(msg: str) -> None:
    print(f"[IwannaseeManga] {msg}", flush=True)


def fail(msg: str) -> "NoReturn":
    print(f"[IwannaseeManga] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def find_bt_dir(arg_value: str | None) -> Path:
    """Locate the BallonsTranslator install (must contain venv + ballontranslator pkg)."""
    candidates = [
        arg_value,
        os.environ.get("IWSM_BT_DIR"),
        str(Path.home() / "BallonsTranslator"),
    ]
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if (p / "ballontranslator").is_dir():
            return p
    fail(
        "Could not find BallonsTranslator. Pass --bt-dir <path> or set the "
        "IWSM_BT_DIR environment variable to your BallonsTranslator checkout."
    )


def bt_python(bt_dir: Path) -> Path:
    """Path to BallonsTranslator's venv interpreter (it has torch/openai/etc. installed)."""
    exe = "python.exe" if os.name == "nt" else "python"
    sub = "Scripts" if os.name == "nt" else "bin"
    py = bt_dir / "venv" / sub / exe
    if not py.exists():
        fail(f"BallonsTranslator venv interpreter not found at {py}")
    return py


def resolve_api_key(arg_value: str | None, bt_dir: Path) -> str:
    """Key precedence: --api-key > ANTHROPIC_API_KEY > config.local.json > BallonsTranslator's config."""
    if arg_value:
        return arg_value.strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    local = Path(__file__).with_name("config.local.json")
    if local.exists():
        try:
            k = json.loads(local.read_text(encoding="utf-8")).get("api_key", "").strip()
            if k:
                return k
        except Exception:
            pass
    # Local convenience fallback: reuse the key already stored in BallonsTranslator.
    bt_cfg = bt_dir / "config" / "config.json"
    if bt_cfg.exists():
        try:
            cfg = json.loads(bt_cfg.read_text(encoding="utf-8"))
            k = cfg["module"]["translator_params"]["ChatGPT"].get("api key", "").strip()
            if k:
                return k
        except Exception:
            pass
    return ""


def build_runtime_config(bt_dir: Path, out_path: Path, *, model: str, source: str,
                         target: str, api_key: str) -> None:
    """Start from BallonsTranslator's own config (correct schema for its version),
    then force the known-good settings for headless JP→KO Claude translation."""
    base = bt_dir / "config" / "config.json"
    cfg = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {"module": {}}
    m = cfg.setdefault("module", {})
    m["ocr"] = "manga_ocr"
    m["textdetector"] = m.get("textdetector") or "ctd"
    m["inpainter"] = m.get("inpainter") or "lama_large_512px"
    m["translator"] = "ChatGPT"
    m["enable_detect"] = True
    m["enable_ocr"] = True
    m["enable_translate"] = True
    m["enable_inpaint"] = True
    m["translate_source"] = source
    m["translate_target"] = target
    gpt = m.setdefault("translator_params", {}).setdefault("ChatGPT", {})
    gpt["override model"] = model
    gpt["3rd party api url"] = ANTHROPIC_URL
    gpt["api key"] = api_key
    out_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def collect_images(input_dir: Path) -> list[Path]:
    imgs = sorted(
        (p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: p.name,
    )
    return imgs


def run_headless(bt_dir: Path, py: Path, proj_dir: Path, cfg_path: Path, log_path: Path) -> int:
    cmd = [
        str(py), "-m", "ballontranslator",
        "--headless",
        "--exec_dirs", str(proj_dir),
        "--config_path", str(cfg_path),
    ]
    log("running BallonsTranslator headlessly... (this can take a while on CPU)")
    with open(log_path, "wb") as logf:
        proc = subprocess.run(cmd, cwd=str(bt_dir), stdout=logf, stderr=subprocess.STDOUT)
    return proc.returncode


def tail(path: Path, n: int = 25) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return "(no log)"


def wipe_new_logs(bt_logs_dir: Path, known_before: set[str]) -> int:
    """Delete only the log files this run created (they contain source text + prompts)."""
    removed = 0
    if not bt_logs_dir.is_dir():
        return 0
    for f in bt_logs_dir.glob("*.log"):
        if f.name not in known_before:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def main(argv=None) -> int:
    # Console may be cp949/cp1252; force UTF-8 so Korean paths, emoji, dashes never crash a print.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        prog="iwannaseemanga",
        description="One-command JP→KO manga translation (BallonsTranslator wrapper). "
                    "Keeps only the finished images; wipes all intermediate traces.",
    )
    ap.add_argument("input", help="folder containing manga images (jpg/png/webp/…)")
    ap.add_argument("-o", "--output", help="output folder (default: <input>_translated)")
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Claude model id (default: {DEFAULT_MODEL})")
    ap.add_argument("--source", default=DEFAULT_SOURCE, help="source language (BallonsTranslator name)")
    ap.add_argument("--target", default=DEFAULT_TARGET, help="target language (BallonsTranslator name)")
    ap.add_argument("--bt-dir", default=None, help="path to BallonsTranslator checkout")
    ap.add_argument("--api-key", default=None, help="Anthropic API key (else env/config/BT fallback)")
    ap.add_argument("--keep-intermediate", action="store_true",
                    help="do NOT wipe the scratch project/logs (debugging)")
    args = ap.parse_args(argv)

    input_dir = Path(args.input).expanduser().resolve()
    if not input_dir.is_dir():
        fail(f"input folder not found: {input_dir}")
    out_dir = Path(args.output).expanduser().resolve() if args.output \
        else input_dir.with_name(input_dir.name + "_translated")

    bt_dir = find_bt_dir(args.bt_dir)
    py = bt_python(bt_dir)
    api_key = resolve_api_key(args.api_key, bt_dir)
    if not api_key:
        fail("no Anthropic API key. Use --api-key, set ANTHROPIC_API_KEY, or add config.local.json.")

    images = collect_images(input_dir)
    if not images:
        fail(f"no images ({', '.join(sorted(IMAGE_EXTS))}) found in {input_dir}")
    log(f"found {len(images)} image(s) in {input_dir}")

    # Scratch workspace OUTSIDE any cloud-synced folder (LOCALAPPDATA / temp).
    work_root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "IwannaseeManga"
    work = work_root / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    proj = work / "job"
    proj.mkdir(parents=True, exist_ok=True)
    for p in images:
        shutil.copy2(p, proj / p.name)
    cfg_path = work / "runtime_config.json"
    build_runtime_config(bt_dir, cfg_path, model=args.model, source=args.source,
                         target=args.target, api_key=api_key)

    bt_logs_dir = bt_dir / "logs"
    logs_before = {f.name for f in bt_logs_dir.glob("*.log")} if bt_logs_dir.is_dir() else set()

    run_log = work / "bt_run.log"
    t0 = time.time()
    rc = run_headless(bt_dir, py, proj, cfg_path, run_log)
    dt = time.time() - t0

    result_dir = proj / "result"
    results = sorted(result_dir.glob("*")) if result_dir.is_dir() else []

    if rc != 0 or not results:
        log(f"BallonsTranslator exited with code {rc} after {dt:.0f}s; results found: {len(results)}")
        log("scratch kept for inspection (cleanup skipped). Last log lines:")
        print(tail(run_log), file=sys.stderr)
        log(f"scratch: {work}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        shutil.copy2(r, out_dir / r.name)
    log(f"translated {len(results)} page(s) in {dt:.0f}s -> {out_dir}")

    # Privacy: leave only the finished images.
    if args.keep_intermediate:
        log(f"--keep-intermediate set; scratch left at {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        n_logs = wipe_new_logs(bt_logs_dir, logs_before)
        log(f"wiped traces: scratch project, masks, inpainted layers, scratch config"
            + (f", {n_logs} run log(s)" if n_logs else "")
            + " - kept only output images.")

    log("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
