# IwannaseeManga

**One command in, translated manga out.** Point it at a folder of Japanese manga
images and get a folder of Korean ones back — fonts, sizing, and erased original
text all handled. Then it wipes every intermediate trace, leaving **only the
finished images**.

IwannaseeManga is a thin automation layer around
[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator), which does the
heavy lifting (text detection, OCR, inpainting, typesetting). The translation
itself runs through the **Claude API** (Anthropic's OpenAI-compatible endpoint).

```
[ input folder ]
      │   jpg / png / webp …
      ▼
IwannaseeManga ──► copy to a private scratch project (outside any cloud folder)
      │            run BallonsTranslator --headless  (detect → OCR → translate → inpaint → typeset)
      │            collect rendered pages
      ▼            wipe scratch project, masks, inpainted layers, run logs, scratch config
[ output folder ]  ◄── only the finished images remain
```

## Why

Online per-page manga translators charge per image and keep your data. This runs
the pipeline locally (only the translation text goes to Claude), batches a whole
folder in one go, and — by design — **leaves no local trace except the output
images**: the project file that holds the OCR'd source text, translations, and
bubble coordinates, plus masks, inpainted layers, and run logs, are all deleted
after export.

## Requirements

- **BallonsTranslator**, installed with its virtual environment, somewhere on disk
  (this tool calls its `venv` interpreter). See its repo for setup.
- **Python 3.8+** to run this wrapper (any interpreter; it only uses the standard library).
- An **Anthropic API key**.

> Note: BallonsTranslator's `ChatGPT` translator sends both `temperature` and
> `top_p`, which Anthropic models reject. If you hit blank translations, patch
> `ballontranslator/modules/translators/trans_chatgpt.py` so it sends at most
> `temperature` (and neither for Opus models). This is being contributed upstream.

## Setup

```sh
git clone https://github.com/Dopamineliminated/IwannaseeManga.git
cd IwannaseeManga
cp config.local.json.example config.local.json   # then paste your Anthropic key
# (or set ANTHROPIC_API_KEY, or rely on the key already stored in BallonsTranslator)
```

If BallonsTranslator is **not** at `~/BallonsTranslator`, set `IWSM_BT_DIR` to its path
(or pass `--bt-dir`).

## Usage

```sh
python iwannaseemanga.py "path/to/manga_chapter"
# → writes to path/to/manga_chapter_translated

python iwannaseemanga.py "chapter01" -o "chapter01_KO" --model claude-opus-4-8
```

On Windows you can also drag a folder onto **`run.bat`**.

### Options

| Flag | Default | Meaning |
|---|---|---|
| `input` | — | folder of manga images |
| `-o, --output` | `<input>_translated` | output folder |
| `--model` | `claude-sonnet-4-6` | Claude model (`claude-opus-4-8` best, `claude-haiku-4-5` cheapest) |
| `--source` / `--target` | `日本語` / `한국어` | languages (BallonsTranslator names) |
| `--bt-dir` | `~/BallonsTranslator` or `IWSM_BT_DIR` | BallonsTranslator location |
| `--api-key` | env / config / BT fallback | Anthropic key |
| `--keep-intermediate` | off | keep the scratch project & logs (debugging) |

API-key precedence: `--api-key` → `ANTHROPIC_API_KEY` → `config.local.json` →
the key already saved in BallonsTranslator's config.

## Tuning the look (fonts / size / erasure)

Typesetting and inpainting are BallonsTranslator features. Set your defaults in
BallonsTranslator's config (font family, auto-layout, inpainter) — IwannaseeManga
starts from that config and only overrides OCR, languages, translator, model, URL,
and key. So tune fonts/size/cleanup once in BallonsTranslator and every run inherits it.

## License & credits

GPLv3 — see [LICENSE](LICENSE). IwannaseeManga is a separate program that invokes
**[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)** (GPLv3) as its
engine; all credit for the detection/OCR/inpainting/typesetting pipeline goes there.
Translation by [Claude](https://www.anthropic.com/) (Anthropic API).
