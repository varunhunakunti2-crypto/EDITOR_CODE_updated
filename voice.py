"""Speech-to-text using the SpeechRecognition library.

The browser records the microphone, converts it to a 16-bit mono WAV and posts it
here; SpeechRecognition then transcribes the file. This needs no PyAudio and no ffmpeg.
"""
import speech_recognition as sr


class VoiceError(Exception):
    """Raised with a message that is safe to show to the user."""


def transcribe_wav(path, language="en-IN"):
    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(path) as source:
            audio = recognizer.record(source)
    except (ValueError, EOFError, OSError) as exc:
        raise VoiceError("Could not read the recording. Please try again.") from exc

    try:
        text = recognizer.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        raise VoiceError("I couldn't understand that. Please speak clearly and try again.")
    except sr.RequestError:
        raise VoiceError("Speech service unreachable. Check your internet connection.")
    return text.strip()
