import sys
import asyncio
import json
import os
import time
import base64
import tempfile
import re
import requests
import random
from difflib import SequenceMatcher
from pydub import AudioSegment
import simpleaudio as sa
import pyvts
import ollama
import pyaudio
import vosk
from textblob import TextBlob
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

is_speaking = False
last_spoken_text = ""

def is_similar(a, b, threshold=0.8):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= threshold

VB_CABLE_INDEX = None

GOOGLE_TTS_API_KEY = os.getenv("GOOGLE_TTS_API_KEY", "")
GOOGLE_TTS_ENDPOINT = (
    f"https://texttospeech.googleapis.com/v1/text:synthesize?key={GOOGLE_TTS_API_KEY}"
    if GOOGLE_TTS_API_KEY else None
)

class VTubeController:
    def __init__(self, ws_url="ws://0.0.0.0:8001"):
        plugin_info = {
            "plugin_name": "VTuber Assistant",
            "developer": "System",
            "authentication_token_path": "vts_token.txt"
        }
        self.vts = pyvts.vts(plugin_info=plugin_info, ws_url=ws_url)
        self.hotkeys = {}
    async def connect(self):
        await self.vts.connect()
        await self.vts.request_authenticate_token()
        await self.vts.request_authenticate()
        await self.get_hotkeys()
    async def get_hotkeys(self):
        resp = await self.vts.request(self.vts.vts_request.requestHotKeyList())
        self.hotkeys = {hk["name"]: hk for hk in resp["data"]["availableHotkeys"]}
    async def trigger_expression(self, expression):
        hotkey = expression if expression and expression.strip() else "Remove Expressions"
        try:
            await self.vts.request(self.vts.vts_request.requestTriggerHotKey(hotkey))
        except Exception as e:
            print(f"[Warning] trigger_expression '{hotkey}': {e}")
    async def disconnect(self):
        try:
            await self.vts.close()
        except Exception as e:
            print(f"[Warning] disconnect: {e}")

async def perform_enhanced_emotes(vts, sentiment):
    try:
        if sentiment == "happy":
            await vts.trigger_expression("blush")
            await asyncio.sleep(0.3)
            await vts.trigger_expression("wink")
            await asyncio.sleep(0.3)
            await vts.trigger_expression("smile")
        elif sentiment == "sad":
            await vts.trigger_expression("look_down")
        elif sentiment == "confused":
            await vts.trigger_expression("look_up")
        else:
            await vts.trigger_expression("blink")
    except Exception as e:
        print(f"[Warning] emotes: {e}")

def sanitize_response(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"\*[^*]+\*", "", text).strip()
    return text

class VoiceRecognition:
    def __init__(self):
        model_path = "vosk-model-small-en-us-0.15"
        if not os.path.exists(model_path):
            os.system("wget -q https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip -o vosk-model-small-en-us-0.15.zip")
        self.model = vosk.Model(model_path)
        self.audio = pyaudio.PyAudio()
        info = self.audio.get_default_input_device_info()
        self.sample_rate = int(info.get("defaultSampleRate", 16000))
        self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        self.recognizer.SetWords(False)
        self.recognizer.SetPartialWords(False)
        if VB_CABLE_INDEX is not None:
            self.stream = self.audio.open(format=pyaudio.paInt16, channels=1, rate=self.sample_rate, input=True, frames_per_buffer=2048, input_device_index=VB_CABLE_INDEX)
        else:
            self.stream = self.audio.open(format=pyaudio.paInt16, channels=1, rate=self.sample_rate, input=True, frames_per_buffer=2048)
        self.stream.start_stream()
    def pause(self):
        if self.stream is not None and not self.stream.is_stopped():
            self.stream.stop_stream()
    def resume(self):
        if self.stream is not None and self.stream.is_stopped():
            self.stream.start_stream()
    def listen(self):
        final_text = ""
        timeout = 2.5
        start_time = time.time()
        last_time = time.time()
        while True:
            try:
                data = self.stream.read(2048, exception_on_overflow=False)
            except Exception as e:
                print(f"[Error] audio read: {e}")
                break
            if len(data) == 0:
                break
            try:
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get("text", "").strip()
                    if text:
                        final_text += " " + text
                        last_time = time.time()
                else:
                    partial_json = json.loads(self.recognizer.PartialResult())
                    partial_text = partial_json.get("partial", "").strip()
                    if partial_text:
                        last_time = time.time()
            except AssertionError:
                continue
            if final_text and (time.time() - last_time > timeout):
                break
            if not final_text and (time.time() - start_time > 1.0):
                break
        return final_text.strip()

async def background_listen(recognizer, queue):
    global is_speaking, last_spoken_text
    while True:
        text = await asyncio.to_thread(recognizer.listen)
        if text:
            lower = text.lower().strip()
            if is_speaking and last_spoken_text and is_similar(lower, last_spoken_text):
                continue
            if is_speaking and not ("misa" in lower or "meesa" in lower or "shut up" in lower):
                continue
            await queue.put(text)
        await asyncio.sleep(0.1)

class AIAssistant:
    def __init__(self):
        self.model = "llama2:7b"
        self.personality = (
            "You are Misa, a sharp, loyal assistant with edge. "
            "Be succinct, direct, and helpful."
        )
    def get_response(self, user_input):
        try:
            full_prompt = self.personality + "\nUser: " + user_input
            resp = ollama.generate(model=self.model, prompt=full_prompt)
            ai_text = resp['response'].strip()
            return sanitize_response(ai_text)
        except Exception as e:
            print(f"[Error] ollama: {e}")
            return "I couldn't process that."

class GoogleTTS:
    def __init__(self):
        self.playback = None
    def speak(self, text):
        if not GOOGLE_TTS_ENDPOINT:
            print("[Error] TTS not configured")
            return
        try:
            payload = {
                "input": {"text": text},
                "voice": {"languageCode": "en-US", "name": "en-US-Wavenet-F", "ssmlGender": "FEMALE"},
                "audioConfig": {"audioEncoding": "MP3", "pitch": -2.0, "speakingRate": 1.0}
            }
            r = requests.post(GOOGLE_TTS_ENDPOINT, json=payload)
            if r.status_code != 200:
                print(f"[Error] TTS {r.status_code}: {r.text}")
                return
            audio_content = r.json().get("audioContent")
            if not audio_content:
                return
            audio_data = base64.b64decode(audio_content)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as out:
                out.write(audio_data)
                temp_mp3 = out.name
            seg = AudioSegment.from_file(temp_mp3, format="mp3")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_out:
                temp_wav = wav_out.name
            seg.export(temp_wav, format="wav")
            wave_obj = sa.WaveObject.from_wave_file(temp_wav)
            self.playback = wave_obj.play()
            self.playback.wait_done()
            os.remove(temp_mp3)
            os.remove(temp_wav)
            self.playback = None
        except Exception as e:
            print(f"[Error] TTS: {e}")

async def async_speak(tts, text, recognizer=None):
    global is_speaking, last_spoken_text
    last_spoken_text = text.strip()
    is_speaking = True
    if recognizer is not None:
        recognizer.pause()
    await asyncio.to_thread(tts.speak, text)
    if recognizer is not None:
        recognizer.resume()
    is_speaking = False
    last_spoken_text = ""

class AssistantThread(QThread):
    def run(self):
        asyncio.run(run_assistant())

async def run_assistant():
    vts = VTubeController(ws_url="ws://0.0.0.0:8001")
    await vts.connect()
    recognizer = VoiceRecognition()
    tts = GoogleTTS()
    greetings = [
        "Systems online. How can I help?",
        "Online and listening. What do you need?",
        "Ready. Say the word."
    ]
    greeting = random.choice(greetings)
    await async_speak(tts, greeting, recognizer)
    await vts.trigger_expression("Heart Eyes")
    input_queue = asyncio.Queue()
    asyncio.create_task(background_listen(recognizer, input_queue))
    ai = AIAssistant()
    try:
        ai.get_response("Hello")
    except Exception as e:
        print(f"[Error] model warmup: {e}")
    expressions_map = {
        "happy": "Heart Eyes",
        "sad": "Angry Sign",
        "confused": "Shock Sign",
        "neutral": "Remove Expressions"
    }
    while True:
        try:
            user_text = input_queue.get_nowait()
        except asyncio.QueueEmpty:
            user_text = ""
        if not user_text:
            user_text = recognizer.listen()
        if not user_text:
            await async_speak(tts, "I didn't catch that. Please repeat.", recognizer)
            await asyncio.sleep(0.1)
            continue
        if len(user_text.split()) < 2:
            await async_speak(tts, "Please elaborate.", recognizer)
            continue
        print(f"You: {user_text}")
        ai_response = ai.get_response(user_text)
        print(f"Misa: {ai_response}")
        polarity = TextBlob(ai_response).sentiment.polarity
        if polarity > 0.4:
            sentiment = "happy"
        elif polarity < -0.4:
            sentiment = "sad"
        elif "?" in ai_response:
            sentiment = "confused"
        else:
            sentiment = "neutral"
        hotkey = expressions_map.get(sentiment, "Remove Expressions")
        await vts.trigger_expression(hotkey)
        await perform_enhanced_emotes(vts, sentiment)
        tts_task = asyncio.create_task(async_speak(tts, ai_response, recognizer))
        while not tts_task.done():
            try:
                new_input = input_queue.get_nowait()
                if new_input:
                    lower = new_input.lower()
                    if "shut up" in lower or "misa" in lower or "meesa" in lower:
                        if tts.playback is not None:
                            tts.playback.stop()
                        await vts.trigger_expression("Angry Sign")
                        await async_speak(tts, "Okay.", recognizer)
                        tts_task.cancel()
                        break
            except asyncio.QueueEmpty:
                pass
            await asyncio.sleep(0.1)
        await vts.trigger_expression("Remove Expressions")
        await asyncio.sleep(0.05)

if __name__ == "__main__":
    print("Starting Misa…")
    app = QApplication(sys.argv)
    t = AssistantThread()
    t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting.")
