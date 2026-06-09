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

A thin automation layer around BallonsTranslator (the engine):
  1. copies the input images into a private scratch project (outside any cloud-synced folder),
  2. runs BallonsTranslator headlessly (detect → OCR → translate → inpaint → typeset),
  3. collects the rendered pages into your output folder, and
  4. wipes every intermediate trace (project JSON, masks, inpainted layers, run
     logs, scratch config) so ONLY the finished images remain.

All post-processing (font, size, stroke/outline, spacing, alignment, erase
quality) is controlled here via settings.json / CLI / --style presets, so you
never edit BallonsTranslator by hand.

BallonsTranslator (https://github.com/dmMaze/BallonsTranslator) is GPLv3; this
wrapper is a separate program that invokes it and is also GPLv3. See LICENSE.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}
ANTHROPIC_URL = "https://api.anthropic.com/v1/"
HERE = Path(__file__).resolve().parent

# Built-in defaults. settings.json (next to this file) overrides these; CLI flags override that.
DEFAULT_SETTINGS = {
    "model": "claude-sonnet-4-6",   # balanced; claude-opus-4-8 = best, claude-haiku-4-5 = cheapest
    "source": "日本語",
    "target": "한국어",
    "style": None,                  # optional preset name (see STYLE_PRESETS)
    "typeset": {
        "font_family": "Jua",       # any font installed in <BallonsTranslator>/fonts or on the system
        "font_size": 24,
        "auto_fit": True,           # shrink text to fit each bubble (recommended)
        "bold": False,
        "italic": False,
        "line_spacing": 1.2,
        "letter_spacing": 1.0,
        "stroke_width": 0.0,        # >0 draws an outline (stroke_color) — good for text over art
        "stroke_color": [255, 255, 255],
        "text_color": None,         # null = auto-detect per bubble (handles black & white text); [r,g,b] = force
        "alignment": "auto",        # auto | left | center | right
    },
    "cleanup": {
        "inpaint_size": 1536,       # higher = cleaner erase of original text, slower
        "mask_dilate": 2,           # grow the erase mask to wipe residual text edges (raise if you see ghosting)
    },
}

# One-click look presets (override typeset.font_family etc.). Fonts must be installed
# (run `--setup-fonts` once to fetch the recommended free set).
STYLE_PRESETS = {
    "comic":       {"font_family": "Jua", "letter_spacing": 1.0},        # rounded, friendly (default)
    "impact":      {"font_family": "Do Hyeon", "letter_spacing": 1.0},   # bold, action
    "handwriting": {"font_family": "Gaegu", "letter_spacing": 1.0},      # casual handwritten
    "clean":       {"font_family": "Pretendard", "letter_spacing": 1.0}, # neutral modern sans
}

ALIGN = {"left": 0, "center": 1, "right": 2}

# Curated free Korean fonts (OFL / free) for --setup-fonts. Family names in comments.
_GF = "https://raw.githubusercontent.com/google/fonts/main/"
FONT_DOWNLOADS = {
    "Jua-Regular.ttf": _GF + "ofl/jua/Jua-Regular.ttf",                       # Jua
    "DoHyeon-Regular.ttf": _GF + "ofl/dohyeon/DoHyeon-Regular.ttf",           # Do Hyeon
    "BlackHanSans-Regular.ttf": _GF + "ofl/blackhansans/BlackHanSans-Regular.ttf",  # Black Han Sans
    "NanumPenScript-Regular.ttf": _GF + "ofl/nanumpenscript/NanumPenScript-Regular.ttf",  # Nanum Pen
    "Gaegu-Regular.ttf": _GF + "ofl/gaegu/Gaegu-Regular.ttf",                 # Gaegu
    "GamjaFlower-Regular.ttf": _GF + "ofl/gamjaflower/GamjaFlower-Regular.ttf",  # Gamja Flower
    "Dokdo-Regular.ttf": _GF + "ofl/dokdo/Dokdo-Regular.ttf",                 # Dokdo
    "Gugi-Regular.ttf": _GF + "ofl/gugi/Gugi-Regular.ttf",                    # Gugi
    "GothicA1-Regular.ttf": _GF + "ofl/gothica1/GothicA1-Regular.ttf",        # Gothic A1
    "GowunDodum-Regular.ttf": _GF + "ofl/gowundodum/GowunDodum-Regular.ttf",  # Gowun Dodum
    "NanumGothic-Regular.ttf": _GF + "ofl/nanumgothic/NanumGothic-Regular.ttf",  # NanumGothic
    "Sunflower-Medium.ttf": _GF + "ofl/sunflower/Sunflower-Medium.ttf",       # Sunflower
    "Pretendard-Regular.otf": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/packages/pretendard/dist/public/static/Pretendard-Regular.otf",  # Pretendard
}


def log(msg: str) -> None:
    print(f"[IwannaseeManga] {msg}", flush=True)


def fail(msg: str) -> "NoReturn":
    print(f"[IwannaseeManga] ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def find_bt_dir(arg_value: str | None) -> Path:
    """Locate the BallonsTranslator install (must contain venv + ballontranslator pkg)."""
    for c in (arg_value, os.environ.get("IWSM_BT_DIR"), str(Path.home() / "BallonsTranslator")):
        if c and (Path(c) / "ballontranslator").is_dir():
            return Path(c)
    fail("Could not find BallonsTranslator. Pass --bt-dir <path> or set IWSM_BT_DIR.")


def bt_python(bt_dir: Path) -> Path:
    exe, sub = ("python.exe", "Scripts") if os.name == "nt" else ("python", "bin")
    py = bt_dir / "venv" / sub / exe
    if not py.exists():
        fail(f"BallonsTranslator venv interpreter not found at {py}")
    return py


def deep_merge(base: dict, over: dict) -> dict:
    """Recursively merge `over` into a copy of `base`."""
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        elif v is not None or k not in out:
            out[k] = v
    return out


def load_settings() -> dict:
    """Built-in defaults, overlaid with settings.json next to this script (if present)."""
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    sf = HERE / "settings.json"
    if sf.exists():
        try:
            settings = deep_merge(settings, json.loads(sf.read_text(encoding="utf-8")))
        except Exception as e:
            log(f"warning: could not read settings.json ({e}); using defaults")
    return settings


def resolve_api_key(arg_value: str | None, bt_dir: Path) -> str:
    """Key precedence: --api-key > ANTHROPIC_API_KEY > config.local.json > BallonsTranslator's config."""
    if arg_value:
        return arg_value.strip()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    local = HERE / "config.local.json"
    if local.exists():
        try:
            k = json.loads(local.read_text(encoding="utf-8")).get("api_key", "").strip()
            if k:
                return k
        except Exception:
            pass
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


def _apply_typeset(cfg: dict, ts: dict) -> None:
    """Write the typeset settings into BallonsTranslator's global_fontformat + let_* flags.

    let_*_flag == 1 forces the global value onto every translated block; we only
    force colors/alignment when the user asked for them, so auto-detection still
    handles e.g. white-on-black bubbles by default.
    """
    gf = cfg.setdefault("global_fontformat", {})
    gf["font_family"] = ts["font_family"]
    gf["font_size"] = int(ts["font_size"])
    gf["bold"] = bool(ts.get("bold", False))
    gf["italic"] = bool(ts.get("italic", False))
    gf["line_spacing"] = float(ts.get("line_spacing", 1.2))
    gf["letter_spacing"] = float(ts.get("letter_spacing", 1.0))
    stroke = float(ts.get("stroke_width", 0.0) or 0.0)
    gf["stroke_width"] = stroke

    cfg["let_family_flag"] = 1                                  # always use our font
    cfg["let_fntsize_flag"] = 0 if ts.get("auto_fit", True) else 1
    cfg["let_autolayout_flag"] = True
    cfg["let_uppercase_flag"] = False
    cfg["let_fnteffect_flag"] = 1
    cfg["let_fntstroke_flag"] = 1                               # apply our stroke_width (0 = none)

    if stroke > 0:
        gf["srgb"] = list(ts.get("stroke_color") or [255, 255, 255])
        cfg["let_fnt_scolor_flag"] = 1
    else:
        cfg["let_fnt_scolor_flag"] = 0

    tc = ts.get("text_color")
    if tc:
        gf["frgb"] = list(tc)
        cfg["let_fntcolor_flag"] = 1
    else:
        cfg["let_fntcolor_flag"] = 0                           # auto-detect per bubble

    av = ALIGN.get(str(ts.get("alignment", "auto")).lower())
    if av is not None:
        gf["alignment"] = av
        cfg["let_alignment_flag"] = 1
    else:
        cfg["let_alignment_flag"] = 0                          # auto from detection


def _apply_cleanup(cfg: dict, cl: dict) -> None:
    """Erase-quality knobs: inpaint resolution + text-mask dilation."""
    m = cfg.setdefault("module", {})
    inp = m.get("inpainter") or "lama_large_512px"
    ipar = m.setdefault("inpainter_params", {}).setdefault(inp, {})
    if cl.get("inpaint_size"):
        ipar["inpaint_size"] = int(cl["inpaint_size"])
    det = m.get("textdetector") or "ctd"
    dpar = m.setdefault("textdetector_params", {}).setdefault(det, {})
    if cl.get("mask_dilate") is not None:
        dpar["mask dilate size"] = int(cl["mask_dilate"])


def build_runtime_config(bt_dir: Path, out_path: Path, settings: dict, api_key: str) -> None:
    """Start from BallonsTranslator's own config (correct schema for its version),
    then force the known-good translation settings + all post-processing options."""
    base = bt_dir / "config" / "config.json"
    cfg = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {"module": {}}
    m = cfg.setdefault("module", {})
    m["ocr"] = "manga_ocr"
    m["textdetector"] = m.get("textdetector") or "ctd"
    m["inpainter"] = m.get("inpainter") or "lama_large_512px"
    m["translator"] = "ChatGPT"
    m["enable_detect"] = m["enable_ocr"] = m["enable_translate"] = m["enable_inpaint"] = True
    m["translate_source"] = settings["source"]
    m["translate_target"] = settings["target"]
    gpt = m.setdefault("translator_params", {}).setdefault("ChatGPT", {})
    gpt["override model"] = settings["model"]
    gpt["3rd party api url"] = ANTHROPIC_URL
    gpt["api key"] = api_key

    _apply_typeset(cfg, settings["typeset"])
    _apply_cleanup(cfg, settings["cleanup"])

    out_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


def collect_images(input_dir: Path) -> list[Path]:
    return sorted((p for p in input_dir.iterdir()
                   if p.is_file() and p.suffix.lower() in IMAGE_EXTS), key=lambda p: p.name)


def run_headless(bt_dir: Path, py: Path, proj_dir: Path, cfg_path: Path, log_path: Path) -> int:
    cmd = [str(py), "-m", "ballontranslator", "--headless",
           "--exec_dirs", str(proj_dir), "--config_path", str(cfg_path)]
    log("running BallonsTranslator headlessly... (this can take a while on CPU)")
    # stdin=DEVNULL: BallonsTranslator's headless loop calls input() once the batch
    # is done; with no stdin it gets EOF and (with our ensure_bt_patched fix) exits
    # cleanly. This is why a direct `python iwannaseemanga.py ...` no longer hangs —
    # the run.bat "echo exit" trick is no longer needed.
    with open(log_path, "wb") as logf:
        return subprocess.run(cmd, cwd=str(bt_dir), stdin=subprocess.DEVNULL,
                              stdout=logf, stderr=subprocess.STDOUT).returncode


def tail(path: Path, n: int = 25) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:])
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


def setup_fonts(bt_dir: Path) -> int:
    """Download the curated free Korean font set into <BallonsTranslator>/fonts."""
    dest = bt_dir / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    ok, failed = [], []
    for name, url in FONT_DOWNLOADS.items():
        target = dest / name
        if target.exists() and target.stat().st_size > 0:
            ok.append(name + " (exists)")
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IwannaseeManga"})
            with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                data = r.read()
            target.write_bytes(data)
            ok.append(name)
        except Exception as e:
            failed.append(f"{name} ({e})")
    log(f"fonts -> {dest}")
    log(f"installed {len(ok)}: {', '.join(ok)}")
    if failed:
        log(f"failed {len(failed)}: {', '.join(failed)}")
    return 0 if not failed else 1


def list_fonts(bt_dir: Path) -> int:
    dest = bt_dir / "fonts"
    files = sorted(list(dest.glob("*.ttf")) + list(dest.glob("*.otf"))) if dest.is_dir() else []
    log(f"fonts in {dest}: " + (", ".join(f.stem for f in files) if files else "(none)"))
    log("style presets: " + ", ".join(f"{k} ({v['font_family']})" for k, v in STYLE_PRESETS.items()))
    return 0


# --- BallonsTranslator compatibility patches --------------------------------
# IwannaseeManga drives BallonsTranslator headlessly against Anthropic's API.
# Two upstream behaviours break that out of the box, so we patch the user's BT
# checkout idempotently (on first run, or via --patch-bt) to make a fresh install
# "just work":
#   1. trans_chatgpt.py sends both `temperature` and `top_p`. Anthropic's
#      OpenAI-compatible endpoint rejects that combination, and Opus models reject
#      both -> the API errors out and you get blank translations.
#   2. mainwindow.py blocks on input() at the end of a headless batch, so the run
#      never exits; and a piped "exit" can carry a UTF-8 BOM that hides it.
# Both edits are minimal and being contributed upstream. Revert any time with:
#   git -C <BallonsTranslator> checkout -- <file>
BT_PATCHES = [
    {
        "name": "trans_chatgpt.py: don't send temperature+top_p to Anthropic",
        "relpath": "ballontranslator/modules/translators/trans_chatgpt.py",
        "marker": "Anthropic's OpenAI-compatible endpoint rejects",
        "old": (
            "        func_args = {\n"
            "            'model': model,\n"
            "            'messages': messages,\n"
            "            'temperature': self.temperature,\n"
            "            'top_p': self.top_p,\n"
            "        }\n"
        ),
        "new": (
            "        func_args = {\n"
            "            'model': model,\n"
            "            'messages': messages,\n"
            "        }\n"
            "        # Anthropic's OpenAI-compatible endpoint rejects sending temperature and top_p\n"
            "        # together, and Opus models reject both; send at most temperature for non-Opus.\n"
            "        if 'opus' not in model.lower():\n"
            "            func_args['temperature'] = self.temperature\n"
        ),
    },
    {
        "name": "mainwindow.py: exit headless run on EOF / BOM-prefixed 'exit'",
        "relpath": "ballontranslator/ui/mainwindow.py",
        "marker": "Non-interactive/headless automation",
        "old": (
            "            new_exec_dirs = input()\n"
            "            if new_exec_dirs.strip().lower() == 'exit':\n"
        ),
        "new": (
            "            try:\n"
            "                new_exec_dirs = input()\n"
            "            except EOFError:\n"
            "                # Non-interactive/headless automation: no stdin -> exit cleanly (code 0).\n"
            "                new_exec_dirs = 'exit'\n"
            "            # Strip a possible UTF-8 BOM so a piped \"exit\" is recognised.\n"
            "            if new_exec_dirs.strip().lstrip('\\ufeff').lower() == 'exit':\n"
        ),
    },
]


def ensure_bt_patched(bt_dir: Path, verbose: bool = False):
    """Apply the BallonsTranslator compatibility patches in place, idempotently.

    Returns (applied, already, problems) lists of human-readable names. Never
    raises on version drift: if the expected code isn't found, it records a
    problem and leaves the file untouched (README documents the manual fix).
    File newlines are preserved so we don't churn the whole file.
    """
    applied, already, problems = [], [], []
    for p in BT_PATCHES:
        target = bt_dir / p["relpath"]
        if not target.exists():
            problems.append(f"{p['name']} — file not found: {target}")
            continue
        with open(target, "r", encoding="utf-8", newline="") as f:
            raw = f.read()
        norm = raw.replace("\r\n", "\n")
        if p["marker"] in norm:
            already.append(p["name"])
            continue
        if p["old"] not in norm:
            problems.append(f"{p['name']} — expected code not found (BallonsTranslator version changed?)")
            continue
        nl = "\r\n" if "\r\n" in raw else "\n"
        patched = norm.replace(p["old"], p["new"], 1).replace("\n", nl)
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write(patched)
        applied.append(p["name"])
    if verbose:
        for n in applied:
            log(f"patched: {n}")
        for n in already:
            log(f"already patched: {n}")
    for w in problems:
        log(f"warning: could not patch — {w}")
    return applied, already, problems


def main(argv=None) -> int:
    # Console may be cp949/cp1252; force UTF-8 so Korean paths, emoji, dashes never crash a print.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    settings = load_settings()
    ts_def, cl_def = settings["typeset"], settings["cleanup"]

    ap = argparse.ArgumentParser(
        prog="iwannaseemanga",
        description="One-command JP→KO manga translation (BallonsTranslator wrapper). "
                    "Keeps only the finished images; wipes all intermediate traces.",
    )
    ap.add_argument("input", nargs="?", help="folder containing manga images (jpg/png/webp/…)")
    ap.add_argument("-o", "--output", help="output folder (default: <input>_translated)")
    ap.add_argument("--model", default=settings["model"], help="Claude model id")
    ap.add_argument("--source", default=settings["source"], help="source language (BallonsTranslator name)")
    ap.add_argument("--target", default=settings["target"], help="target language (BallonsTranslator name)")
    ap.add_argument("--style", choices=sorted(STYLE_PRESETS), default=settings.get("style"),
                    help="look preset (sets font etc.)")
    ap.add_argument("--font", help="font family (overrides style/settings)")
    ap.add_argument("--font-size", type=int, help="base font size")
    ap.add_argument("--no-auto-fit", action="store_true", help="use a fixed font size (no shrink-to-fit)")
    ap.add_argument("--stroke", type=float, help="outline width (0 = none)")
    ap.add_argument("--inpaint-size", type=int, help="erase resolution (higher = cleaner, slower)")
    ap.add_argument("--mask-dilate", type=int, help="grow erase mask (raise to remove ghosting)")
    ap.add_argument("--bt-dir", default=None, help="path to BallonsTranslator checkout")
    ap.add_argument("--api-key", default=None, help="Anthropic API key (else env/config/BT fallback)")
    ap.add_argument("--keep-intermediate", action="store_true", help="do NOT wipe scratch/logs (debug)")
    ap.add_argument("--setup-fonts", action="store_true", help="download the recommended free fonts, then exit")
    ap.add_argument("--list-fonts", action="store_true", help="list installed fonts + presets, then exit")
    ap.add_argument("--patch-bt", action="store_true",
                    help="apply BallonsTranslator compatibility patches, then exit (also done automatically on first run)")
    args = ap.parse_args(argv)

    bt_dir = find_bt_dir(args.bt_dir)

    if args.patch_bt:
        applied, already, problems = ensure_bt_patched(bt_dir, verbose=True)
        if not applied and not already:
            return 1  # nothing was patched and nothing was already in place (warnings printed)
        log("BallonsTranslator already up to date." if not applied
            else f"done: applied {len(applied)} patch(es).")
        return 0 if not problems else 1
    if args.setup_fonts:
        return setup_fonts(bt_dir)
    if args.list_fonts:
        return list_fonts(bt_dir)
    if not args.input:
        ap.error("input folder is required (or use --setup-fonts / --list-fonts)")

    # Merge precedence: settings -> --style preset -> individual CLI flags.
    if args.style:
        settings["typeset"] = deep_merge(ts_def, STYLE_PRESETS[args.style])
    settings["model"], settings["source"], settings["target"] = args.model, args.source, args.target
    ts = settings["typeset"]
    if args.font:
        ts["font_family"] = args.font
    if args.font_size is not None:
        ts["font_size"] = args.font_size
    if args.no_auto_fit:
        ts["auto_fit"] = False
    if args.stroke is not None:
        ts["stroke_width"] = args.stroke
    if args.inpaint_size is not None:
        cl_def["inpaint_size"] = args.inpaint_size
    if args.mask_dilate is not None:
        cl_def["mask_dilate"] = args.mask_dilate

    input_dir = Path(args.input).expanduser().resolve()
    if not input_dir.is_dir():
        fail(f"input folder not found: {input_dir}")
    out_dir = Path(args.output).expanduser().resolve() if args.output \
        else input_dir.with_name(input_dir.name + "_translated")

    py = bt_python(bt_dir)
    applied, _already, _problems = ensure_bt_patched(bt_dir)
    if applied:
        log(f"applied {len(applied)} BallonsTranslator compatibility patch(es) (one-time setup).")
    api_key = resolve_api_key(args.api_key, bt_dir)
    if not api_key:
        fail("no Anthropic API key. Use --api-key, set ANTHROPIC_API_KEY, or add config.local.json.")

    images = collect_images(input_dir)
    if not images:
        fail(f"no images ({', '.join(sorted(IMAGE_EXTS))}) found in {input_dir}")
    log(f"found {len(images)} image(s); font={ts['font_family']}, model={settings['model']}")

    # Scratch workspace OUTSIDE any cloud-synced folder (LOCALAPPDATA / temp).
    work_root = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "IwannaseeManga"
    work = work_root / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    proj = work / "job"
    proj.mkdir(parents=True, exist_ok=True)
    for p in images:
        shutil.copy2(p, proj / p.name)
    cfg_path = work / "runtime_config.json"
    build_runtime_config(bt_dir, cfg_path, settings, api_key)

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
        log("wiped traces: scratch project, masks, inpainted layers, scratch config"
            + (f", {n_logs} run log(s)" if n_logs else "")
            + " - kept only output images.")

    log("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
