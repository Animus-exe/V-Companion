I wrote this ages ago as a joke but now companions are a big deal i am open sourcing it 

I hardly recall much about it so its in your hands now


# Misa — VTuber AI Assistant

Misa is a voice-driven VTuber assistant that listens, talks back, emotes in real-time, and can be interrupted mid-sentence like a true live companion.  
It integrates **speech recognition (Vosk)**, **speech synthesis (Google TTS)**, **local LLMs via Ollama**, and **VTube Studio expressions**.

---

## ✨ Features
- 🎤 Real-time speech recognition with [Vosk](https://alphacephei.com/vosk/)  
- 🔊 Natural speech playback via Google Cloud TTS (Wavenet voices)  
- 🧠 Local AI responses using [Ollama](https://ollama.com) + LLaMA 2  
- 🎭 Dynamic facial expressions in VTube Studio (happy, sad, confused, neutral + chained emotes)  
- ⏸️ Mic pause during playback to prevent feedback loops  
- 🗣️ True barge-in (say *"Misa"* or *"shut up"* to interrupt her speech instantly)  
- 🎲 Random startup greetings for a more natural vibe  

---

## 📦 Requirements

### Python Packages
Install required dependencies:

⚠️ pyaudio may require system audio libraries (e.g., brew install portaudio on macOS, sudo apt install portaudio19-dev on Linux).

Runtime Dependencies

VTube Studio
 (API enabled, your model loaded)

Ollama 
 running locally with llama2:7b pulled 

"ollama pull llama2:7b"

Google Cloud Text-to-Speech API key set in environment:

"export GOOGLE_TTS_API_KEY="your_key_here"



Vosk Model

The script will auto-download the small English model if missing:
vosk-model-small-en-us-0.15 (~50 MB). ( https://alphacephei.com/vosk/models )

▶️ Usage

Run the assistant:

"python misa_assistant.py"


Make sure:

Your microphone is active.

VTube Studio is open with the API enabled.

Ollama is running (ollama serve).

The GOOGLE_TTS_API_KEY environment variable is set.



🎮 Controls

Speak naturally; Misa will respond in real time.

Interrupt her at any time by saying:

"Misa"

"Meesa"

"Shut up"


🛠️ Configuration

Microphone Device
The default input is used. To force a specific device, set:
VB_CABLE_INDEX = 2


TTS Voice Settings
Modify GoogleTTS.speak() for pitch, speed, or voice name.
