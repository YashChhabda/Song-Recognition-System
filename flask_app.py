"""
Song Recognition System - Flask Web Dashboard
==============================================
A Flask web application and REST API offering:
- In-browser microphone audio recording & audio file upload.
- Cloud recognition (ACRCloud + Spotify API enrichment).
- Local Custom DSP Acoustic Fingerprinting (STFT Spectrogram, Constellation Peak Picking,
  Combinatorial Hashing, and Histogram Time-Delta Matching).
"""

import os
import json
import tempfile
from flask import Flask, render_template, request, jsonify, send_file
from fingerprint import AudioFingerprinter
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from acrcloud.recognizer import ACRCloudRecognizer

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload

# Initialize Fingerprinter
DB_PATH = os.path.join(os.path.dirname(__file__), "fingerprints_db.json")
fingerprinter = AudioFingerprinter(db_path=DB_PATH)

# Cloud Credentials
ACRCLOUD_HOST = os.getenv('ACRCLOUD_HOST', 'identify-ap-southeast-1.acrcloud.com')
ACRCLOUD_ACCESS_KEY = os.getenv('ACRCLOUD_ACCESS_KEY', '65365a6d4d2d133fad5ed94e39d61086')
ACRCLOUD_ACCESS_SECRET = os.getenv('ACRCLOUD_ACCESS_SECRET', 'x0jRjc5h76A4amsXDgLh9C37A1WNg4xO7irCPvfb')
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '82df22cf76bf45b49aee5d30f1faa8d3')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', 'dacdd714badb4feaa7fc7be4bf8d0541')

LAST_SPECTROGRAM_PATH = os.path.join(tempfile.gettempdir(), "last_spectrogram.png")


def run_acrcloud_recognition(audio_path):
    config = {
        'host': ACRCLOUD_HOST,
        'access_key': ACRCLOUD_ACCESS_KEY,
        'access_secret': ACRCLOUD_ACCESS_SECRET,
        'timeout': 10
    }
    try:
        recognizer = ACRCloudRecognizer(config)
        result_string = recognizer.recognize_by_file(audio_path, start_seconds=0, rec_length=10)
        res = json.loads(result_string)
        if res.get('status', {}).get('code') == 0:
            music = res['metadata']['music'][0]
            artist = music['artists'][0]['name'] if music.get('artists') else 'Unknown'
            title = music.get('title', 'Unknown')
            album = music.get('album', {}).get('name', 'Unknown')
            spotify_id = None
            if 'spotify' in music.get('external_metadata', {}):
                spotify_id = music['external_metadata']['spotify']['track'].get('id')
            return {'artist': artist, 'title': title, 'album': album, 'spotify_id': spotify_id}
    except Exception as e:
        print(f"ACRCloud Error: {e}")
    return None


def get_spotify_metadata(spotify_id):
    if not spotify_id:
        return None
    try:
        auth_mgr = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
        sp = spotipy.Spotify(auth_manager=auth_mgr)
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
        print(f"Spotify Error: {e}")
        return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/recognize', methods=['POST'])
def recognize():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio file provided in form-data key "audio"'}), 400

    audio_file = request.files['audio']
    temp_path = os.path.join(tempfile.gettempdir(), f"upload_{os.getpid()}_{audio_file.filename}")
    audio_file.save(temp_path)

    try:
        # 1. Custom DSP Fingerprinting
        dsp_fingerprint = fingerprinter.fingerprint_file(temp_path)
        local_match = fingerprinter.match_audio(temp_path)

        # 2. Render Spectrogram for web display
        try:
            fingerprinter.render_spectrogram_plot(temp_path, LAST_SPECTROGRAM_PATH)
            has_spectrogram = True
        except Exception:
            has_spectrogram = False

        # 3. Cloud ACRCloud Identification
        cloud_data = run_acrcloud_recognition(temp_path)

        # 4. Spotify metadata
        spotify_data = None
        if cloud_data and cloud_data.get('spotify_id'):
            spotify_data = get_spotify_metadata(cloud_data['spotify_id'])

        return jsonify({
            'success': True,
            'cloud_recognition': cloud_data,
            'spotify': spotify_data,
            'dsp_metrics': {
                'peaks_extracted': dsp_fingerprint['num_peaks'],
                'hashes_generated': dsp_fingerprint['num_hashes'],
                'duration_sec': round(dsp_fingerprint['duration_sec'], 2),
                'local_match': local_match
            },
            'has_spectrogram': has_spectrogram
        })
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@app.route('/api/spectrogram', methods=['GET'])
def get_spectrogram():
    if os.path.exists(LAST_SPECTROGRAM_PATH):
        return send_file(LAST_SPECTROGRAM_PATH, mimetype='image/png')
    return jsonify({'error': 'No spectrogram generated yet'}), 404


@app.route('/api/index', methods=['POST'])
def index_track():
    if 'audio' not in request.files or 'title' not in request.form:
        return jsonify({'error': 'Fields "audio" (file) and "title" (string) are required.'}), 400

    title = request.form['title']
    audio_file = request.files['audio']
    temp_path = os.path.join(tempfile.gettempdir(), f"index_{audio_file.filename}")
    audio_file.save(temp_path)

    try:
        res = fingerprinter.index_song(title, temp_path)
        return jsonify({
            'success': True,
            'result': res
        })
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    return jsonify({
        'total_songs': len(fingerprinter.song_catalog),
        'catalog': fingerprinter.song_catalog
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    print(f"Starting Flask Music Recognizer on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
