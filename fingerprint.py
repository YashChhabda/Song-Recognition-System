"""
Acoustic Audio Fingerprinting Engine
====================================
A custom acoustic fingerprinting system inspired by landmark DSP research (Wang / Shazam).
Features:
  1. Audio Signal Preprocessing (mono downmixing, normalization, resampling).
  2. Time-Frequency Analysis via Short-Time Fourier Transform (STFT) & Spectrogram.
  3. Log-scale Frequency Binning and 2D Local Maximum Filtering (Peak Picking / Constellation Map).
  4. Combinatorial Peak Pairing with Target Zone Windowing to generate robust 32-bit hashes.
  5. In-Memory / Persistent Fingerprint Database with Temporal Coherence Matcher (Time-Delta Histogram Peak Detection).
  6. Spectrogram & Constellation Map Visualization exporter.
"""

import os
import json
import hashlib
import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter
import soundfile as sf


class AudioFingerprinter:
    def __init__(
        self,
        sample_rate: int = 44100,
        fft_window_size: int = 4096,
        fft_hop_size: int = 512,
        peak_neighborhood_size: int = 25,
        peak_min_amplitude_percentile: float = 75.0,
        fan_value: int = 15,
        target_t_min: int = 1,
        target_t_max: int = 10,
        target_f_delta: int = 200,
        db_path: str = "fingerprints_db.json"
    ):
        """
        Initialize the Audio Fingerprinter with customizable DSP parameters.

        :param sample_rate: Audio sampling frequency in Hz (default: 44,100 Hz).
        :param fft_window_size: Number of samples per FFT window (default: 4,096).
        :param fft_hop_size: Hop / stride length between successive FFT windows (default: 512).
        :param peak_neighborhood_size: Neighborhood footprint radius for 2D local maximum filtering.
        :param peak_min_amplitude_percentile: Minimum amplitude threshold percentile to suppress low-energy noise.
        :param fan_value: Maximum number of target points paired per anchor peak.
        :param target_t_min: Minimum lookahead time bins for pairing.
        :param target_t_max: Maximum lookahead time bins for pairing.
        :param target_f_delta: Maximum frequency bin difference between anchor and target peak.
        :param db_path: Path to persistent JSON fingerprint database.
        """
        self.sample_rate = sample_rate
        self.fft_window_size = fft_window_size
        self.fft_hop_size = fft_hop_size
        self.peak_neighborhood_size = peak_neighborhood_size
        self.peak_min_amplitude_percentile = peak_min_amplitude_percentile
        self.fan_value = fan_value
        self.target_t_min = target_t_min
        self.target_t_max = target_t_max
        self.target_f_delta = target_f_delta
        self.db_path = db_path

        # Database schema: { hash_key: [ {"song": song_title, "offset": t1_bin}, ... ] }
        self.database = {}
        # Metadata catalog: { song_title: { "num_hashes": int, "duration_sec": float } }
        self.song_catalog = {}

        self.load_database()

    # -------------------------------------------------------------------------
    # 1. Audio Ingestion & Preprocessing
    # -------------------------------------------------------------------------
    def load_audio(self, file_path: str):
        """
        Load an audio file, downmix stereo to mono, and normalize amplitude.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        audio_data, sr = sf.read(file_path, dtype="float32")

        # Downmix multi-channel audio to mono
        if audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)

        # Normalize audio signal to range [-1.0, 1.0]
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            audio_data = audio_data / max_val

        return audio_data, sr

    # -------------------------------------------------------------------------
    # 2. Short-Time Fourier Transform (STFT) & Spectrogram Computation
    # -------------------------------------------------------------------------
    def compute_spectrogram(self, audio_data: np.ndarray, sr: int):
        """
        Compute the power spectrogram using STFT with a Hann window.
        Returns:
            frequencies: Array of frequency bin centers.
            times: Array of segment time centers.
            spectrogram_db: 2D array of logarithmic power amplitudes in dB.
        """
        frequencies, times, spec = signal.spectrogram(
            audio_data,
            fs=sr,
            window="hann",
            nperseg=self.fft_window_size,
            noverlap=self.fft_window_size - self.fft_hop_size,
            mode="magnitude"
        )

        # Convert to logarithmic scale (decibels) to mimic human perceptual loudness
        with np.errstate(divide="ignore"):
            spec_db = 20 * np.log10(np.maximum(spec, 1e-6))

        return frequencies, times, spec_db

    # -------------------------------------------------------------------------
    # 3. Peak Picking & Constellation Map Extraction
    # -------------------------------------------------------------------------
    def extract_peaks(self, spec_db: np.ndarray):
        """
        Extract prominent local energy peaks (Constellation Map) from the spectrogram.
        Applies a 2D local maximum filter and filters out points below the amplitude threshold.
        Returns:
            peaks: List of tuples [(time_idx, freq_idx), ...] sorted chronologically.
        """
        # 2D maximum filter over the neighborhood footprint
        filter_size = self.peak_neighborhood_size
        local_max = maximum_filter(spec_db, size=(filter_size, filter_size)) == spec_db

        # Suppress noise by applying amplitude threshold
        threshold = np.percentile(spec_db, self.peak_min_amplitude_percentile)
        detected_peaks = local_max & (spec_db > threshold)

        # Extract (frequency_idx, time_idx) coordinates
        freq_indices, time_indices = np.where(detected_peaks)

        # Structure as [(time_idx, freq_idx)] and sort by time
        peaks = sorted(zip(time_indices, freq_indices), key=lambda pt: (pt[0], pt[1]))
        return peaks

    # -------------------------------------------------------------------------
    # 4. Combinatorial Hashing
    # -------------------------------------------------------------------------
    def generate_hashes(self, peaks):
        """
        Combinatorially pair anchor peaks with target zone peaks to generate hashes.
        For an anchor peak (t1, f1), search subsequent peaks (t2, f2) where:
            target_t_min <= (t2 - t1) <= target_t_max
            |f2 - f1| <= target_f_delta
        Returns:
            hashes: List of tuples [(hash_str, anchor_time_idx), ...]
        """
        hashes = []
        num_peaks = len(peaks)

        for i in range(num_peaks):
            t1, f1 = peaks[i]
            paired_count = 0

            for j in range(i + 1, num_peaks):
                t2, f2 = peaks[j]
                delta_t = t2 - t1

                if delta_t < self.target_t_min:
                    continue
                if delta_t > self.target_t_max:
                    # Beyond lookahead window, stop inner loop
                    break

                if abs(f2 - f1) <= self.target_f_delta:
                    # Create compact, collision-resistant acoustic hash key
                    # Format: f1:f2:delta_t -> MD5/SHA1 truncated to 12 hex chars
                    raw_token = f"{f1}:{f2}:{delta_t}".encode("utf-8")
                    hash_str = hashlib.sha1(raw_token).hexdigest()[:12]
                    hashes.append((hash_str, int(t1)))

                    paired_count += 1
                    if paired_count >= self.fan_value:
                        break

        return hashes

    # -------------------------------------------------------------------------
    # 5. Full Fingerprinting Pipeline for Audio
    # -------------------------------------------------------------------------
    def fingerprint_audio(self, audio_data: np.ndarray, sr: int):
        """
        End-to-end fingerprint extraction: STFT -> Peaks -> Hashes.
        """
        frequencies, times, spec_db = self.compute_spectrogram(audio_data, sr)
        peaks = self.extract_peaks(spec_db)
        hashes = self.generate_hashes(peaks)
        return {
            "num_peaks": len(peaks),
            "num_hashes": len(hashes),
            "hashes": hashes,
            "peaks": peaks,
            "spectrogram_shape": spec_db.shape,
            "duration_sec": len(audio_data) / sr
        }

    def fingerprint_file(self, file_path: str):
        """
        Fingerprints an audio file by path.
        """
        audio_data, sr = self.load_audio(file_path)
        return self.fingerprint_audio(audio_data, sr)

    # -------------------------------------------------------------------------
    # 6. Database Indexing
    # -------------------------------------------------------------------------
    def index_song(self, song_title: str, file_path: str):
        """
        Index a new song into the local fingerprint database.
        """
        data = self.fingerprint_file(file_path)
        hashes = data["hashes"]

        for hash_val, offset in hashes:
            if hash_val not in self.database:
                self.database[hash_val] = []
            self.database[hash_val].append({"song": song_title, "offset": offset})

        self.song_catalog[song_title] = {
            "num_hashes": len(hashes),
            "num_peaks": data["num_peaks"],
            "duration_sec": round(data["duration_sec"], 2)
        }

        self.save_database()
        return {
            "song": song_title,
            "indexed_hashes": len(hashes),
            "total_unique_hashes_in_db": len(self.database)
        }

    # -------------------------------------------------------------------------
    # 7. Temporal Coherence Matching (Time-Delta Histogram Peak Alignment)
    # -------------------------------------------------------------------------
    def match_audio(self, query_file_path: str, min_matches: int = 5):
        """
        Identify a query audio recording against the indexed database.
        Calculates time difference delta: (offset_in_db - offset_in_query).
        True matches cluster at a single delta value (temporal alignment peak),
        effectively filtering out random noise hash collisions.
        """
        if not self.database:
            return {
                "matched": False,
                "reason": "Database is empty. Index songs first.",
                "candidates": []
            }

        query_result = self.fingerprint_file(query_file_path)
        query_hashes = query_result["hashes"]

        # Track delta counts per candidate song: { song_title: { delta_offset: count } }
        matches_per_song = {}

        for hash_val, query_offset in query_hashes:
            if hash_val in self.database:
                for match_record in self.database[hash_val]:
                    song = match_record["song"]
                    db_offset = match_record["offset"]
                    delta = db_offset - query_offset

                    if song not in matches_per_song:
                        matches_per_song[song] = {}
                    matches_per_song[song][delta] = matches_per_song[song].get(delta, 0) + 1

        if not matches_per_song:
            return {
                "matched": False,
                "reason": "No acoustic hash matches found in local database.",
                "query_peaks": query_result["num_peaks"],
                "query_hashes": query_result["num_hashes"],
                "candidates": []
            }

        # Find the peak delta count for each candidate song
        candidates = []
        for song, delta_histogram in matches_per_song.items():
            best_delta, highest_bin_count = max(delta_histogram.items(), key=lambda item: item[1])
            total_matches = sum(delta_histogram.values())
            # Confidence score: temporal cluster coherence ratio
            coherence_score = highest_bin_count / max(1, total_matches)

            candidates.append({
                "song": song,
                "coherent_matches": highest_bin_count,
                "total_hash_collisions": total_matches,
                "coherence_score": round(coherence_score, 3),
                "aligned_offset_diff": best_delta
            })

        # Sort candidate matches by highest coherent bin matches
        candidates.sort(key=lambda c: c["coherent_matches"], reverse=True)
        best_candidate = candidates[0]

        is_matched = best_candidate["coherent_matches"] >= min_matches

        return {
            "matched": is_matched,
            "best_match": best_candidate if is_matched else None,
            "query_peaks": query_result["num_peaks"],
            "query_hashes": query_result["num_hashes"],
            "candidates": candidates[:5]
        }

    # -------------------------------------------------------------------------
    # 8. Database Persistence
    # -------------------------------------------------------------------------
    def save_database(self, filepath: str = None):
        """Save database and catalog to a JSON file."""
        target = filepath or self.db_path
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump({
                    "catalog": self.song_catalog,
                    "database": self.database
                }, f)
        except Exception as e:
            print(f"Warning: could not save fingerprint database: {e}")

    def load_database(self, filepath: str = None):
        """Load database and catalog from a JSON file if present."""
        target = filepath or self.db_path
        if os.path.exists(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    self.song_catalog = content.get("catalog", {})
                    self.database = content.get("database", {})
            except Exception as e:
                print(f"Warning: could not load fingerprint database: {e}")

    # -------------------------------------------------------------------------
    # 9. Spectrogram & Constellation Map Visualization Exporter
    # -------------------------------------------------------------------------
    def render_spectrogram_plot(self, file_path: str, output_image_path: str = "spectrogram_constellation.png"):
        """
        Generate and save a visual spectrogram with constellation peak overlay.
        """
        import matplotlib
        matplotlib.use("Agg")  # Headless backend
        import matplotlib.pyplot as plt

        audio_data, sr = self.load_audio(file_path)
        freqs, times, spec_db = self.compute_spectrogram(audio_data, sr)
        peaks = self.extract_peaks(spec_db)

        fig, ax = plt.subplots(figsize=(10, 5), dpi=120)
        fig.patch.set_facecolor("#121212")
        ax.set_facecolor("#121212")

        # Plot Spectrogram
        extent = [times[0], times[-1], freqs[0], freqs[-1]]
        im = ax.imshow(
            spec_db,
            aspect="auto",
            origin="lower",
            extent=extent,
            cmap="inferno"
        )

        # Overlay Constellation Peaks
        if peaks:
            peak_times = [times[p[0]] for p in peaks if p[0] < len(times)]
            peak_freqs = [freqs[p[1]] for p in peaks if p[1] < len(freqs)]
            ax.scatter(peak_times, peak_freqs, color="#00ffcc", s=10, alpha=0.85, label="Acoustic Peaks")

        ax.set_title("Audio Spectrogram & Extracted Constellation Peaks", color="#ffffff", fontsize=12, pad=10)
        ax.set_xlabel("Time (seconds)", color="#cccccc")
        ax.set_ylabel("Frequency (Hz)", color="#cccccc")
        ax.set_ylim(0, min(8000, sr // 2))  # Focus on key audio frequency range
        ax.tick_params(colors="#aaaaaa")
        for spine in ax.spines.values():
            spine.set_color("#444444")

        cbar = fig.colorbar(im, ax=ax, orientation="vertical", pad=0.02)
        cbar.set_label("Magnitude (dB)", color="#cccccc")
        cbar.ax.yaxis.set_tick_params(color="#aaaaaa")
        plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="#aaaaaa")

        plt.tight_layout()
        plt.savefig(output_image_path, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)
        return output_image_path


if __name__ == "__main__":
    print("Initializing AudioFingerprinter...")
    fingerprinter = AudioFingerprinter()
    print("AudioFingerprinter ready.")
