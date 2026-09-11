# 🎵 Acoustic Song Recognition System

[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Django](https://img.shields.io/badge/Django-4.x-092E20?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Spotify API](https://img.shields.io/badge/Spotify-API-1DB954?style=for-the-badge&logo=spotify&logoColor=white)](https://developer.spotify.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

An intelligent, multi-interface **Automatic Song & Music Recognition System** written in Python. The system captures 10 seconds of live audio or accepts pre-recorded audio files and recognizes songs using a **hybrid dual-engine architecture**:

1. **Cloud Acoustic Recognition**: Powered by the **ACRCloud** audio fingerprinting database and enriched with real-time metadata, high-resolution album artwork, preview audio, and track URLs from the **Spotify Web API**.
2. **Custom In-House DSP Acoustic Fingerprinting Engine**: A digital signal processing (DSP) engine implementing the landmark Avery Wang (Shazam) algorithm — featuring Short-Time Fourier Transform (STFT) spectrogram computation, 2D local maximum filtering (Constellation Map extraction), combinatorial peak hashing, and relative time-delta histogram alignment.

The system is accessible via three interfaces:
- 🖥️ **Desktop GUI**: Built with Python **Tkinter** with live spectrogram rendering and local database indexing.
- 🌐 **Web Dashboard**: Modern dark-mode web application built with **Flask** and HTML5 Web Audio API.
- ⚙️ **REST API Backend**: Modular enterprise service built with **Django**.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Audio Input
        Mic[Microphone Input / 10s Capture] --> Ingest[Audio Preprocessing & Mono Downmixing]
        Upload[WAV / MP3 File Upload] --> Ingest
    end

    subgraph Cloud Recognition Engine
        Ingest --> ACR[ACRCloud Fingerprinting API]
        ACR --> ACRMeta[Parse Title, Artist, Album & Spotify Track ID]
        ACRMeta --> Spotify[Spotify Web API Client]
        Spotify --> RichMeta[Album Art, 30s Audio Preview, Direct Links]
    end

    subgraph Custom DSP Fingerprinting Engine
        Ingest --> STFT[Short-Time Fourier Transform / STFT]
        STFT --> Spec[Log-Power 2D Spectrogram]
        Spec --> Peaks[2D Local Max Filtering / Constellation Map]
        Peaks --> Hashing[Combinatorial Target-Zone Hashing]
        Hashing --> Delta[Time-Delta Histogram Peak Matcher]
        Delta --> LocalDB[(Local Fingerprint Index)]
    end

    RichMeta --> TkinterApp[Tkinter Desktop App (song.py)]
    Delta --> TkinterApp
    RichMeta --> FlaskApp[Flask Web Dashboard (flask_app.py)]
    Delta --> FlaskApp
    RichMeta --> DjangoAPI[Django REST API (django_app/)]
    Delta --> DjangoAPI
```

---

## 🔬 Mathematical Deep Dive: How Audio Fingerprinting Works

Commercial music identification (like Shazam) does not compare raw waveforms because audio recordings captured from microphones suffer from room acoustics, background noise, low-quality microphones, and volume variation. Instead, our custom fingerprinting engine uses **Spectrogram Constellation Hashing**:

### 1. Short-Time Fourier Transform (STFT)
The audio time-series signal $x[n]$ sampled at $f_s = 44,100\text{ Hz}$ is partitioned into overlapping windows (window size $N = 4096$, hop size $H = 512$) multiplied by a Hann window function $w[n]$:

$$X(m, \omega) = \sum_{n=0}^{N-1} x[n + mH] \cdot w[n] \cdot e^{-j \omega n}$$

We convert the magnitude spectrum into logarithmic decibels ($\text{dB}$):
$$S_{\text{dB}}(m, k) = 20 \log_{10}\left(\max(|X(m, k)|, 10^{-6})\right)$$

### 2. Peak Picking & Constellation Map
A local 2D maximum filter ($\text{neighborhood} = 25 \times 25$) is swept across the spectrogram matrix to identify points that are strictly higher in amplitude than all surrounding neighbors and above a dynamic 75th-percentile energy threshold:

$$\text{is\_peak}(t, f) = \left(S_{\text{dB}}(t, f) == \max_{(i, j) \in \mathcal{N}} S_{\text{dB}}(t+i, f+j)\right) \land \left(S_{\text{dB}}(t, f) > \tau\right)$$

This condenses thousands of audio samples into a sparse set of dominant frequency coordinates: the **Constellation Map** $\{(t_i, f_i)\}$.

### 3. Combinatorial Target-Zone Hashing
Raw individual peaks are susceptible to false alarms. To make fingerprints unique, each **anchor peak** $(t_1, f_1)$ is paired with multiple subsequent peaks $(t_2, f_2)$ situated in a forward lookahead "target zone":
- Time delta constraint: $t_{\min} \le t_2 - t_1 \le t_{\max}$
- Frequency delta constraint: $|f_2 - f_1| \le \Delta f_{\max}$

A cryptographic hash is generated from the tuple $(f_1, f_2, \Delta t)$:
$$\text{Hash} = \text{SHA1}(f_1 \parallel f_2 \parallel (t_2 - t_1))_{[0:12]}$$
Each fingerprint stored in the database consists of `(Hash, t1_offset)`.

### 4. Temporal Coherence Matching (Time-Delta Histogram Peak)
When matching a 10-second query against the database:
1. For every hash match between query and database, calculate the time difference:
   $$\Delta t = t_{\text{database}} - t_{\text{query}}$$
2. If the audio is indeed the same song, true hash collisions will all share the exact same time offset $\Delta t$, regardless of background noise. Random noise collisions will be scattered randomly across time.
3. Plotting a histogram of $\Delta t$ reveals a sharp peak for the true song. The height and coherence of this peak determine the match confidence!

---

## ✨ Features

- 🎧 **10-Second Mic Capture**: One-click microphone recording with automatic input device validation.
- 🌐 **Cloud Recognition**: Instant identification via ACRCloud API covering tens of millions of commercial tracks.
- 🎨 **Spotify Web API Enrichment**: Fetches high-resolution album artwork, artist details, album name, Spotify web URL, and 30-second audio previews.
- 🔬 **Custom DSP Fingerprinting**: Offline-capable constellation spectrogram matcher with local JSON indexing.
- 📊 **Spectrogram Visualizer**: View color-coded audio spectrograms overlaid with extracted constellation peaks directly in Tkinter and Flask.
- 🖥️ **Three User Interfaces**:
  - **Tkinter Desktop GUI**: Complete native desktop experience.
  - **Flask Web Dashboard**: Responsive dark-mode interface with live recording and file upload.
  - **Django REST Service**: Scalable API endpoints ready for enterprise integration.

---

## 📁 Repository Structure

```
Song-Recognition-System/
├── song.py                 # Tkinter desktop GUI application
├── fingerprint.py          # Custom DSP audio fingerprinting engine
├── flask_app.py            # Flask web server & REST API
├── templates/
│   └── index.html          # Modern dark-mode web dashboard UI
├── django_app/             # Django project configuration & API views
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── views.py
│   └── wsgi.py
├── manage.py               # Django CLI management script
├── requirements.txt        # Python package dependencies
├── .env.example            # Environment variables template
├── .gitignore              # Git ignore rules
└── README.md               # Project documentation
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.8 to 3.11
- PortAudio (for microphone access):
  - **macOS**: `brew install portaudio`
  - **Ubuntu/Debian**: `sudo apt-get install portaudio19-dev libasound2-dev`
  - **Windows**: Included with `sounddevice` wheels automatically

### 2. Installation
Clone the repository and install the dependencies:

```bash
git clone https://github.com/yxshh98/Song-Recognition-System.git
cd Song-Recognition-System
pip install -r requirements.txt
```

### 3. API Credentials Setup (Optional)
Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
ACRCLOUD_HOST=identify-ap-southeast-1.acrcloud.com
ACRCLOUD_ACCESS_KEY=your_acrcloud_access_key
ACRCLOUD_ACCESS_SECRET=your_acrcloud_access_secret
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

> **Note**: Default working fallback credentials are provided in the codebase for immediate out-of-the-box demonstration.

---

## 💻 How to Run

### Option 1: Desktop Application (Tkinter GUI)
Launch the graphical desktop interface:

```bash
python song.py
```
- Click **"🎧 Identify Song from Mic (10s)"** to record and identify music playing around you.
- Click **"📊 View Spectrogram"** to inspect the STFT power spectrogram and constellation peaks.
- Click **"💾 Save to Local DB"** to add the identified track into your local acoustic fingerprint database.

---

### Option 2: Web Application (Flask Dashboard)
Start the local web server:

```bash
python flask_app.py
```
Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your browser. You can record audio directly through your web browser or upload `.wav` / `.mp3` files for recognition.

---

### Option 3: Django REST API
Start the Django development server:

```bash
python manage.py runserver 8000
```
API endpoints:
- `POST /api/recognize/`: Upload an audio file to receive DSP acoustic fingerprints and matching candidates.
- `POST /api/index/`: Index an audio file under a specific song title into the local database.
- `GET /api/catalog/`: Retrieve the list of all indexed songs.

---

## 🛠️ Troubleshooting & FAQs

### macOS Microphone Permissions
If microphone recording fails on macOS:
1. Open **System Settings → Privacy & Security → Microphone**.
2. Ensure your terminal or IDE (Terminal, iTerm2, VSCode, PyCharm) has microphone permissions enabled.

### SSL Certificate Verification Errors
If you encounter `CERTIFICATE_VERIFY_FAILED` on macOS when contacting Spotify or ACRCloud:
- Run the python certificate installer:
  ```bash
  /Applications/Python\ 3.x/Install\ Certificates.command
  ```
- The codebase also automatically bundles `certifi` to resolve SSL verification issues seamlessly.

---

## 📄 License
Distributed under the MIT License. See `LICENSE` for more information.

---

## 👤 Author
- **Yash Chhabda** - [GitHub Profile](https://github.com/yxshh98)
