"""Shared native eSpeak conversion without model or playback dependencies."""

import ctypes
from functools import lru_cache
from pathlib import Path
import threading


_ESPEAK_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _espeak_library() -> ctypes.CDLL:
    # Called under _ESPEAK_LOCK: eSpeak's voice and text cursor are process-global.
    import espeakng_loader

    library = ctypes.CDLL(espeakng_loader.get_library_path())
    library.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    library.espeak_Initialize.restype = ctypes.c_int
    library.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
    library.espeak_SetVoiceByName.restype = ctypes.c_int
    library.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_int, ctypes.c_int]
    library.espeak_TextToPhonemes.restype = ctypes.c_char_p
    # Synchronous conversion only; never open an audio output. DONT_EXIT makes
    # missing packaged data an ordinary failure instead of terminating Magi.
    data_root = str(Path(espeakng_loader.get_data_path()).parent).encode("utf-8")
    if library.espeak_Initialize(2, 0, data_root, 0x8000) <= 0:
        raise ValueError("runtime_missing")
    if library.espeak_SetVoiceByName(b"en-us") != 0:
        raise ValueError("runtime_missing")
    return library


def english_phonemes(text: str) -> str:
    """Convert English to IPA without opening playback or interpreting SSML."""
    if "\x00" in text:
        raise ValueError("unsupported_text")
    with _ESPEAK_LOCK:
        library = _espeak_library()
        buffer = ctypes.create_string_buffer(text.encode("utf-8"))
        cursor = ctypes.c_void_p(ctypes.addressof(buffer))
        result = []
        while cursor.value:
            previous = cursor.value
            # UTF-8 text, IPA phonemes. Copy the native result before the next call.
            phonemes = library.espeak_TextToPhonemes(ctypes.byref(cursor), 1, 2)
            if phonemes is None or cursor.value == previous:
                raise ValueError("invalid_audio")
            result.append(phonemes.decode("utf-8"))
        return " ".join(result).strip()
