# IwannaseeManga

**One command in, translated manga out.** Point it at a folder of Japanese manga
images and get a folder of Korean ones back — font, sizing, outline, and erased
original text all handled from one place. Then it wipes every intermediate trace,
leaving **only the finished images**.

IwannaseeManga is a thin automation layer around
[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator), which does the
heavy lifting (text detection, OCR, inpainting, typesetting). The translation
itself runs through the **Claude API** (Anthropic's OpenAI-compatible endpoint).

> **한국어 — 한 번의 명령으로 만화 번역 완료.** 일본어 만화 이미지가 든 폴더를
> 가리키면 한국어로 번역된 폴더가 나옵니다 — 폰트, 크기, 외곽선, 원본 글자 지우기까지
> 한곳에서 처리합니다. 그리고 모든 중간 흔적을 지우고 **완성된 이미지만** 남깁니다.
>
> IwannaseeManga는 [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)를
> 감싸는 얇은 자동화 레이어입니다. 무거운 작업(텍스트 감지, OCR, 인페인팅, 식자)은
> BallonsTranslator가 담당하고, 번역 자체는 **Claude API**(Anthropic의 OpenAI 호환
> 엔드포인트)를 통해 실행됩니다.

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

> **한국어 — 왜 만들었나.** 온라인 페이지 단위 만화 번역기는 이미지당 요금을 받고
> 사용자의 데이터를 보관합니다. 이 도구는 파이프라인을 로컬에서 실행하고(번역 텍스트만
> Claude로 전송), 폴더 전체를 한 번에 일괄 처리하며, 식자(레터링)를 단일
> `settings.json`에서 제어하게 해줍니다. 그리고 설계상 **출력 이미지를 제외한 어떤
> 로컬 흔적도 남기지 않습니다**: OCR로 추출한 원문, 번역문, 말풍선 좌표가 담긴 프로젝트
> 파일과 마스크, 인페인트 레이어, 실행 로그는 내보내기 후 모두 삭제됩니다.

## Privacy & data

The pipeline runs locally and your **images never leave your machine** — detection,
OCR, inpainting, and typesetting are all done on your computer. Two things are worth
knowing before you use it:

- **Dialogue text is sent to Anthropic.** To translate, the OCR'd source text (the
  lines read out of each bubble) and the translation prompt are sent over HTTPS to
  the Claude API (`api.anthropic.com`). Commercial API inputs are **not used to train
  models**, but they may be retained for a limited period under Anthropic's policies;
  see [Anthropic's terms and privacy policy](https://www.anthropic.com/legal) for the
  current details. If you cannot send text off-machine, do not use this tool.
- **A failed run leaves temporary files behind.** On success, every intermediate
  trace is wiped automatically. But if a run **errors out**, the scratch workspace is
  kept on purpose for inspection at `%LOCALAPPDATA%\IwannaseeManga\` (or your temp
  directory) — and it contains your **API key in plain text** (`runtime_config.json`)
  and the **OCR'd source text** (run logs). Delete that folder once you're done
  debugging, or re-run successfully to have it cleaned up.

> **한국어 — 개인정보 및 데이터.** 파이프라인은 로컬에서 실행되며 **이미지는 절대
> 사용자의 컴퓨터를 벗어나지 않습니다** — 감지, OCR, 인페인팅, 식자가 모두 본인
> 컴퓨터에서 처리됩니다. 사용 전에 알아둘 두 가지가 있습니다:
>
> - **대사 텍스트는 Anthropic으로 전송됩니다.** 번역을 위해 OCR로 추출한 원문(각
>   말풍선에서 읽어낸 대사)과 번역 프롬프트가 HTTPS를 통해 Claude API
>   (`api.anthropic.com`)로 전송됩니다. 상용 API 입력은 **모델 학습에 사용되지
>   않지만**, Anthropic의 정책에 따라 일정 기간 보관될 수 있습니다. 최신 내용은
>   [Anthropic 약관 및 개인정보처리방침](https://www.anthropic.com/legal)을
>   확인하세요. 텍스트를 외부로 전송할 수 없는 상황이라면 이 도구를 사용하지 마세요.
> - **번역에 실패하면 임시 파일이 남습니다.** 성공 시에는 모든 중간 흔적이 자동으로
>   삭제됩니다. 하지만 실행이 **오류로 종료되면** 검사를 위해 스크래치 작업 폴더가
>   `%LOCALAPPDATA%\IwannaseeManga\`(또는 임시 디렉터리)에 의도적으로 남으며, 그
>   안에는 **평문 API 키**(`runtime_config.json`)와 **OCR로 추출한 원문**(실행
>   로그)이 들어 있습니다. 디버깅이 끝나면 해당 폴더를 삭제하거나, 정상적으로
>   다시 실행하면 자동으로 정리됩니다.

## Requirements

- **BallonsTranslator**, installed with its virtual environment (this tool calls its `venv` interpreter).
- **Python 3.8+** to run this wrapper (any interpreter; standard library only).
- An **Anthropic API key**.

> **한국어 — 요구 사항.**
> - **BallonsTranslator** — 가상 환경과 함께 설치되어 있어야 합니다(이 도구가 그
>   `venv` 인터프리터를 호출합니다).
> - 이 래퍼를 실행할 **Python 3.8 이상**(아무 인터프리터나 가능; 표준 라이브러리만 사용).
> - **Anthropic API 키**.

> **BallonsTranslator compatibility patches — applied automatically.** Two upstream
> behaviours break headless use through Anthropic, so IwannaseeManga patches your
> BallonsTranslator checkout for you:
> 1. its `ChatGPT` translator sends both `temperature` and `top_p` — Anthropic's
>    endpoint rejects that combination, and Opus models reject both, so you get
>    **blank translations**; and
> 2. its headless loop blocks on `input()` at the end of a batch, so **the run never
>    exits** (a piped `exit` can even carry a UTF-8 BOM that hides it).
>
> The patches are applied automatically the first time you translate — or run
> `python iwannaseemanga.py --patch-bt` to apply them explicitly. They are minimal,
> idempotent, and being contributed upstream; revert any time with
> `git -C <BallonsTranslator> checkout -- <file>`.

> **한국어 — BallonsTranslator 호환성 패치(자동 적용).** 두 가지 업스트림 동작이
> Anthropic을 통한 헤드리스 사용을 막기 때문에, IwannaseeManga가 사용자의
> BallonsTranslator 체크아웃을 대신 패치합니다:
> 1. `ChatGPT` 번역기가 `temperature`와 `top_p`를 함께 보냅니다 — Anthropic
>    엔드포인트는 이 조합을 거부하고, Opus 모델은 둘 다 거부하므로 **번역 결과가
>    비게** 됩니다.
> 2. 헤드리스 루프가 배치 종료 시 `input()`에서 멈춰 **실행이 끝나지 않습니다**(파이프로
>    넣은 `exit`에 UTF-8 BOM이 섞여 인식되지 않을 수도 있음).
>
> 이 패치들은 처음 번역할 때 자동으로 적용됩니다 — 또는
> `python iwannaseemanga.py --patch-bt`로 명시적으로 적용할 수 있습니다. 최소한의
> 변경이며 멱등(idempotent)하고 업스트림에 기여 중입니다.
> `git -C <BallonsTranslator> checkout -- <file>`로 언제든 되돌릴 수 있습니다.

## Setup

```sh
git clone https://github.com/Dopamineliminated/IwannaseeManga.git
cd IwannaseeManga

# copy the example, then paste your Anthropic key into config.local.json:
cp config.local.json.example config.local.json    # Windows: copy config.local.json.example config.local.json

python iwannaseemanga.py --setup-fonts             # download the recommended free Korean fonts
python iwannaseemanga.py --patch-bt                # make BallonsTranslator work headlessly with Anthropic
```

The `--patch-bt` step is also run automatically the first time you translate, so it's
safe to skip — it's listed here just so the behaviour is explicit.

If BallonsTranslator is **not** at `~/BallonsTranslator`, set `IWSM_BT_DIR` to its
path (or pass `--bt-dir`). API key can also come from `ANTHROPIC_API_KEY` or the
key already stored in BallonsTranslator.

> **한국어 — 설정.** 위 명령으로 저장소를 클론하고, 예제 파일을 복사한 뒤
> `config.local.json`에 Anthropic 키를 붙여넣고, 권장 한국어 폰트를 받고,
> BallonsTranslator를 패치합니다.
>
> `--patch-bt` 단계는 처음 번역할 때 자동으로도 실행되므로 건너뛰어도 됩니다 — 동작을
> 명시적으로 보여주려 적어둔 것뿐입니다.
>
> BallonsTranslator가 `~/BallonsTranslator`에 **없다면** `IWSM_BT_DIR` 환경변수에 그
> 경로를 설정하세요(또는 `--bt-dir` 전달). API 키는 `ANTHROPIC_API_KEY` 환경변수나
> BallonsTranslator에 이미 저장된 키에서 가져올 수도 있습니다.

## Usage

```sh
python iwannaseemanga.py "path/to/chapter"                 # → path/to/chapter_translated
python iwannaseemanga.py "chapter01" -o "chapter01_KO"
python iwannaseemanga.py "chapter01" --style impact        # bold action lettering
python iwannaseemanga.py "chapter01" --font "Gaegu" --stroke 2 --model claude-opus-4-8
```

On Windows you can also drag a folder onto **`run.bat`**.

> **한국어 — 사용법.** 위처럼 폴더 경로를 넘기면 됩니다(기본 출력은
> `<입력>_translated`). `-o`로 출력 폴더, `--style`로 룩 프리셋, `--font`/`--stroke`/
> `--model` 등으로 세부 설정을 지정할 수 있습니다. Windows에서는 폴더를 **`run.bat`**
> 위로 드래그해도 됩니다.

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
| `--patch-bt` | — | apply the BallonsTranslator compatibility patches, then exit (auto-applied on first run) |
| `--bt-dir` / `--api-key` | env / fallback | BallonsTranslator path / Anthropic key |
| `--keep-intermediate` | off | keep scratch & logs (debugging) |

> **한국어 — 옵션 설명.**
> - `input` — 만화 이미지가 든 폴더
> - `-o, --output` — 출력 폴더 (기본값 `<입력>_translated`)
> - `--style` — 룩 프리셋: `comic`, `impact`, `handwriting`, `clean`
> - `--font` — 폰트 패밀리 (설치되어 있어야 함; `--setup-fonts` 참고)
> - `--font-size` — 기본 글자 크기
> - `--no-auto-fit` — 자동 맞춤 대신 고정 크기 사용
> - `--stroke` — 외곽선 두께 (그림 위 텍스트에 유용)
> - `--inpaint-size` — 지우기 해상도 (높을수록 깨끗·느림)
> - `--mask-dilate` — 지우기 마스크 확장 (잔상 제거 시 값을 올림)
> - `--model` — `claude-opus-4-8` 최고 품질, `claude-haiku-4-5` 최저 비용
> - `--source`/`--target` — 언어 (BallonsTranslator 명칭)
> - `--setup-fonts` — 권장 무료 폰트 다운로드 후 종료
> - `--list-fonts` — 설치된 폰트 + 프리셋 목록 출력 후 종료
> - `--patch-bt` — BallonsTranslator 호환성 패치 적용 후 종료 (첫 실행 시 자동 적용)
> - `--bt-dir` / `--api-key` — BallonsTranslator 경로 / Anthropic 키
> - `--keep-intermediate` — 스크래치 및 로그 보존 (디버깅용)

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

> **한국어 — 후처리는 `settings.json`에서 한 번만 설정.** 레터링과 지우기에 관한 모든
> 것은 스크립트 옆의 **`settings.json`**에 들어 있습니다. 한 번 설정하면 매 실행
> (`run.bat` 더블클릭 한 번)마다 적용되며, CLI 플래그와 `--style`이 실행별로 이를
> 덮어씁니다. 위 값들은 BallonsTranslator의 `global_fontformat` + `let_*` 플래그 +
> 인페인터/디텍터 파라미터로 매핑되므로, 룩을 바꾸려고 BallonsTranslator를 열 필요가
> 없습니다. 폰트는 시리즈별로 다르게 — `font_family`를 바꾸거나 `--style`을 전달하면
> 됩니다.
>
> 출력 품질은 입력만큼만 선명합니다: 저해상도 원본 스캔은 텍스트 선명도를 제한합니다.

## License & credits

GPLv3 — see [LICENSE](LICENSE). IwannaseeManga is a separate program that invokes
**[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)** (GPLv3) as its
engine; all credit for the detection/OCR/inpainting/typesetting pipeline goes there.
Translation by [Claude](https://www.anthropic.com/) (Anthropic API). Recommended
fonts are free/OFL (Google Fonts, Pretendard).

> **한국어 — 라이선스 및 크레딧.** GPLv3 — [LICENSE](LICENSE) 참고. IwannaseeManga는
> 엔진으로 **[BallonsTranslator](https://github.com/dmMaze/BallonsTranslator)**(GPLv3)를
> 호출하는 별도의 프로그램이며, 감지/OCR/인페인팅/식자 파이프라인의 모든 공로는
> BallonsTranslator에 있습니다. 번역은 [Claude](https://www.anthropic.com/)(Anthropic
> API)가 담당합니다. 권장 폰트는 무료/OFL(Google Fonts, Pretendard)입니다.
