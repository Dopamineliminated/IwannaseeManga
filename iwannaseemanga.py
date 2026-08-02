#!/usr/bin/env python3
# IwannaseeManga — one-command comic/manga translation into Korean (Japanese OR English source).
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
"""IwannaseeManga — point it at a folder of comic/manga images and get Korean ones back.

Handles BOTH Japanese→Korean and English→Korean; pick the source language and the
right OCR engine is selected automatically (Japanese → manga_ocr, English →
mit48px_ctc). It is a thin automation layer around BallonsTranslator (the engine):
  1. copies the input images into a private scratch project (outside any cloud-synced folder),
  2. runs BallonsTranslator headlessly (detect → OCR → translate → inpaint → typeset),
  3. collects the rendered pages into your output folder, and
  4. wipes every intermediate trace (project JSON, masks, inpainted layers, run
     logs, scratch config) so ONLY the finished images remain.

Run it with no arguments (or double-click run.bat) to open a small window where you
choose the folder, output location, translation model and language, then click
Translate. Or drive it from the command line (see --help). All post-processing
(font, size, stroke/outline, spacing, alignment, erase quality) is controlled here
via settings.json / CLI / --style presets, so you never edit BallonsTranslator by hand.

BallonsTranslator (https://github.com/dmMaze/BallonsTranslator) is GPLv3; this
wrapper is a separate program that invokes it and is also GPLv3. See LICENSE.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import string
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

# Supported source languages → the BallonsTranslator language name + the OCR engine
# that can read it. Japanese uses the Japanese-only manga_ocr; English uses the
# Latin-capable mit48px_ctc (from manga-image-translator).
LANGUAGES = {
    "Japanese": {"source": "日本語", "ocr": "manga_ocr"},
    "English":  {"source": "English", "ocr": "mit48px_ctc"},
}
# Accepted --language aliases (case-insensitive) → canonical key.
_LANG_ALIASES = {
    "japanese": "Japanese", "jp": "Japanese", "ja": "Japanese", "日本語": "Japanese", "일본어": "Japanese",
    "english": "English", "en": "English", "eng": "English", "영어": "English",
}

# Claude models offered in the GUI dropdown (label shown, id sent).
MODEL_CHOICES = [
    ("Sonnet — 균형·추천", "claude-sonnet-4-6"),
    ("Opus — 최고 품질", "claude-opus-4-8"),
    ("Haiku — 가장 저렴", "claude-haiku-4-5"),
]
# Languages offered in the GUI dropdown (label shown, LANGUAGES key).
LANGUAGE_CHOICES = [
    ("일본어 → 한국어", "Japanese"),
    ("영어 → 한국어", "English"),
]

# Built-in defaults. settings.json (next to this file) overrides these; CLI flags / GUI override that.
DEFAULT_SETTINGS = {
    "model": "claude-sonnet-4-6",   # balanced; claude-opus-4-8 = best, claude-haiku-4-5 = cheapest
    "language": "Japanese",         # default source language; picks the source name + OCR engine
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


class IwsmError(Exception):
    """Recoverable error; CLI prints it and exits 1, the GUI shows it without crashing."""


# Optional sink so the GUI can mirror progress into its log pane (set while a job runs).
_LOG_SINK = None


def log(msg: str) -> None:
    print(f"[IwannaseeManga] {msg}", flush=True)
    if _LOG_SINK is not None:
        try:
            _LOG_SINK(msg)
        except Exception:
            pass


def fail(msg: str) -> "NoReturn":
    raise IwsmError(msg)


# Where an auto-discovered BallonsTranslator path is remembered, so we don't rescan every run.
_BT_CACHE = HERE / ".bt_dir"


def _is_bt_root(p: Path) -> bool:
    """A BallonsTranslator checkout/install has a `ballontranslator` package dir."""
    try:
        return (p / "ballontranslator").is_dir()
    except OSError:
        return False


def _remember_bt(p: Path) -> None:
    try:
        _BT_CACHE.write_text(str(p), encoding="utf-8")
    except OSError:
        pass


def _bt_search_parents() -> "list[Path]":
    """Common folders a BallonsTranslator install might sit directly under."""
    home = Path.home()
    parents = [home, home / "Desktop", home / "Documents", home / "Downloads",
               home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents",
               home / "OneDrive" / "바탕 화면", home / "OneDrive" / "문서"]
    if os.name == "nt":
        parents += [Path(f"{d}:\\") for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
        parents += [Path(r"C:\Program Files"), Path(r"C:\Program Files (x86)")]
    else:
        parents += [Path("/opt"), Path("/usr/local")]
    out, seen = [], set()
    for p in parents:
        key = str(p).lower()
        if key not in seen and p.exists():
            seen.add(key)
            out.append(p)
    return out


def find_bt_dir(arg_value: str | None) -> Path:
    """Locate BallonsTranslator (a dir containing the `ballontranslator` package).

    Order: --bt-dir, IWSM_BT_DIR, a remembered path, common install locations,
    then a bounded scan of the home folder and every drive root.
    """
    for c in (arg_value, os.environ.get("IWSM_BT_DIR")):        # explicit wins
        if c and _is_bt_root(Path(c)):
            return Path(c).resolve()
    if _BT_CACHE.exists():                                       # remembered from a previous run
        try:
            cached = Path(_BT_CACHE.read_text(encoding="utf-8").strip())
            if _is_bt_root(cached):
                return cached.resolve()
        except OSError:
            pass

    names = ("BallonsTranslator", "BallonsTranslator-master", "BallonsTranslator-main")
    parents = _bt_search_parents()
    for p in parents:                                           # common exact paths (instant)
        for n in names:
            cand = p / n
            if _is_bt_root(cand):
                log(f"auto-detected BallonsTranslator at {cand}")
                _remember_bt(cand.resolve())
                return cand.resolve()
    for p in parents:                                           # one level down (e.g. renamed folder)
        try:
            for child in sorted(p.iterdir()):
                if child.is_dir() and "ballonstranslator" in child.name.lower().replace(" ", "") \
                        and _is_bt_root(child):
                    log(f"auto-detected BallonsTranslator at {child}")
                    _remember_bt(child.resolve())
                    return child.resolve()
        except OSError:
            pass

    # Bounded deep scan (skip system/heavy dirs; give up after a while), stop at first hit.
    log("BallonsTranslator not in the usual spots; scanning drives (this can take a moment)...")
    skip = {"windows", "$recycle.bin", "system volume information", "program files",
            "program files (x86)", "programdata", "appdata", "node_modules",
            ".git", "venv", "__pycache__", "windowsapps", "onedrivetemp"}
    roots, seen = [], set()
    drive_roots = ([Path(f"{d}:\\") for d in string.ascii_uppercase if Path(f"{d}:\\").exists()]
                   if os.name == "nt" else [Path("/")])
    for r in [Path.home()] + drive_roots:
        if str(r).lower() not in seen and r.exists():
            seen.add(str(r).lower())
            roots.append(r)
    deadline = time.time() + 25
    for root in roots:
        base = len(root.parts)
        for dirpath, dirnames, _ in os.walk(root):
            if time.time() > deadline:
                break
            d = Path(dirpath)
            if len(d.parts) - base >= 4:
                dirnames[:] = []
                continue
            dirnames[:] = [dn for dn in dirnames
                           if dn.lower() not in skip and not dn.startswith(".")]
            if "ballonstranslator" in d.name.lower().replace(" ", "") and _is_bt_root(d):
                log(f"auto-detected BallonsTranslator at {d}")
                _remember_bt(d.resolve())
                return d.resolve()
        if time.time() > deadline:
            break
    fail("Could not find BallonsTranslator on this PC. Install it, or pass --bt-dir <path> "
         "or set IWSM_BT_DIR. (Searched home, Desktop, Documents, Downloads, and all drives.)")


def bt_python(bt_dir: Path) -> Path:
    """BallonsTranslator's Python interpreter — a venv for a source install, or a
    bundled runtime for the portable build."""
    if os.name == "nt":
        candidates = [bt_dir / "venv" / "Scripts" / "python.exe",
                      bt_dir / "python" / "python.exe",
                      bt_dir / "runtime" / "python.exe"]
    else:
        candidates = [bt_dir / "venv" / "bin" / "python",
                      bt_dir / "python" / "bin" / "python"]
    for py in candidates:
        if py.exists():
            return py
    fail(f"Found BallonsTranslator at {bt_dir}, but not its Python interpreter "
         f"(looked for: {', '.join(str(c) for c in candidates)}). "
         "Make sure its virtual environment is installed.")


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


def normalize_language(value: str | None) -> str | None:
    """Map a user-supplied language string to a canonical LANGUAGES key (or None)."""
    if not value:
        return None
    return _LANG_ALIASES.get(value.strip().lower(), value if value in LANGUAGES else None)


def resolve_language(settings: dict, lang_arg=None, source_arg=None, ocr_arg=None):
    """Work out the (source language name, OCR engine) to use.

    Priority: an explicit --source/--ocr wins; otherwise both are derived from the
    chosen language (--language > settings.json "language" > Japanese)."""
    lang_key = normalize_language(lang_arg) or normalize_language(settings.get("language")) or "Japanese"
    li = LANGUAGES.get(lang_key, LANGUAGES["Japanese"])
    source = source_arg or settings.get("source") or li["source"]
    ocr = ocr_arg or settings.get("ocr") or li["ocr"]
    return source, ocr


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
    m["ocr"] = settings["ocr"]                          # manga_ocr (JP) or mit48px_ctc (EN), per language
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


def resolve_images(input_path: Path):
    """Accept a folder of images OR a single image file. Returns (images, default_output_dir)."""
    input_path = input_path.expanduser().resolve()
    if input_path.is_dir():
        images = collect_images(input_path)
        if not images:
            fail(f"no images ({', '.join(sorted(IMAGE_EXTS))}) found in {input_path}")
        return images, input_path.with_name(input_path.name + "_translated")
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTS:
            fail(f"input is not a supported image ({', '.join(sorted(IMAGE_EXTS))}): {input_path}")
        return [input_path], input_path.parent / (input_path.stem + "_translated")
    fail(f"input not found (pass a folder of images or a single image file): {input_path}")


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
# Several upstream behaviours break that out of the box, so we patch the user's BT
# checkout idempotently (on first run, or via --patch-bt) to make a fresh install
# "just work". Patches auto-skip files that a given BT version doesn't ship, so
# both the older `trans_chatgpt.py` and the current `trans_llm.py` are covered:
#   1. The LLM translator sends both `temperature` and `top_p`. Anthropic's
#      OpenAI-compatible endpoint rejects that combination, and Opus models reject
#      both -> the API errors out and you get blank translations.
#   2. The same translator sends `response_format={"type":"json_object"}`, which
#      Anthropic rejects; it only accepts the `json_schema` form, and that schema
#      must set `additionalProperties: false` on every object (strict mode).
#   3. mainwindow.py blocks on input() at the end of a headless batch, so the run
#      never exits; and a piped "exit" can carry a UTF-8 BOM that hides it.
# All edits are minimal and being contributed upstream. Revert any time with:
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
        "name": "trans_llm.py: don't send temperature+top_p to Anthropic",
        "relpath": "ballontranslator/modules/translators/trans_llm.py",
        "marker": "omit temperature entirely for Opus",
        "old": (
            "        api_args = {\n"
            "            \"model\": model,\n"
            "            \"messages\": messages,\n"
            "            \"temperature\": float(profile.temperature),\n"
            "            \"top_p\": float(profile.top_p),\n"
            "        }\n"
        ),
        "new": (
            "        api_args = {\n"
            "            \"model\": model,\n"
            "            \"messages\": messages,\n"
            "        }\n"
            "        # Anthropic rejects temperature+top_p together; send temperature only.\n"
            "        # Opus models additionally reject a non-default temperature (\"temperature is\n"
            "        # deprecated for this model\"), so omit temperature entirely for Opus.\n"
            "        if 'opus' not in model.lower():\n"
            "            api_args[\"temperature\"] = float(profile.temperature)\n"
        ),
    },
    {
        "name": "trans_llm.py: always request the json_schema response_format",
        "relpath": "ballontranslator/modules/translators/trans_llm.py",
        "marker": "response_format.type == \"json_schema\" (it rejects",
        "old": (
            "        if profile.json_schema_response_format:\n"
            "            api_args[\"response_format\"] = {\n"
            "                \"type\": \"json_schema\",\n"
            "                \"json_schema\": {\n"
            "                    \"name\": \"translation_response\",\n"
            "                    \"strict\": True,\n"
            "                    \"schema\": self._json_schema(),\n"
            "                },\n"
            "            }\n"
            "        else:\n"
            "            api_args[\"response_format\"] = {\"type\": \"json_object\"}\n"
        ),
        "new": (
            "        # Anthropic's OpenAI-compatible endpoint only accepts\n"
            "        # response_format.type == \"json_schema\" (it rejects \"json_object\").\n"
            "        api_args[\"response_format\"] = {\n"
            "            \"type\": \"json_schema\",\n"
            "            \"json_schema\": {\n"
            "                \"name\": \"translation_response\",\n"
            "                \"strict\": True,\n"
            "                \"schema\": self._json_schema(),\n"
            "            },\n"
            "        }\n"
        ),
    },
    {
        "name": "trans_llm.py: additionalProperties:false for strict json_schema",
        "relpath": "ballontranslator/modules/translators/trans_llm.py",
        "marker": "\"additionalProperties\": False",
        "old": (
            "                        \"required\": [\"id\", \"translation\"],\n"
            "                    },\n"
            "                }\n"
            "            },\n"
            "            \"required\": [\"translations\"],\n"
            "        }\n"
        ),
        "new": (
            "                        \"required\": [\"id\", \"translation\"],\n"
            "                        \"additionalProperties\": False,\n"
            "                    },\n"
            "                }\n"
            "            },\n"
            "            \"required\": [\"translations\"],\n"
            "            \"additionalProperties\": False,\n"
            "        }\n"
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
            # Different BallonsTranslator versions ship different translator files
            # (e.g. trans_chatgpt.py vs trans_llm.py); a missing target just means
            # this particular patch doesn't apply to this version — skip quietly.
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


def run_translation(bt_dir: Path, py: Path, images: list[Path], out_dir: Path,
                    settings: dict, api_key: str, keep_intermediate: bool):
    """Core pipeline. Returns (returncode, human summary). Progress goes through log()."""
    # Make sure the user's BallonsTranslator has our headless/Anthropic patches.
    applied, _already, _problems = ensure_bt_patched(bt_dir)
    if applied:
        log(f"applied {len(applied)} BallonsTranslator compatibility patch(es) (one-time setup).")

    ts = settings["typeset"]
    log(f"found {len(images)} image(s); source={settings['source']}, ocr={settings['ocr']}, "
        f"font={ts['font_family']}, model={settings['model']}")

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

    if not results:
        log(f"BallonsTranslator exited with code {rc} after {dt:.0f}s; results found: 0")
        log("scratch kept for inspection (cleanup skipped). Last log lines:")
        log(tail(run_log))
        log(f"scratch: {work}")
        return 1, f"실패 (exit {rc}). 로그 위치: {work}"

    # BallonsTranslator can crash on shutdown on Windows (exit code 0xC0000409)
    # AFTER the pages are fully rendered. If the result images exist, the run
    # succeeded; treat a non-zero exit as a benign shutdown quirk and continue.
    if rc != 0:
        log(f"note: BallonsTranslator exited with code {rc} after {dt:.0f}s, but "
            f"{len(results)} result(s) were produced (benign shutdown crash); continuing.")

    out_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        shutil.copy2(r, out_dir / r.name)
    log(f"translated {len(results)} page(s) in {dt:.0f}s -> {out_dir}")

    # Privacy: leave only the finished images.
    if keep_intermediate:
        log(f"--keep-intermediate set; scratch left at {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        n_logs = wipe_new_logs(bt_logs_dir, logs_before)
        log("wiped traces: scratch project, masks, inpainted layers, scratch config"
            + (f", {n_logs} run log(s)" if n_logs else "")
            + " - kept only output images.")

    log("done.")
    return 0, f"완료: {len(results)}장 번역 → {out_dir}  ({dt:.0f}s)"


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui(settings: dict) -> int:
    """Small tkinter window: choose folder, output, model and language, then translate.

    Standard-library only (tkinter ships with CPython on Windows). The translation
    runs on a worker thread so the window stays responsive and streams progress.
    """
    try:
        import queue
        import threading
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception as e:
        log(f"GUI unavailable ({e}); run from the command line instead, e.g. "
            f'python iwannaseemanga.py "path\\to\\folder"')
        return 1

    root = tk.Tk()
    root.title("IwannaseeManga")
    root.minsize(680, 460)
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(0, weight=1)

    ttk.Label(outer, text="IwannaseeManga", font=("Segoe UI", 16, "bold")).grid(
        row=0, column=0, sticky="w")
    ttk.Label(outer, text="만화/이미지 폴더를 골라 한국어로 번역합니다.",
              foreground="#666").grid(row=1, column=0, sticky="w", pady=(0, 10))

    body = ttk.Frame(outer)
    body.grid(row=2, column=0, sticky="nsew")
    body.columnconfigure(0, weight=3)   # left: folder (center/main)
    body.columnconfigure(1, weight=2)   # right: options

    input_var = tk.StringVar()
    output_var = tk.StringVar()

    # --- Left: folder to translate (the main pick) ---
    left = ttk.LabelFrame(body, text="번역할 폴더", padding=12)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    left.columnconfigure(0, weight=1)

    input_entry = ttk.Entry(left, textvariable=input_var)
    input_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))

    def browse_input():
        d = filedialog.askdirectory(title="번역할 이미지 폴더 선택")
        if d:
            input_var.set(d)
            if not output_var.get().strip():
                output_var.set(str(Path(d).with_name(Path(d).name + "_translated")))

    ttk.Button(left, text="폴더 찾아보기…", command=browse_input).grid(row=1, column=0, sticky="ew")
    ttk.Label(left, text="jpg · png · webp 등\n이미지가 든 폴더를 고르세요",
              foreground="#888").grid(row=2, column=0, sticky="w", pady=(8, 0))

    # --- Right: language, model, save location ---
    right = ttk.Frame(body)
    right.grid(row=0, column=1, sticky="nsew")
    right.columnconfigure(0, weight=1)

    ttk.Label(right, text="언어").grid(row=0, column=0, sticky="w")
    lang_labels = [lbl for lbl, _ in LANGUAGE_CHOICES]
    lang_keys = [key for _, key in LANGUAGE_CHOICES]
    default_lang = normalize_language(settings.get("language")) or "Japanese"
    lang_combo = ttk.Combobox(right, values=lang_labels, state="readonly")
    lang_combo.current(lang_keys.index(default_lang) if default_lang in lang_keys else 0)
    lang_combo.grid(row=1, column=0, sticky="ew", pady=(2, 10))

    ttk.Label(right, text="번역 모델").grid(row=2, column=0, sticky="w")
    model_labels = [lbl for lbl, _ in MODEL_CHOICES]
    model_ids = [mid for _, mid in MODEL_CHOICES]
    default_model = settings.get("model") or model_ids[0]
    model_combo = ttk.Combobox(right, values=model_labels, state="readonly")
    model_combo.current(model_ids.index(default_model) if default_model in model_ids else 0)
    model_combo.grid(row=3, column=0, sticky="ew", pady=(2, 10))

    ttk.Label(right, text="저장 위치").grid(row=4, column=0, sticky="w")
    output_entry = ttk.Entry(right, textvariable=output_var)
    output_entry.grid(row=5, column=0, sticky="ew", pady=(2, 2))

    def browse_output():
        d = filedialog.askdirectory(title="번역 결과를 저장할 폴더 선택")
        if d:
            output_var.set(d)

    ttk.Button(right, text="저장 폴더 찾아보기…", command=browse_output).grid(
        row=6, column=0, sticky="ew")
    ttk.Label(right, text="비우면 <폴더>_translated 에 저장",
              foreground="#888").grid(row=7, column=0, sticky="w", pady=(6, 0))

    # --- Start button + status log ---
    start_btn = ttk.Button(outer, text="번역 시작")
    start_btn.grid(row=3, column=0, sticky="ew", pady=(14, 8), ipady=4)

    log_frame = ttk.LabelFrame(outer, text="진행 상황", padding=6)
    log_frame.grid(row=4, column=0, sticky="nsew")
    outer.rowconfigure(4, weight=1)
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)
    log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled",
                       background="#111", foreground="#ddd", font=("Consolas", 9))
    log_text.grid(row=0, column=0, sticky="nsew")
    scroll = ttk.Scrollbar(log_frame, command=log_text.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    log_text["yscrollcommand"] = scroll.set

    q: "queue.Queue" = queue.Queue()

    def append_log(msg: str):
        log_text.configure(state="normal")
        log_text.insert("end", msg + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")

    def worker(input_path: Path, out_dir_arg, job: dict, keep: bool):
        global _LOG_SINK
        _LOG_SINK = lambda m: q.put(m)
        try:
            images, default_out = resolve_images(input_path)
            target_out = out_dir_arg or default_out
            q.put("BallonsTranslator 찾는 중…")
            bt_dir = find_bt_dir(None)
            py = bt_python(bt_dir)
            api_key = resolve_api_key(None, bt_dir)
            if not api_key:
                raise IwsmError("Anthropic API 키가 없습니다. config.local.json 에 넣거나 "
                                "ANTHROPIC_API_KEY 환경변수를 설정하세요.")
            rc, msg = run_translation(bt_dir, py, images, Path(target_out), job, api_key, keep)
            q.put(("__DONE__", rc, msg))
        except IwsmError as e:
            q.put(("__DONE__", 1, str(e)))
        except Exception as e:  # surface anything to the user, don't crash the GUI
            q.put(("__DONE__", 1, f"예상치 못한 오류: {e}"))
        finally:
            _LOG_SINK = None

    def on_start():
        inp = input_var.get().strip()
        if not inp:
            messagebox.showwarning("IwannaseeManga", "번역할 폴더를 먼저 선택하세요.")
            return
        lang_key = lang_keys[lang_combo.current()]
        model_id = model_ids[model_combo.current()]
        li = LANGUAGES[lang_key]
        job = json.loads(json.dumps(settings))          # deep copy of base settings
        job["model"] = model_id
        job["source"] = li["source"]
        job["ocr"] = li["ocr"]
        job["target"] = settings.get("target") or "한국어"
        if job.get("style"):                            # honour a preset if set in settings.json
            job["typeset"] = deep_merge(job["typeset"], STYLE_PRESETS.get(job["style"], {}))
        out = output_var.get().strip()
        start_btn.configure(state="disabled", text="번역 중…")
        append_log(f"── 시작: {inp}  ({lang_combo.get()}, {model_combo.get()})")
        threading.Thread(
            target=worker,
            args=(Path(inp), Path(out) if out else None, job, False),
            daemon=True,
        ).start()

    start_btn.configure(command=on_start)

    def poll():
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__DONE__":
                    _, rc, msg = item
                    append_log(("✅ " if rc == 0 else "❌ ") + msg)
                    start_btn.configure(state="normal", text="번역 시작")
                    (messagebox.showinfo if rc == 0 else messagebox.showerror)("IwannaseeManga", msg)
                else:
                    append_log(str(item))
        except queue.Empty:
            pass
        root.after(120, poll)

    root.after(120, poll)
    root.mainloop()
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv=None) -> int:
    settings = load_settings()
    ts_def, cl_def = settings["typeset"], settings["cleanup"]

    ap = argparse.ArgumentParser(
        prog="iwannaseemanga",
        description="One-command comic/manga translation into Korean (Japanese or English source; "
                    "BallonsTranslator wrapper). Run with no input to open the window. "
                    "Keeps only the finished images; wipes all intermediate traces.",
    )
    ap.add_argument("input", nargs="?", help="folder of comic/manga images, or a single image file "
                                             "(omit to open the graphical window)")
    ap.add_argument("-o", "--output", help="output folder (default: <input>_translated)")
    ap.add_argument("--model", default=settings["model"], help="Claude model id")
    ap.add_argument("--language", "--lang", dest="language", default=None,
                    help="source language: Japanese or English (picks the OCR engine)")
    ap.add_argument("--source", default=None, help="override source language (BallonsTranslator name)")
    ap.add_argument("--target", default=None, help="target language (BallonsTranslator name)")
    ap.add_argument("--ocr", default=None, help="override OCR engine (e.g. manga_ocr, mit48px_ctc, mit48px)")
    ap.add_argument("--style", choices=sorted(STYLE_PRESETS), default=settings.get("style"),
                    help="look preset (sets font etc.)")
    ap.add_argument("--font", help="font family (overrides style/settings)")
    ap.add_argument("--font-size", type=int, help="base font size")
    ap.add_argument("--no-auto-fit", action="store_true", help="use a fixed font size (no shrink-to-fit)")
    ap.add_argument("--stroke", type=float, help="outline width (0 = none)")
    ap.add_argument("--inpaint-size", type=int, help="erase resolution (higher = cleaner, slower)")
    ap.add_argument("--mask-dilate", type=int, help="grow erase mask (raise to remove ghosting)")
    ap.add_argument("--bt-dir", default=None, help="path to BallonsTranslator (auto-detected if omitted)")
    ap.add_argument("--api-key", default=None, help="Anthropic API key (else env/config/BT fallback)")
    ap.add_argument("--keep-intermediate", action="store_true", help="do NOT wipe scratch/logs (debug)")
    ap.add_argument("--gui", action="store_true", help="force the graphical window even if an input is given")
    ap.add_argument("--no-gui", action="store_true", help="never open the window (CLI only)")
    ap.add_argument("--setup-fonts", action="store_true", help="download the recommended free fonts, then exit")
    ap.add_argument("--list-fonts", action="store_true", help="list installed fonts + presets, then exit")
    ap.add_argument("--patch-bt", action="store_true",
                    help="apply BallonsTranslator compatibility patches, then exit (also done automatically on first run)")
    args = ap.parse_args(argv)

    if args.patch_bt:
        applied, already, problems = ensure_bt_patched(find_bt_dir(args.bt_dir), verbose=True)
        if not applied and not already:
            return 1  # nothing patched and nothing already in place (warnings printed)
        log("BallonsTranslator already up to date." if not applied
            else f"done: applied {len(applied)} patch(es).")
        return 0 if not problems else 1
    if args.setup_fonts:
        return setup_fonts(find_bt_dir(args.bt_dir))
    if args.list_fonts:
        return list_fonts(find_bt_dir(args.bt_dir))

    # No input given (e.g. double-clicked run.bat) → open the window, unless suppressed.
    if args.gui or (args.input is None and not args.no_gui):
        return run_gui(settings)
    if args.input is None:
        ap.error("input is required (or omit it to open the window, or use --setup-fonts / --list-fonts)")

    # Merge precedence: settings -> --style preset -> individual CLI flags.
    if args.style:
        settings["typeset"] = deep_merge(ts_def, STYLE_PRESETS[args.style])
    settings["model"] = args.model
    settings["source"], settings["ocr"] = resolve_language(settings, args.language, args.source, args.ocr)
    settings["target"] = args.target or settings.get("target") or "한국어"
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

    images, default_out = resolve_images(Path(args.input))
    out_dir = Path(args.output).expanduser().resolve() if args.output else default_out

    bt_dir = find_bt_dir(args.bt_dir)
    py = bt_python(bt_dir)
    api_key = resolve_api_key(args.api_key, bt_dir)
    if not api_key:
        fail("no Anthropic API key. Use --api-key, set ANTHROPIC_API_KEY, or add config.local.json.")

    rc, _summary = run_translation(bt_dir, py, images, out_dir, settings, api_key, args.keep_intermediate)
    return rc


def main(argv=None) -> int:
    # Console may be cp949/cp1252; force UTF-8 so Korean paths, emoji, dashes never crash a print.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        return _main(argv)
    except IwsmError as e:
        print(f"[IwannaseeManga] ERROR: {e}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
