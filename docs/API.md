# Voice Dubbing API Documentation

ឯកសារនេះពិពណ៌នាពី API និង service ដែល `dinmagicdubbing` ប្រើសម្រាប់បង្កើត Khmer voice dubbing។ Project បច្ចុប្បន្នដំណើរការនៅក្នុង browser ហើយផ្ញើ request ទៅ external services ដោយផ្ទាល់ពី client។ វាមិនមាន backend API ផ្ទាល់ខ្លួនសម្រាប់ proxy request ទេ។

## 1. Voice-dubbing pipeline

```text
Local video
  → extract audio in browser
  → Gemini transcription + translation
  → Khmer subtitle segments
  → Edge Khmer TTS or Gemini Audio
  → audio clips per subtitle line
  → timeline alignment and audio mixing
  → MP4/WebM export in browser
```

រាល់ subtitle segment មានទិន្នន័យសំខាន់ៗ៖

```json
{
  "s": 0.0,
  "e": 3.2,
  "g": "m",
  "text": "Hello everyone",
  "km": "សួស្តីអ្នកទាំងអស់គ្នា"
}
```

- `s`: ពេលចាប់ផ្តើម គិតជាវិនាទី
- `e`: ពេលបញ្ចប់ គិតជាវិនាទី
- `g`: gender ដែលបានរកឃើញ (`m` ឬ `f`)
- `text`: អត្ថបទដើម
- `km`: Khmer translation ដែលនឹងយកទៅបង្កើតសំឡេង

## 2. Google Gemini API

Gemini ត្រូវបានប្រើសម្រាប់មុខងារពីរ៖

1. Transcribe audio និង translate ទៅ Khmer
2. បង្កើត audio voice នៅពេលជ្រើស `Gemini voice` ឬប្រើជា fallback ពេល Edge helper បរាជ័យ

### 2.1 Authentication

អ្នកប្រើបញ្ចូល Gemini API key នៅក្នុងផ្នែក **Providers**។ Key ត្រូវបានប្រើពី browser ផ្ទាល់ ហើយត្រូវបានរក្សាទុកក្នុង browser `localStorage`។ Project ទទួល key ទម្រង់ Google AI Studio ដូចជា៖

```text
AIzaSy...
AQ....
```

កុំដាក់ API key ពិតនៅក្នុង documentation, source control ឬ screenshot។ សម្រាប់ production គួរប្រើ backend proxy ដែលមាន rate limit និង secret storage ជំនួសការផ្ញើ key ពី browser ផ្ទាល់។

### 2.2 Generate Content endpoint

```http
POST https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}
Content-Type: application/json
```

ឧទាហរណ៍៖

```text
https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=YOUR_KEY
```

សម្រាប់ key ប្រភេទ Vertex/Gemini `AQ...` code ក៏អាចសាកល្បង endpoint នេះ៖

```http
POST https://aiplatform.googleapis.com/v1/publishers/google/models/{MODEL}:generateContent?key={GEMINI_API_KEY}
Content-Type: application/json
```

### 2.3 Transcription និង Khmer translation

Audio ត្រូវបានបម្លែងទៅ WAV 16 kHz mono នៅក្នុង browser ហើយ encode ជា Base64។ Request body មានទម្រង់៖

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "inlineData": {
            "mimeType": "audio/wav",
            "data": "BASE64_WAV_AUDIO"
          }
        },
        {
          "text": "Transcribe every spoken sentence and translate each one into natural conversational Khmer. Return only a JSON array..."
        }
      ]
    }
  ],
  "generationConfig": {
    "responseMimeType": "application/json",
    "temperature": 0,
    "maxOutputTokens": 8192
  }
}
```

Response ដែល project រំពឹងទុក៖

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "text": "[{\"s\":0,\"e\":3.2,\"g\":\"m\",\"text\":\"Hello everyone\",\"km\":\"សួស្តីអ្នកទាំងអស់គ្នា\"}]"
          }
        ]
      }
    }
  ]
}
```

Project នឹង parse `candidates[0].content.parts[].text` ជា JSON ហើយប្រើ `km`, `s`, `e` និង `g` សម្រាប់ដំណាក់កាលបន្ទាប់។

### 2.4 Gemini voice/TTS

នៅពេលជ្រើស `Gemini voice`, project ផ្ញើ Khmer text ជាមួយ `responseModalities: ["AUDIO"]`៖

```http
POST https://generativelanguage.googleapis.com/v1beta/models/{TTS_MODEL}:generateContent?key={GEMINI_API_KEY}
Content-Type: application/json
```

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "សួស្តីអ្នកទាំងអស់គ្នា"
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {
          "voiceName": "Puck"
        }
      }
    }
  }
}
```

Response មាន audio ជា inline Base64 data៖

```json
{
  "candidates": [
    {
      "content": {
        "parts": [
          {
            "inlineData": {
              "mimeType": "audio/L16;rate=24000",
              "data": "BASE64_AUDIO_DATA"
            }
          }
        ]
      }
    }
  ]
}
```

Project នឹង៖

1. Decode Base64 ទៅ bytes
2. ពិនិត្យ `mimeType` និង sample rate
3. បន្ថែម WAV header ប្រសិនបើ response ជា raw PCM
4. បង្កើត `Blob` និង `Object URL`
5. រក្សាទុក audio clip តាម subtitle segment

Voice names ដែល UI អាចផ្តល់ជូនអាស្រ័យលើ model account និង model ដែលបាន load។ ឧទាហរណ៍៖

```text
Puck, Charon, Fenrir, Orus
Zephyr, Kore, Leda, Aoede
```

Gender mapping របស់ project សម្រាប់ Auto mode គឺ៖

```text
male   → Puck
female → Zephyr
```

### 2.5 Model listing និង key verification

Project អាចពិនិត្យ key និងទាញយក model list ដោយ៖

```http
GET https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}
```

ឬ៖

```http
GET https://generativelanguage.googleapis.com/v1beta/models?pageSize=100
x-goog-api-key: {GEMINI_API_KEY}
```

នៅពេល key ប្រភេទ `AQ...` វាអាចសាកល្បង Vertex endpoint ជាមួយ request តូចមួយ ដើម្បីពិនិត្យថា key អាចប្រើបាន។

### 2.6 Retry និង rate-limit behavior

Project រក្សាស្ថានភាព key/model ក្នុង browser ដើម្បីកុំឱ្យផ្ញើ request ទៅ key ដែលកំពុង rate-limited។ វាធ្វើដូចខាងក្រោម៖

- ប្តូរទៅ key បន្ទាប់ ប្រសិនបើ key បច្ចុប្បន្ន error
- ប្តូរទៅ model បន្ទាប់ ប្រសិនបើ model មិនគាំទ្រ
- រង់ចាំ cooldown បន្ទាប់ពី HTTP `429` ឬ server `5xx`
- សម្គាល់ daily quota ហើយរំលងរហូតដល់ quota reset
- បញ្ឈប់ key ដែលបានឆ្លើយ `400`, `401` ឬ `403` ពាក់ព័ន្ធនឹង API key

HTTP status ដែលគួរយកចិត្តទុកដាក់៖

| Status | អត្ថន័យទូទៅ | អាកប្បកិរិយារបស់ tool |
|---|---|---|
| `200` | Request ជោគជ័យ | Parse text ឬ audio response |
| `400` | Request/model/config មិនត្រឹមត្រូវ | សាកល្បង model/key បន្ទាប់ ឬបង្ហាញ error |
| `401` / `403` | Key មិនត្រឹមត្រូវ ឬគ្មានសិទ្ធិ | សម្គាល់ key ជា invalid |
| `404` | Model/endpoint មិនមាន | រំលង model នោះ |
| `429` | Rate limit ឬ quota | Cooldown និង retry ពេលក្រោយ |
| `5xx` | Gemini server error | Retry និងប្តូរ key/model |

## 3. Edge Khmer TTS helper

Edge voice ជាជម្រើស default សម្រាប់បង្កើតសំឡេង Khmer ដែលអាច export បាន។ Base URL ត្រូវបានកំណត់ក្នុង `index.html`៖

```text
https://khmer-voice-1.onrender.com
```

Repository នេះមានតែ client integration ប៉ុណ្ណោះ មិនមាន source code របស់ helper server ទេ។ ដូច្នេះ implementation ខាងក្នុងរបស់ helper មិនគួរត្រូវបានចាត់ទុកថាជាផ្នែកដែល project គ្រប់គ្រងឡើយ។

### 3.1 Health check

```http
GET https://khmer-voice-1.onrender.com/ping
```

Response ដែល project រំពឹងថា HTTP `2xx`។ ក្នុង UI វាអាចបង្ហាញថា helper កំពុងដំណើរការ។ Server ដែលដំណើរការលើ free hosting អាចត្រូវការ wake-up មុន request ដំបូង។

### 3.2 Text-to-speech request

```http
POST https://khmer-voice-1.onrender.com/tts
Content-Type: application/json
```

Request body៖

```json
{
  "text": "សួស្តីអ្នកទាំងអស់គ្នា",
  "voice": "km-KH-PisethNeural"
}
```

បើមាន rate option៖

```json
{
  "text": "សួស្តីអ្នកទាំងអស់គ្នា",
  "voice": "km-KH-SreymomNeural",
  "rate": 1.0
}
```

Response គួរតែជា binary audio response ដែល browser អាចអានជា `Blob`៖

```javascript
const response = await fetch(`${base}/tts`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text, voice })
});

const audioBlob = await response.blob();
```

Project ពិនិត្យថា response ជា HTTP success និង blob មានទំហំគ្រប់គ្រាន់ មុនរក្សាទុកជា audio clip។

### 3.3 Voice selection

Voice ជ្រើសតាម speaker gender ដែល Gemini បានរកឃើញ៖

```text
m → km-KH-PisethNeural
f → km-KH-SreymomNeural
```

អ្នកក៏អាចជ្រើស voice fixed នៅក្នុង Pipeline tab៖

```text
Auto from subtitle gender
Piseth (male only)
Sreymom (female only)
```

### 3.4 Text chunking និង retry

ដើម្បីកាត់បន្ថយ TTS failure, text វែងត្រូវបំបែកជាច្រើន chunk។ លំដាប់ដែល project ប្រើជាទូទៅ៖

```text
140 characters → retry with 60 → retry with 28
```

Request នីមួយៗមាន timeout ប្រហែល 25 វិនាទី។ Project អាច retry request រហូតដល់ 4 ដង និង retry failed subtitle lines ជាជុំបន្ថែម។ Audio chunks ត្រូវបាន decode និងភ្ជាប់ជាមួយ gap តូចប្រហែល 0.12 វិនាទី មុនរក្សាទុកជាខ្សែ audio មួយសម្រាប់ subtitle line នោះ។

## 4. Fallback order

នៅពេលជ្រើស `Edge voice`៖

```text
1. ពិនិត្យ Edge helper /ping
2. ផ្ញើ text ទៅ Edge /tts
3. Retry failed lines
4. បើនៅតែបរាជ័យ និងមាន Gemini key → ប្រើ Gemini voice fallback
```

នៅពេលជ្រើស `Gemini voice`៖

```text
1. ពិនិត្យ Gemini key និង model
2. ផ្ញើ Khmer text ទៅ generateContent ជាមួយ AUDIO modality
3. Decode inline audio
4. រក្សាទុក audio clip សម្រាប់ line នីមួយៗ
```

ជម្រើស `This device’s Khmer voice` មិនប្រើ external API ហើយប្រើ browser `speechSynthesis`។ Voice ប្រភេទនេះអាចស្តាប់បានក្នុង browser ប៉ុន្តែមិនអាចកត់ត្រាជា audio file សម្រាប់ export video បានទេ។

## 5. Audio timeline និង mixing

បន្ទាប់ពីបាន audio clip នីមួយៗ project រក្សាទុកវាជាមួយ timestamp៖

```javascript
{
  t: 5.2,
  e: 7.8,
  km: 'សួស្តីអ្នកទាំងអស់គ្នា',
  audio: 'blob:...'
}
```

ក្នុង browser វានឹង៖

1. Decode clip ទាំងអស់ជាមួយ `AudioContext`
2. ដាក់ clip តាម `t` របស់ subtitle
3. កែ timing ប្រសិនបើ clip វែងជាង subtitle slot
4. លាយ Khmer voice ជាមួយ original audio តាម volume slider
5. បង្កើត `AudioBuffer` ពេញប្រវែង video
6. ផ្ញើ buffer ទៅ MediaBunny សម្រាប់ encode/mux នៅពេល export

ការលាយ audio និងការបង្កើត video output ធ្វើនៅលើ device របស់អ្នក។ Gemini និង Edge helper ទទួលតែ audio/text request ដែល client ផ្ញើទៅពួកវា មិនទទួល finished exported video ពី project ទេ។

## 6. Browser/CORS requirements

ដោយសារ request ចេញពី browser ផ្ទាល់៖

- Gemini endpoint ត្រូវអនុញ្ញាត request ដែលមាន API key តាម query ឬ header
- Edge helper ត្រូវអនុញ្ញាត CORS ពី origin របស់ website
- Browser ត្រូវអនុញ្ញាត `fetch`, `Blob`, `AudioContext` និង object URLs
- Network connection ត្រូវមានសម្រាប់ Gemini, Edge helper និង MediaBunny CDN

ប្រសិនបើ local server ប្រើ `http://127.0.0.1:8000` ហើយ helper មិនកំណត់ CORS សម្រាប់ origin នេះ ទំព័រអាចបង្ហាញ CORS error ទោះ helper server កំពុង online ក៏ដោយ។

## 7. Troubleshooting checklist

### Gemini មិនដំណើរការ

- ពិនិត្យថា API key ត្រូវបានបញ្ចូលក្នុង Providers
- ពិនិត្យ model ដែលបានជ្រើសគាំទ្រ `generateContent`
- ពិនិត្យ browser Network tab រក HTTP `400`, `403` ឬ `429`
- សាកល្បង model ផ្សេង ឬ key ផ្សេង
- កុំដាក់ key ដែលមានសិទ្ធិខ្ពស់ពេកក្នុង client-side app

### Edge voice មិនឆ្លើយ

- សាកល្បង `GET /ping`
- រង់ចាំ server wake-up ប្រសិនបើ free hosting បាន sleep
- ពិនិត្យ CORS error ក្នុង browser console
- ពិនិត្យថា `voice` ជា `km-KH-PisethNeural` ឬ `km-KH-SreymomNeural`
- ប្រសិនបើមាន Gemini key អាចប្រើ Gemini voice ជំនួស

### Voice បាន ប៉ុន្តែ export មិនមានសំឡេង

- កុំប្រើ device voice សម្រាប់ export
- ជ្រើស Edge voice ឬ Gemini voice
- ចុច Generate Audio មុន Export
- ពិនិត្យថា audio clip មាន size ធំជាង 200 bytes
- ពិនិត្យថា subtitle segment មាន `km` និង timestamp ត្រឹមត្រូវ

## 8. Security notes

ការរក្សា Gemini API key ក្នុង browser គឺសមសម្រាប់ local testing ឬ personal use ប៉ុណ្ណោះ។ សម្រាប់ production គួរ៖

- រក្សា key នៅ server-side secret manager
- បង្កើត backend proxy សម្រាប់ Gemini
- ដាក់ per-user quota និង request size limit
- កំណត់ allowed origins និង CORS ឱ្យច្បាស់
- មិន log API key ឬ audio content ក្នុង production logs
- កំណត់ Google API restrictions និង billing quota

ឯកសារនេះពិពណ៌នាតាម implementation បច្ចុប្បន្នរបស់ project។ ប្រសិនបើប្តូរ endpoint, model, voice helper ឬ request schema ត្រូវ update ឯកសារនេះជាមួយ code ផង។
