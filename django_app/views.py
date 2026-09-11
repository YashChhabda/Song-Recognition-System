"""
Django views for Song Recognition System.
"""

import os
import tempfile
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from fingerprint import AudioFingerprinter

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fingerprints_db.json")
fingerprinter = AudioFingerprinter(db_path=DB_PATH)


@csrf_exempt
def recognize_view(request):
    """
    POST /api/recognize/
    Analyzes uploaded audio and returns DSP acoustic fingerprints + match results.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    if 'audio' not in request.FILES:
        return JsonResponse({'error': 'No audio file uploaded under key "audio"'}, status=400)

    audio_file = request.FILES['audio']
    temp_path = os.path.join(tempfile.gettempdir(), f"django_{audio_file.name}")

    with open(temp_path, 'wb+') as destination:
        for chunk in audio_file.chunks():
            destination.write(chunk)

    try:
        dsp_data = fingerprinter.fingerprint_file(temp_path)
        local_match = fingerprinter.match_audio(temp_path)

        return JsonResponse({
            'success': True,
            'peaks_extracted': dsp_data['num_peaks'],
            'hashes_generated': dsp_data['num_hashes'],
            'duration_sec': round(dsp_data['duration_sec'], 2),
            'local_match': local_match
        })
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@csrf_exempt
def index_view(request):
    """
    POST /api/index/
    Indexes an uploaded track with a given title into the local fingerprint database.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    title = request.POST.get('title')
    if not title or 'audio' not in request.FILES:
        return JsonResponse({'error': 'Both "title" and "audio" are required.'}, status=400)

    audio_file = request.FILES['audio']
    temp_path = os.path.join(tempfile.gettempdir(), f"django_index_{audio_file.name}")

    with open(temp_path, 'wb+') as destination:
        for chunk in audio_file.chunks():
            destination.write(chunk)

    try:
        res = fingerprinter.index_song(title, temp_path)
        return JsonResponse({'success': True, 'indexed': res})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def catalog_view(request):
    """
    GET /api/catalog/
    Returns list of indexed tracks in database.
    """
    return JsonResponse({
        'total_songs': len(fingerprinter.song_catalog),
        'catalog': fingerprinter.song_catalog
    })
