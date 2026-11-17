# dinmagic-whisper — Whisper server លើ Cloady (FREE)

Server នេះដាក់លើ Cloady ដើម្បីឱ្យ app dinmagicdubbing នៅលើ**ទូរស័ព្ទ**
ក៏ transcribe បានដែរ — មិនបាច់ដំណើរការ server លើកុំព្យូទ័រទេ។

## វាធ្វើអ្វី

- `POST /transcribe` — ទទួលវីដេអូ/អូឌីយ៉ូ រួចឆ្លើយ 202 ជាមួយ job id
  ភ្លាមៗ (`{"job": "<id>", "status": "queued"}`) រួច transcribe នៅខាងក្រោយ។
- `GET /job/<id>` — ពិនិត្យ progress (`queued → loading → processing →
  done/error`, `progress` 0–100) រួចយក .srt ពេលរួច។
- `GET /healthz` — ពិនិត្យថា server រត់ឬអត់។

App upload ដោយបង្ហាញ % ហើយ poll job រៀងរាល់ 10 វិនាទី ដូច្នេះប៊ូតុង
លែងគាំងពេល upload/transcribe វីដេអូធំៗ។ វីដេអូត្រូវកាត់ត្រឹម
**60 នាទី** — លើសពីនេះ server បដិសេធជាមួយសារច្បាស់។ សំឡេងត្រូវបកជា
chunk 10 នាទីម្ដង ដើម្បីកុំឱ្យពេញ RAM 0.5 GB។

## ហេតុអ្វីបានជា Whisper tiny?

Free tier ឱ្យ app នេះតែ **0.25 CPU / 0.5 GB RAM**។ វាស់នៅលើ CPU
( int8 )៖

| Model | RAM ខ្ពស់បំផុត | ល្បឿន (1 core) | ចុះឬអត់ |
|---|---|---|---|
| Whisper **tiny** | ~325 MB | ~3.7× realtime | ✅ ចុះ |
| Whisper base | ~482 MB | ~3.8× realtime | ❌ ជិតពេញ 512 MB — វីដេអូ 9 នាទីអាច OOM |
| SenseVoiceSmall | ~2 GB | — | ❌ (torch + model 936 MB fp32) |
| Qwen3-ASR 0.6B | ~1.2 GB+ | — | ❌ (transformers + torch) |

Tiny ជា model តែមួយគត់ដែលចុះពិតប្រាកដ។ នៅលើភាសាចិនច្បាស់ៗ វាបក
ពាក្យបាន តែមានកំហុស homophone (ឧ. 世界→事件 លើឃ្លាសាកល្បង);
នៅលើសន្ទនាលឿនៗក្នុងរឿង វាខ្សោយជាង medium។ បើចង់បាន transcript
ត្រឹមត្រូវបំផុត សូមរត់ `whisper-server.py` (medium) នៅលើកុំព្យូទ័រ
របស់អ្នកដូចដើម។

ល្បឿនដែលវាស់បាននៅលើ Cloady **JPN1** (0.25 CPU, `cpu_threads=1`)៖
transcribe លើកដំបូង 35 វិនាទី ចំណាយ 3m15s (load model ~2 នាទី +
inference ~1 នាទី); ពេល model ក្តៅហើយ ~2× realtime + ~15 វិនាទី
overhead (ឃ្លា 3 វិនាទី ចំណាយ 22 វិនាទី)។ វីដេអូ 9 នាទីត្រូវការ
~18 នាទី — តែឥឡូវជា async job (upload → poll) ដូច្នេះលែងមានបញ្ហា
request timeout ហើយ app បង្ហាញ progress ជាប់រហូត។ **EU1 ប្រើ
មិនកើតទេ** (host ខ្វះ CPU៖ load model 5–10+ នាទី, ~7× realtime)
— ត្រូវប្រើ JPN1។

Model (~75 MB) ត្រូវបានដាក់ចូលក្នុង image តាំងពីពេល build
(`railpack.json` + `download_model.py`) ដូច្នេះពេលរត់មិនត្រូវការ
download ពី HuggingFace ឡើយ (download ក្នុង container នៅលើ
Cloady ជាប់គាំង)។ ប៉ុន្តែ load model ចូល memory នៅតែត្រូវការ
~2 នាទីនៅលើ JPN1 នៅពេល transcribe លើកដំបូងបន្ទាប់ពី server
ចាប់ផ្តើមឡើងវិញ។

## របៀបប្រើក្នុង app

នៅក្នុង app → tab Subtitles → URL របស់ server ត្រូវបានដាក់ជា default
(https://dinmagic-whisper-q98i15bk-nakforver.cloady.io — JPN1) រួចជ្រើស
Whisper → Transcribe → បន្ទាប់មកជ្រើស **Translate Only → Dub** ដើម្បីឱ្យ
Gemini បកប្រែជាខ្មែរ។ URL នៅតែកែបាន — បើចង់ប្រើ server លើកុំព្យូទ័រវិញ
សូមដាក់ `http://127.0.0.1:8001` មកវិញ។

## Deploy ឡើងវិញ

Zip folder នេះ (`server.py`, `requirements.txt`, `README-km.md`,
`railpack.json`, `download_model.py`) រួច deploy លើ Cloady ជា app
ថ្មី (upload source, `PORT=8000`, scale 0.5×, `price: 0`,
**region JPN1** — EU1 ប្រើមិនកើតដោយសារ host ខ្វះ CPU)។ ឈ្មោះឯកសារ
`server.py` គឺចាំបាច់ — Railpack ស្គាល់តែ `server.py` / `app.py` /
`main.py` … ប៉ុណ្ណោះ បើដាក់ឈ្មោះផ្សេង វានឹង crash-loop។
