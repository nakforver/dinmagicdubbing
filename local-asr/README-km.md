# បកសំឡេងក្នុងម៉ាស៊ីនខ្លួនឯង (Local ASR) ជំនួស Gemini Transcript

## ចម្លើយខ្លី

**បាន។** `app.js` របស់ dinmagicdubbing ជា encrypted bundle កែមិនបាន
តែ app មានប៊ូតុង transcript ក្នុងផ្ទាំង **Subtitles** ដែលភ្ជាប់ទៅ
local server (`whisper-server.py`) លើកុំព្យូទ័ររបស់អ្នក។
Server នោះរត់បាន **3 engines** — ជ្រើសក្នុង app បាន៖

```
វីដេអូ → [Local ASR ក្នុងកុំព្យូទ័រ: Whisper / SenseVoice / Qwen3-ASR]
        → .srt (ភាសាដើម, ដូចជាចិន)
        → app បំពេញអត្ថបទដោយស្វ័យប្រវត្តិ → Translate Only
        → Gemini បកប្រែជាខ្មែរ → Export
```

មានន័យថា local ASR **ជំនួសតែជំហាន transcribe** ប៉ុណ្ណោះ។
ការបកប្រែជាខ្មែរនៅតែប្រើ Gemini ក្នុង app ដដែល (ត្រូវការ Gemini key)។
សំឡេងមិនដែលផ្ញើទៅ Gemini ទេ ដូច្នេះសន្សំ quota បានច្រើន។

## វិធីប្រើក្នុង app (ងាយបំផុត)

```bash
# ដំឡើង package សម្រាប់ engine ដែលអ្នកចង់ប្រើ (យ៉ាងហោចមួយ)៖
pip install faster-whisper            # Whisper
pip install funasr                    # SenseVoice
pip install "transformers>=5.13.0" torch   # Qwen3-ASR

# ដំណើរការ server (ពី folder ដែលមាន whisper-server.py)៖
python3 whisper-server.py
```

រួចបើក app → ផ្ទាំង **Subtitles** → ជ្រើស engine
(Whisper / SenseVoice / Qwen3-ASR) → ចុច **Transcribe** →
បន្ទាប់មកជ្រើស **Translate Only** → ចុច Dub។
Server ផ្ទុក model នីមួយៗនៅពេលប្រើលើកដំបូងប៉ុណ្ណោះ
(មិនផ្ទុកទាំង 3 ក្នុងពេលតែមួយទេ)។

## ប្រៀបធៀប 3 engines

| Engine | ចំណុចខ្លាំង | ចំណុចខ្សោយ | សាកសម |
|---|---|---|---|
| **Whisper** (`faster-whisper`, script `transcribe.py`) | ងាយដំឡើងបំផុត, ចិនល្អ, ដំណើរការលើ CPU បាន, មាន timestamps ត្រឹមត្រូវ | `large-v3` យឺតលើ CPU (ប្រើ `medium` បើ CPU ខ្សោយ) | **ជម្រើសដំបូងដែលណែនាំ** |
| **SenseVoice** (`FunASR`, script `transcribe_sensevoice.py`) | លឿនបំផុតលើ CPU, ចិនល្អណាស់ (Alibaba, ធ្វើសម្រាប់ចិន/អង់គ្លេស), មាន timestamps | ដំឡើងធ្ងន់ជាងបន្តិច (FunASR + models) | វីដេអូយូរ, ចង់បានលឿន |
| **Qwen3-ASR** (`transformers`, script `transcribe_qwen3.py`) | ថ្មីបំផុត (2025), ចិនត្រឹមត្រូវណាស់, ស្គាល់ភាសា 30+ | ត្រូវការ RAM ច្រើន (0.6B ប្រហែល 4GB RAM, 1.7B ត្រូវ GPU), **គ្មាន timestamps** — .srt បែងចែកតាមពេលវេលា (30 វិនាទីមួយបន្ទាត់) | បើមាន RAM គ្រប់ ឬចង់បានភាពត្រឹមត្រូវខ្ពស់បំផុត |

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

## Qwen3-ASR (script `transcribe_qwen3.py`)

```bash
pip install "transformers>=5.13.0" torch
python3 transcribe_qwen3.py video.mp4 -l zh
# បើមាន RAM ច្រើន / GPU៖  python3 transcribe_qwen3.py video.mp4 --model Qwen/Qwen3-ASR-1.7B-hf
```

Model id ត្រឹមត្រូវគឺ `Qwen/Qwen3-ASR-0.6B-hf` (transformers-native)។
Script បកសំឡេងជា chunk 30 វិនាទីម្ដង ព្រោះ model នេះមិនឱ្យ timestamps
ទេ — .srt បែងចែកតាមពេលវេលា (ប្រយោគនីមួយៗទទួលបានចន្លោះពេលតាមប្រវែងអក្សរ)។
បើចង់បាន timestamps ពិត ត្រូវប្រើ Qwen3-ForcedAligner បន្ថែម (មិនមានក្នុង script នេះ)។

## វិធីប្រើ script ដោយឡែក (មិនប្រើ server)

បើមិនចង់ដំណើរការ server អាច run script នីមួយៗដោយផ្ទាល់ រួចបញ្ចូល .srt ចូល app៖

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

- Script ទាំង 3 បានត្រឹម `python3 -m py_compile` ប៉ុណ្ណោះ លើកលែងតែ Whisper
  ដែលបានសាក transcribe ពិតក្នុង sandbox (Khmer TTS clip → 1 cue, 2026-11-16)
  និងសាក end-to-end តាម app button ម្តងទៀតពេលបន្ថែម engines ថ្មី។
  SenseVoice និង Qwen3-ASR មិនទាន់បានសាក transcribe ពិតនៅឡើយ
  (ត្រូវ download model ធំៗ និង torch) — បើ run ហើយមាន error
  ផ្ញើ error មកឱ្យខ្ញុំ។
- ត្រូវការ Python 3.9+ និង `ffmpeg` ក្នុង PATH (សម្រាប់អាន mp4)។
- `transcribe.py` និង `whisper-server.py` decode សំឡេងដោយ `ffmpeg` ផ្ទាល់
  (មិនប្រើ PyAV) ដើម្បីចៀសបញ្ហា version របស់ PyAV (`metadata_errors`
  error ដែលជួបពេលសាកលើ Muse)។
- **Migration (2026-11-17)៖** ទូរស័ព្ទដែលធ្លាប់ save URL ចាស់ `http://127.0.0.1:8001`
  នឹងត្រូវ app ប្តូរទៅ Cloud server (`https://dinmagic-whisper-q98i15bk-nakforver.cloady.io`)
  ដោយស្វ័យប្រវត្តិម្តងគត់ពេលបើក app — បើចង់ប្រើ localhost វិញ អាចប្តូរ URL ក្នុងប្រអប់បាន
  (app មិនប្តូរវិញទេ)។ URL Cloud ចាស់ (`...cgpozr1p...`) ក៏ត្រូវប្តូរដោយស្វ័យប្រវត្តិដែរ
  ព្រោះ server ត្រូវបង្កើតឡើងវិញពេលដាក់ async jobs។
- **Async jobs (2026-11-17)៖** `POST /transcribe` ឆ្លើយ 202 ជាមួយ job id ភ្លាមៗ
  រួច app poll `GET /job/<id>` រៀងរាល់ 10 វិនាទី ហើយបង្ហាញ progress
  (upload % → load model → transcribe %)។ វីដេអូត្រូវកាត់ត្រឹម **60 នាទី** —
  លើសពីនេះ server បដិសេធជាមួយសារច្បាស់។ សំឡេងត្រូវបកជា chunk 10 នាទីម្ដង
  ដើម្បីកុំឱ្យពេញ RAM។ ពេលវេលាដែលរំពឹង៖ Cloud (tiny) វីដេអូ 9 នាទី ≈ 18 នាទី
  (ពេល model ក្តៅហើយ); លើកុំព្យូទ័រ (medium) វីដេអូ 9 នាទី ≈ 10–20 នាទី។
  Server ចាស់ដែលឆ្លើយ 200 `{"srt": ...}` ផ្ទាល់ នៅប្រើបានដដែល — app ចេះទាំងពីរ។
- **ទាំង 3 engines រត់តែលើកុំព្យូទ័ររបស់អ្នកទេ (localhost)។**
  នៅលើទូរស័ព្ទ app មិនអាចចូល server ក្នុងកុំព្យូទ័របានទេ — វិធីលើទូរស័ព្ទ
  នៅតែដដែល៖ ផ្ញើវីដេអូ/អូឌីយ៉ូមកឱ្យ Muse transcribe រួចយក .srt ត្រឡប់ទៅវិញ។
