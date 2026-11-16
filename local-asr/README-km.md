# បកសំឡេងក្នុងម៉ាស៊ីនខ្លួនឯង (Local ASR) ជំនួស Gemini Transcript

## ចម្លើយខ្លី

**បាន — តែមិនមែនក្នុង app ផ្ទាល់ទេ។** `app.js` របស់ dinmagicdubbing ជា
encrypted bundle កែមិនបាន ដូច្នេះបន្ថែម local ASR ចូល app មិនកើត។
វិធីដែលធ្វើបានគឺ **2 ជំហាន**៖

```
វីដេអូ → [Local ASR ក្នុងកុំព្យូទ័រ] → .srt (ភាសាដើម, ដូចជាចិន)
        → បញ្ចូល .srt ចូល app (ផ្ទាំង Subtitles) → Translate Only
        → Gemini បកប្រែជាខ្មែរ → Export
```

មានន័យថា local ASR **ជំនួសតែជំហាន transcribe** ប៉ុណ្ណោះ។
ការបកប្រែជាខ្មែរនៅតែប្រើ Gemini ក្នុង app ដដែល (ត្រូវការ Gemini key)។

## ប្រៀបធៀប 3 models

| Model | ចំណុចខ្លាំង | ចំណុចខ្សោយ | សាកសម |
|---|---|---|---|
| **Whisper** (`faster-whisper`, script `transcribe.py`) | ងាយដំឡើងបំផុត, ចិនល្អ, ដំណើរការលើ CPU បាន, មាន timestamps ត្រឹមត្រូវ | `large-v3` យឺតលើ CPU (ប្រើ `medium` បើ CPU ខ្សោយ) | **ជម្រើសដំបូងដែលណែនាំ** |
| **SenseVoice** (`FunASR`, script `transcribe_sensevoice.py`) | លឿនបំផុតលើ CPU, ចិនល្អណាស់ (Alibaba, ធ្វើសម្រាប់ចិន/អង់គ្លេស) | ដំឡើងធ្ងន់ជាងបន្តិច (FunASR + models) | វីដេអូយូរ, ចង់បានលឿន |
| **Qwen3-ASR** (`Qwen/Qwen3-ASR-0.6B`) | ថ្មីបំផុត (2025), ចិនត្រឹមត្រូវណាស់, មាន timestamps, ស្គាល់ភាសា 30+ | ត្រូវការ RAM/GPU ច្រើនជាង (0.6B ប្រហែល 4GB RAM, 1.7B ត្រូវ GPU) | បើមាន GPU ឬចង់បានភាពត្រឹមត្រូវខ្ពស់បំផុត |

## វិធីប្រើ Whisper (ណែនាំ)

```bash
pip install faster-whisper
python3 transcribe.py video.mp4 -l zh
# បើ CPU យឺត៖  python3 transcribe.py video.mp4 -m medium -l zh
```

បាន file `video.srt` (អត្ថបទចិន + timestamps)។

## វិធីប្រើ SenseVoice

```bash
pip install funasr
python3 transcribe_sensevoice.py video.mp4 -l zh
```

## Qwen3-ASR (គ្មាន script ក្នុង folder នេះ — ប្រើ transformers)

```bash
pip install transformers torch
```

```python
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor
import torch
processor = AutoProcessor.from_pretrained("Qwen/Qwen3-ASR-0.6B")
model = AutoModelForSpeechSeq2Seq.from_pretrained(
    "Qwen/Qwen3-ASR-0.6B", dtype=torch.float16, device_map="auto")
# រួច transcribe ជាមួយ return_timestamps=True ហើយសរសេរជា .srt
```

## បញ្ចូល .srt ចូល app

1. បើក https://nakforver.github.io/dinmagicdubbing/
2. ផ្ទាំង **Subtitles** → **Import .srt** → ជ្រើស file `.srt` ដែលបានពី script
3. បន្ទាត់នឹងបង្ហាញក្នុងបញ្ជី → ជ្រើស **Translate Only** → ចុច Dub
4. ពិនិត្យអត្ថបទខ្មែរ រួច Export

## រឿងត្រូវដឹង៖ ភេទ (♂/♀)

Local ASR **មិនដឹងភេទអ្នកនិយាយទេ** (Gemini ទេដែលដាក់ `g: m/f`)។
បន្ទាត់ដែលបញ្ចូលពី .srt នឹង default ទៅ ♂ ទាំងអស់។
មុន Generate Audio សូមចុចប៊ូតុង ♂/♀ លើបន្ទាត់ស្រីៗដើម្បីប្ដូរទៅ ♀
ដោយខ្លួនឯង។ បើចង់បែងចែកអ្នកនិយាយដោយស្វ័យប្រវត្តិ
ត្រូវបន្ថែម speaker diarization (ឧ. `pyannote-audio`) — នោះជា
ជំហានបន្ថែម ប្រាប់ខ្ញុំបើចង់បាន។

## អត្ថប្រយោជន៍នៃ local ASR

- **ឯកជនភាព៖** សំឡេងមិនចេញពីម៉ាស៊ីនអ្នកទេ
- **មិនបង់ថ្លៃ API៖** transcribe ឥតគិតថ្លៃ (មានតែ translate ទេប្រើ Gemini)
- **គ្រប់គ្រងបាន៖** អាចកែ .srt មុនបកប្រែ

## ចំណាំ

- Script ទាំង 2 នេះបានត្រឹម `python3 -m py_compile` ប៉ុណ្ណោះ
  (មិនបានសាក transcribe ពិតក្នុង sandbox នេះទេ ព្រោះត្រូវ download
  model ធំៗ និង GPU)។ បើ run ហើយមាន error ផ្ញើ error មកឱ្យខ្ញុំ។
- ត្រូវការ Python 3.9+ និង `ffmpeg` ក្នុង PATH (សម្រាប់អាន mp4)។
- `transcribe.py` decode សំឡេងដោយ `ffmpeg` ផ្ទាល់ (មិនប្រើ PyAV)
  ដើម្បីចៀសបញ្ហា version របស់ PyAV (`metadata_errors` error ដែលជួប
  ពេលសាកលើ Muse)។
