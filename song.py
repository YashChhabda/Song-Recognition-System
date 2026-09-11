"""
Song Recognition System (Desktop GUI - Tkinter)
================================================
Automatic music identification system combining:
1. Cloud Audio Recognition: ACRCloud Fingerprinting Engine + Spotify Web API metadata.
2. Custom Acoustic DSP Fingerprinter: Short-Time Fourier Transform (STFT), 2D Local Maximum
   filtering (Constellation Map), Combinatorial Hashing, and Temporal Coherence Matcher.
"""

import os
import ssl
import json
import io
import webbrowser
import threading
from queue import Queue, Empty
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

# SSL / certificate handling
import certifi
os.environ.setdefault('SSL_CERT_FILE', certifi.where())
try:
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except Exception:
    pass

# Audio & API Dependencies
import requests
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import sounddevice as sd
import soundfile as sf
from acrcloud.recognizer import ACRCloudRecognizer

# Custom Acoustic Fingerprinting Engine
try:
    from fingerprint import AudioFingerprinter
except ImportError:
    from Song_Recognition_System.fingerprint import AudioFingerprinter


class MusicRecognizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Acoustic Song Recognition System")
        self.root.geometry("640x480")
        self.root.minsize(580, 440)

        # Credentials: read from environment or use default fallbacks
        self.ACRCLOUD_HOST = os.getenv('ACRCLOUD_HOST', 'identify-ap-southeast-1.acrcloud.com')
        self.ACRCLOUD_ACCESS_KEY = os.getenv('ACRCLOUD_ACCESS_KEY', '65365a6d4d2d133fad5ed94e39d61086')
        self.ACRCLOUD_ACCESS_SECRET = os.getenv('ACRCLOUD_ACCESS_SECRET', 'x0jRjc5h76A4amsXDgLh9C37A1WNg4xO7irCPvfb')
        self.SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '82df22cf76bf45b49aee5d30f1faa8d3')
        self.SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', 'dacdd714badb4feaa7fc7be4bf8d0541')

        self.RECORD_DURATION_SEC = 10
        self.SAMPLE_RATE = 44100
        self.RECORDING_FILENAME = 'my_recording.wav'

        # Initialize local DSP fingerprinter
        self.fingerprinter = AudioFingerprinter(sample_rate=self.SAMPLE_RATE)

        self.result_queue = Queue()
        self.album_art_image = None
        self.last_recording_path = None
        self.last_fingerprint_data = None
        self.current_song_name = None

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top Control Bar
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 8))

        self.recognize_button = ttk.Button(
            top_frame,
            text="🎧 Identify Song from Mic (10s)",
            command=self.start_recognition_thread
        )
        self.recognize_button.pack(side=tk.LEFT, padx=(0, 8))

        self.spectrogram_btn = ttk.Button(
            top_frame,
            text="📊 View Spectrogram",
            command=self.show_spectrogram_window,
            state="disabled"
        )
        self.spectrogram_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.index_button = ttk.Button(
            top_frame,
            text="💾 Save to Local DB",
            command=self.index_current_song,
            state="disabled"
        )
        self.index_button.pack(side=tk.LEFT)

        # Status Bar
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(4, 8))
        self.status_label = ttk.Label(
            status_frame,
            text="Ready. Click 'Identify Song from Mic' to begin 10-second capture.",
            font=("Segoe UI", 9, "italic")
        )
        self.status_label.pack(side=tk.LEFT)

        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        # Main Content Layout: Left (Album Art) / Right (Metadata & DSP Metrics)
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Left Column: Album Art
        left_col = ttk.Frame(content_frame)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))

        self.art_label = ttk.Label(left_col)
        self.art_label.pack(anchor=tk.N)
        placeholder = Image.new("RGB", (170, 170), (220, 224, 230))
        self.album_art_image = ImageTk.PhotoImage(placeholder)
        self.art_label.config(image=self.album_art_image)

        # Right Column: Identification Details & DSP Info
        right_col = ttk.Frame(content_frame)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.title_label = ttk.Label(right_col, text="Title: -", font=("Segoe UI", 13, "bold"))
        self.title_label.pack(anchor=tk.W, pady=(0, 2))

        self.artist_label = ttk.Label(right_col, text="Artist: -", font=("Segoe UI", 10))
        self.artist_label.pack(anchor=tk.W, pady=(0, 2))

        self.album_label = ttk.Label(right_col, text="Album: -", font=("Segoe UI", 10))
        self.album_label.pack(anchor=tk.W, pady=(0, 8))

        # Links
        links_frame = ttk.Frame(right_col)
        links_frame.pack(anchor=tk.W, pady=(0, 10))

        self.spotify_link_label = ttk.Label(links_frame, text="", foreground="#1DB954", cursor="hand2", font=("Segoe UI", 9, "underline"))
        self.spotify_link_label.pack(side=tk.LEFT, padx=(0, 12))

        self.preview_link_label = ttk.Label(links_frame, text="", foreground="#0066cc", cursor="hand2", font=("Segoe UI", 9, "underline"))
        self.preview_link_label.pack(side=tk.LEFT)

        # DSP Metrics Frame
        dsp_group = ttk.LabelFrame(right_col, text="Custom DSP Acoustic Fingerprinting Analysis", padding=8)
        dsp_group.pack(fill=tk.X, pady=(6, 0))

        self.dsp_peaks_label = ttk.Label(dsp_group, text="Extracted Spectral Peaks: -", font=("Segoe UI", 9))
        self.dsp_peaks_label.pack(anchor=tk.W)

        self.dsp_hashes_label = ttk.Label(dsp_group, text="Combinatorial Hashes Generated: -", font=("Segoe UI", 9))
        self.dsp_hashes_label.pack(anchor=tk.W)

        self.dsp_match_label = ttk.Label(dsp_group, text="Local Database Match: -", font=("Segoe UI", 9))
        self.dsp_match_label.pack(anchor=tk.W)

    # -------------------------------------------------------------------------
    # Threading & Pipeline Coordination
    # -------------------------------------------------------------------------
    def start_recognition_thread(self):
        self.recognize_button.config(state="disabled")
        self.spectrogram_btn.config(state="disabled")
        self.index_button.config(state="disabled")
        self.clear_results()
        threading.Thread(target=self.run_recognition_pipeline, daemon=True).start()
        self.root.after(100, self.check_result_queue)

    def run_recognition_pipeline(self):
        try:
            # 1. Record 10s audio
            self.result_queue.put({'status': 'recording'})
            recorded_file = self.record_audio()
            if not recorded_file:
                return

            self.last_recording_path = recorded_file

            # 2. Run Custom DSP Fingerprinting
            self.result_queue.put({'status': 'dsp_analyzing'})
            fp_data = self.fingerprinter.fingerprint_file(recorded_file)
            local_match = self.fingerprinter.match_audio(recorded_file)

            # 3. Query Cloud ACRCloud Recognition
            self.result_queue.put({'status': 'identifying'})
            identified_song = self.identify_song(recorded_file)

            # 4. Fetch Spotify Metadata
            spotify_info = None
            if identified_song and identified_song.get('spotify_id'):
                self.result_queue.put({'status': 'fetching'})
                spotify_info = self.get_spotify_details(identified_song.get('spotify_id'))

            self.result_queue.put({
                'status': 'complete',
                'acr_data': identified_song,
                'spotify_data': spotify_info,
                'dsp_data': fp_data,
                'local_match': local_match
            })

        except Exception as e:
            self.result_queue.put({'error': f'Pipeline Error: {e}'})

    def check_result_queue(self):
        try:
            msg = self.result_queue.get(block=False)

            if 'error' in msg:
                self.status_label.config(text=f"Error: {msg['error']}")
                self.recognize_button.config(state="normal")

            elif msg['status'] == 'recording':
                self.status_label.config(text=f"Recording microphone input... ({self.RECORD_DURATION_SEC}s)")
                self.root.after(100, self.check_result_queue)

            elif msg['status'] == 'dsp_analyzing':
                self.status_label.config(text="Computing STFT Spectrogram & Constellation Hashes...")
                self.root.after(100, self.check_result_queue)

            elif msg['status'] == 'identifying':
                self.status_label.config(text="Querying ACRCloud Acoustic Fingerprint database...")
                self.root.after(100, self.check_result_queue)

            elif msg['status'] == 'fetching':
                self.status_label.config(text="Enriching with Spotify metadata & artwork...")
                self.root.after(100, self.check_result_queue)

            elif msg['status'] == 'complete':
                self.status_label.config(text="Analysis Complete.")
                self.display_pipeline_results(msg)
                self.recognize_button.config(state="normal")
                self.spectrogram_btn.config(state="normal")
                if self.current_song_name:
                    self.index_button.config(state="normal")

        except Empty:
            self.root.after(100, self.check_result_queue)

    # -------------------------------------------------------------------------
    # UI Display Updates
    # -------------------------------------------------------------------------
    def display_pipeline_results(self, result_msg):
        acr_data = result_msg.get('acr_data')
        spotify_data = result_msg.get('spotify_data')
        dsp_data = result_msg.get('dsp_data')
        local_match = result_msg.get('local_match')

        # Cloud metadata
        if acr_data:
            self.current_song_name = f"{acr_data.get('title', 'Unknown')} - {acr_data.get('artist', 'Unknown')}"
            self.title_label.config(text=f"Title: {acr_data.get('title', '-')}")
            self.artist_label.config(text=f"Artist: {acr_data.get('artist', '-')}")
            self.album_label.config(text=f"Album: {acr_data.get('album', '-')}")
        else:
            self.current_song_name = None
            self.title_label.config(text="Title: No Cloud Match Found")
            self.artist_label.config(text="Artist: -")
            self.album_label.config(text="Album: -")

        # Spotify links & artwork
        if spotify_data:
            threading.Thread(target=self.load_album_art, args=(spotify_data['album_art_url'],), daemon=True).start()

            spotify_url = spotify_data['spotify_url']
            self.spotify_link_label.config(text="Open in Spotify ↗")
            self.spotify_link_label.bind("<Button-1>", lambda e: self.open_link(spotify_url))

            preview_url = spotify_data.get('preview_url')
            if preview_url:
                self.preview_link_label.config(text="Play 30s Preview ▷")
                self.preview_link_label.bind("<Button-1>", lambda e: self.open_link(preview_url))
            else:
                self.preview_link_label.config(text="(Preview unavailable)")
                self.preview_link_label.unbind("<Button-1>")

        # DSP Metrics
        if dsp_data:
            self.last_fingerprint_data = dsp_data
            self.dsp_peaks_label.config(text=f"Extracted Spectral Peaks: {dsp_data['num_peaks']:,}")
            self.dsp_hashes_label.config(text=f"Combinatorial Hashes Generated: {dsp_data['num_hashes']:,}")

        if local_match:
            if local_match.get('matched'):
                best = local_match['best_match']
                match_text = f"Matched '{best['song']}' (Coherence: {int(best['coherence_score']*100)}%, {best['coherent_matches']} hashes)"
            else:
                match_text = local_match.get('reason', 'No match in local database.')
            self.dsp_match_label.config(text=f"Local Database Match: {match_text}")

    def load_album_art(self, url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            img_data = io.BytesIO(response.content)
            img = Image.open(img_data)
            img.thumbnail((170, 170))
            tk_image = ImageTk.PhotoImage(img)
            self.root.after(0, self.update_art_label, tk_image)
        except Exception as e:
            print(f"Failed to load album art: {e}")

    def update_art_label(self, tk_image):
        self.album_art_image = tk_image
        self.art_label.config(image=self.album_art_image)

    def clear_results(self):
        self.title_label.config(text="Title: -")
        self.artist_label.config(text="Artist: -")
        self.album_label.config(text="Album: -")
        self.spotify_link_label.config(text="")
        self.spotify_link_label.unbind("<Button-1>")
        self.preview_link_label.config(text="")
        self.preview_link_label.unbind("<Button-1>")
        self.dsp_peaks_label.config(text="Extracted Spectral Peaks: -")
        self.dsp_hashes_label.config(text="Combinatorial Hashes Generated: -")
        self.dsp_match_label.config(text="Local Database Match: -")
        placeholder = Image.new("RGB", (170, 170), (220, 224, 230))
        self.album_art_image = ImageTk.PhotoImage(placeholder)
        self.art_label.config(image=self.album_art_image)

    def open_link(self, url):
        webbrowser.open_new(url)

    # -------------------------------------------------------------------------
    # Visual Spectrogram Window
    # -------------------------------------------------------------------------
    def show_spectrogram_window(self):
        if not self.last_recording_path or not os.path.exists(self.last_recording_path):
            messagebox.showinfo("Spectrogram", "No audio recording available to plot.")
            return

        spec_window = tk.Toplevel(self.root)
        spec_window.title("Acoustic Spectrogram & Constellation Map")
        spec_window.geometry("820x450")

        lbl_loading = ttk.Label(spec_window, text="Rendering Spectrogram & Constellation Peaks...", font=("Segoe UI", 11))
        lbl_loading.pack(expand=True)

        def generate_plot():
            img_path = "temp_spectrogram.png"
            self.fingerprinter.render_spectrogram_plot(self.last_recording_path, img_path)

            def render_in_gui():
                lbl_loading.destroy()
                img = Image.open(img_path)
                img.thumbnail((800, 420))
                tk_spec = ImageTk.PhotoImage(img)
                lbl_img = ttk.Label(spec_window, image=tk_spec)
                lbl_img.image = tk_spec
                lbl_img.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            spec_window.after(0, render_in_gui)

        threading.Thread(target=generate_plot, daemon=True).start()

    def index_current_song(self):
        if not self.last_recording_path or not self.current_song_name:
            messagebox.showwarning("Index Song", "No identified song available to index.")
            return

        res = self.fingerprinter.index_song(self.current_song_name, self.last_recording_path)
        messagebox.showinfo(
            "Indexed to Local Database",
            f"Successfully indexed '{res['song']}'!\n"
            f"Hashes stored: {res['indexed_hashes']:,}\n"
            f"Total unique hashes in database: {res['total_unique_hashes_in_db']:,}"
        )
        self.dsp_match_label.config(text=f"Local Database Match: Indexed as '{self.current_song_name}'")

    # -------------------------------------------------------------------------
    # Microphone Audio Capture
    # -------------------------------------------------------------------------
    def record_audio(self):
        try:
            try:
                default_input = sd.default.device[0]
            except Exception:
                default_input = None

            devices = sd.query_devices()
            if default_input is None or devices[default_input]['max_input_channels'] <= 0:
                err_msg = "No valid microphone input device found. Please check connection and privacy settings."
                self.result_queue.put({'error': err_msg})
                return None

            try:
                sd.check_input_settings(device=default_input, samplerate=self.SAMPLE_RATE, channels=1)
            except Exception as e:
                guidance = "Microphone access failed. On macOS: System Settings → Privacy & Security → Microphone."
                self.result_queue.put({'error': guidance})
                return None

            myrecording = sd.rec(
                int(self.RECORD_DURATION_SEC * self.SAMPLE_RATE),
                samplerate=self.SAMPLE_RATE,
                channels=1,
                dtype='int16'
            )
            sd.wait()
            sf.write(self.RECORDING_FILENAME, myrecording, self.SAMPLE_RATE, subtype='PCM_16')
            return self.RECORDING_FILENAME

        except Exception as e:
            self.result_queue.put({'error': f"Recording error: {e}"})
            return None

    # -------------------------------------------------------------------------
    # Cloud ACRCloud Identification
    # -------------------------------------------------------------------------
    def identify_song(self, file_path):
        config = {
            'host': self.ACRCLOUD_HOST,
            'access_key': self.ACRCLOUD_ACCESS_KEY,
            'access_secret': self.ACRCLOUD_ACCESS_SECRET,
            'timeout': 10
        }
        try:
            recognizer = ACRCloudRecognizer(config)
            result_string = recognizer.recognize_by_file(file_path, start_seconds=0, rec_length=self.RECORD_DURATION_SEC)
            result = json.loads(result_string)

            if result.get('status', {}).get('code') == 0:
                metadata = result['metadata']['music'][0]
                artist = metadata['artists'][0]['name'] if metadata.get('artists') else 'Unknown'
                title = metadata.get('title', 'Unknown')
                album = metadata.get('album', {}).get('name', 'Unknown')

                spotify_id = None
                if 'spotify' in metadata.get('external_metadata', {}):
                    spotify_id = metadata['external_metadata']['spotify']['track'].get('id')

                return {'artist': artist, 'title': title, 'album': album, 'spotify_id': spotify_id}
            else:
                return None

        except Exception as e:
            print(f"ACRCloud recognition error: {e}")
            return None

    # -------------------------------------------------------------------------
    # Spotify Enrichment
    # -------------------------------------------------------------------------
    def get_spotify_details(self, spotify_id):
        if not spotify_id:
            return None
        try:
            auth_manager = SpotifyClientCredentials(
                client_id=self.SPOTIFY_CLIENT_ID,
                client_secret=self.SPOTIFY_CLIENT_SECRET
            )
            sp = spotipy.Spotify(auth_manager=auth_manager)
            track = sp.track(spotify_id)
            return {
                'artist': track['artists'][0]['name'],
                'title': track['name'],
                'album': track['album']['name'],
                'album_art_url': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'preview_url': track.get('preview_url'),
                'spotify_url': track['external_urls']['spotify']
            }
        except Exception as e:
            print(f"Spotify lookup error: {e}")
            return None


if __name__ == "__main__":
    root = tk.Tk()
    app = MusicRecognizerApp(root)
    root.mainloop()
