# IwannaseeManga

**One command in, translated manga out.** Point it at a folder of Japanese manga
images and get a folder of Korean ones back — font, sizing, outline, and erased
original text all handled from one place. Then it wipes every intermediate trace,
leaving **only the finished images**.

IwannaseeManga is a thin automation layer around
[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator), which does the
heavy lifting (text detection, OCR, inpainting, typesetting). The translation
itself runs through the **Claude API** (Anthropic's OpenAI-compatible endpoint).

```
[ input folder ]
      │   jpg / png / webp …
      ▼
IwannaseeManga ──► copy to a private scratch project (outside any cloud folder)
      │            build a runtime config (translation + all post-processing options)
      │            run BallonsTranslator --headless  (detect → OCR → translate → inpaint → typeset)
      │            collect rendered pages
      ▼            wipe scratch project, masks, inpainted layers, run logs, scratch config
[ output folder ]  ◄── only the finished images remain
```

## Why

Online per-page manga translators charge per image and keep your data. This runs
the pipeline locally (only the translation text goes to Claude), batches a whole
folder in one go, lets you control the lettering from a single `settings.json`,
and — by design — **leaves no local trace except the output images**: the project
file holding OCR'd source text, translations, and bubble coordinates, plus masks,
inpainted layers, and run logs, are all deleted after export.

## Requirements

- **BallonsTranslator**, installed with its virtual environment (this tool calls its `venv` interpreter).
- **Python 3.8+** to run this wrapper (any interpreter; standard library only).
- An **Anthropic API key**.

> If you hit blank translations, BallonsTranslator's `ChatGPT` translator is
> sending both `temperature` and `top_p`, which Anthropic rejects. Patch
> `ballontranslator/modules/translators/trans_chatgpt.py` to send at most
> `temperature` (and neither for Opus models). Being contributed upstream.

## Setup

```sh
git clone https://github.com/Dopamineliminated/IwannaseeManga.git
cd IwannaseeManga
cp config.local.json.example config.local.json   # then paste your Anthropic key
python iwannaseemanga.py --setup-fonts            # download the recommended free Korean fonts
```

If BallonsTranslator is **not** at `~/BallonsTranslator`, set `IWSM_BT_DIR` to its
path (or pass `--bt-dir`). API key can also come from `ANTHROPIC_API_KEY` or the
key already stored in BallonsTranslator.

## Usage

```sh
python iwannaseemanga.py "path/to/chapter"                 # → path/to/chapter_translated
python iwannaseemanga.py "chapter01" -o "chapter01_KO"
python iwannaseemanga.py "chapter01" --style impact        # bold action lettering
python iwannaseemanga.py "chapter01" --font "Gaegu" --stroke 2 --model claude-opus-4-8
```

On Windows you can also drag a folder onto **`run.bat`**.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `input` | — | folder of manga images |
| `-o, --output` | `<input>_translated` | output folder |
| `--style` | — | look preset: `comic`, `impact`, `handwriting`, `clean` |
| `--font` | `Jua` | font family (must be installed; see `--setup-fonts`) |
| `--font-size` | `24` | base font size |
| `--no-auto-fit` | off | fixed size instead of shrink-to-fit |
| `--stroke` | `0` | outline width (good for text over art) |
| `--inpaint-size` | `1536` | erase resolution (higher = cleaner, slower) |
| `--mask-dilate` | `2` | grow erase mask (raise to remove ghosting) |
| `--model` | `claude-sonnet-4-6` | `claude-opus-4-8` best, `claude-haiku-4-5` cheapest |
| `--source`/`--target` | `日本語`/`한국어` | languages (BallonsTranslator names) |
| `--setup-fonts` | — | download the recommended free fonts, then exit |
| `--list-fonts` | — | list installed fonts + presets, then exit |
| `--bt-dir` / `--api-key` | env / fallback | BallonsTranslator path / Anthropic key |
| `--keep-intermediate` | off | keep scratch & logs (debugging) |

## Post-processing — set once in `settings.json`

Everything about the lettering and erasure lives in **`settings.json`** next to the
script. Set it once and every run (one double-click of `run.bat`) applies it; CLI
flags and `--style` override it per run.

```jsonc
{
  "model": "claude-sonnet-4-6",
  "source": "日本語", "target": "한국어",
  "typeset": {
    "font_family": "Jua",       // any installed font
    "font_size": 24,
    "auto_fit": true,           // shrink text to fit each bubble
    "bold": false,
    "line_spacing": 1.2,
    "letter_spacing": 1.0,
    "stroke_width": 0.0,        // >0 = outline (stroke_color)
    "stroke_color": [255,255,255],
    "text_color": null,         // null = auto-detect (handles black & white text); [r,g,b] = force
    "alignment": "auto"         // auto | left | center | right
  },
  "cleanup": {
    "inpaint_size": 1536,       // erase quality
    "mask_dilate": 2            // raise if original text leaves ghosting
  }
}
```

These map onto BallonsTranslator's `global_fontformat` + `let_*` flags + inpainter
/ detector params, so you never have to open BallonsTranslator to change the look.
Font choice can be per-series — swap `font_family` or pass `--style`.

> The output is only as sharp as the input: low-resolution source scans cap text crispness.

## License & credits

GPLv3 — see [LICENSE](LICENSE). IwannaseeManga is a separate program that invokes
**[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)** (GPLv3) as its
engine; all credit for the detection/OCR/inpainting/typesetting pipeline goes there.
Translation by [Claude](https://www.anthropic.com/) (Anthropic API). Recommended
fonts are free/OFL (Google Fonts, Pretendard).
