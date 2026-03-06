# main.py - OmniTutor with Gemini 2.5 Flash-Lite (July 2025)
import os
import sys
import subprocess
import logging
import asyncio
import base64
import json
import uuid
from typing import Dict
import io

# Auto-install dependencies if missing
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
except ModuleNotFoundError:
    print("📦 Installing missing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

import google.generativeai as genai
from google.cloud import texttospeech, vision
from PIL import Image
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="OmniTutor", description="Live AI Tutor with Gemini 2.5")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create static directory
os.makedirs("static", exist_ok=True)

# ============================================
# GEMINI 2.5 SETUP - CORRECT MODEL NAMES
# ============================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("❌ GEMINI_API_KEY not set in environment variables")
    logger.error("Please add it in Replit Secrets (Tools → Secrets)")
    # Don't exit, but models will be None
else:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Gemini API configured")

# Initialize Gemini 2.5 models (from your screenshot)
try:
    if GEMINI_API_KEY:
        # Gemini 2.5 Flash-Lite - Latest July 2025 model
        # This single model handles BOTH text and vision!
        model_name = 'models/gemini-2.5-flash-lite'
        logger.info(f"🚀 Loading Gemini model: {model_name}")

        # Create the model
        model = genai.GenerativeModel(model_name)

        # Test the model with a simple prompt
        test_response = model.generate_content("Hello, I am OmniTutor. Respond with '✅ Gemini 2.5 ready'")
        logger.info(f"✅ Model test successful: {test_response.text}")

        # Use same model for both text and vision (2.5 is multimodal)
        live_model = model
        vision_model = model

        logger.info("🎉 Gemini 2.5 Flash-Lite loaded successfully (July 2025)")
    else:
        live_model = None
        vision_model = None
        logger.error("❌ Cannot load models: No API key")

except Exception as e:
    logger.error(f"❌ Error loading Gemini 2.5: {e}")
    logger.info("🔄 Trying fallback models...")

    # Fallback options if 2.5 fails
    fallback_models = [
        'models/gemini-2.0-flash',
        'models/gemini-1.5-flash',
        'gemini-pro'
    ]

    live_model = None
    vision_model = None

    for fallback in fallback_models:
        try:
            logger.info(f"Trying {fallback}...")
            model = genai.GenerativeModel(fallback)
            test_response = model.generate_content("test")
            live_model = model
            vision_model = model if 'vision' in fallback or 'pro' in fallback else model
            logger.info(f"✅ Using fallback model: {fallback}")
            break
        except:
            continue

# Store active WebSocket connections
active_connections: Dict[str, WebSocket] = {}

# ============================================
# HTML FRONTEND (with Gemini 2.5 optimized UI)
# ============================================
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OmniTutor - Live AI Tutor with Gemini 2.5</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            max-width: 800px;
            width: 100%;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .header p { opacity: 0.9; }
        .badge {
            display: inline-block;
            padding: 5px 10px;
            background: rgba(255,255,255,0.2);
            border-radius: 20px;
            font-size: 12px;
            margin-top: 10px;
        }
        .status-badge {
            display: inline-block;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            margin-top: 10px;
        }
        .status-connected { background: #4CAF50; color: white; }
        .status-disconnected { background: #f44336; color: white; animation: pulse 2s infinite; }
        .status-thinking { background: #FF9800; color: white; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.7; } 100% { opacity: 1; } }
        .chat-container {
            height: 400px;
            overflow-y: auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .message {
            margin-bottom: 15px;
            display: flex;
        }
        .user-message { justify-content: flex-end; }
        .ai-message { justify-content: flex-start; }
        .message-bubble {
            max-width: 70%;
            padding: 12px 18px;
            border-radius: 20px;
            font-size: 14px;
            line-height: 1.4;
            word-wrap: break-word;
        }
        .user-message .message-bubble {
            background: #667eea;
            color: white;
            border-bottom-right-radius: 5px;
        }
        .ai-message .message-bubble {
            background: white;
            color: #333;
            border-bottom-left-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .input-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #eee;
        }
        .mic-button {
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            color: white;
            font-size: 24px;
            cursor: pointer;
            margin: 0 auto 20px;
            display: block;
            transition: transform 0.2s;
        }
        .mic-button:hover { transform: scale(1.1); }
        .mic-button.listening {
            animation: pulse 1.5s infinite;
            background: #f44336;
        }
        .text-input {
            display: flex;
            gap: 10px;
        }
        .text-input input {
            flex: 1;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 10px;
            font-size: 14px;
            outline: none;
        }
        .text-input input:focus {
            border-color: #667eea;
        }
        .text-input button {
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border: none;
            border-radius: 10px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: opacity 0.2s;
        }
        .text-input button:hover { opacity: 0.9; }
        .text-input button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .image-upload {
            margin-top: 10px;
            text-align: center;
        }
        .image-upload input { display: none; }
        .image-upload label {
            display: inline-block;
            padding: 8px 16px;
            background: #f0f0f0;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.2s;
        }
        .image-upload label:hover {
            background: #e0e0e0;
        }
        .image-preview {
            max-width: 200px;
            max-height: 200px;
            margin: 10px auto;
            display: none;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .model-info {
            font-size: 12px;
            color: #666;
            text-align: center;
            margin-top: 5px;
            padding: 5px;
            background: #f8f9fa;
            border-radius: 5px;
        }
        .thinking-indicator {
            display: flex;
            gap: 5px;
            padding: 12px 18px;
            background: white;
            border-radius: 20px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            width: fit-content;
        }
        .thinking-indicator span {
            width: 8px;
            height: 8px;
            background: #999;
            border-radius: 50%;
            animation: bounce 1.5s infinite;
        }
        .thinking-indicator span:nth-child(2) { animation-delay: 0.2s; }
        .thinking-indicator span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-10px); }
        }
        .math-display {
            font-family: 'Courier New', monospace;
            background: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎓 OmniTutor</h1>
            <p>Powered by Gemini 2.5 Flash-Lite (July 2025)</p>
            <div class="badge">Multimodal • Real-time • Smart</div>
            <div id="status" class="status-badge status-disconnected">Disconnected</div>
            <div id="modelInfo" class="model-info"></div>
        </div>

        <div id="chatContainer" class="chat-container">
            <div class="message ai-message">
                <div class="message-bubble">Hello! I'm OmniTutor powered by Gemini 2.5. Ask me anything - text, voice, or upload a photo!</div>
            </div>
        </div>

        <div class="input-area">
            <button id="micButton" class="mic-button" disabled>🎤</button>

            <div class="text-input">
                <input type="text" id="messageInput" placeholder="Type your question..." disabled>
                <button id="sendButton" disabled>Send</button>
            </div>

            <div class="image-upload">
                <input type="file" id="imageInput" accept="image/*" disabled>
                <label for="imageInput" id="imageLabel">📷 Upload Photo</label>
            </div>

            <img id="imagePreview" class="image-preview" alt="Preview">
        </div>
    </div>

    <script>
        // Configuration
        const SESSION_ID = Math.random().toString(36).substring(2, 15);

        // WebSocket connection
        const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const WS_URL = `${WS_PROTOCOL}//${window.location.host}/ws/${SESSION_ID}`;

        console.log('🔌 WebSocket URL:', WS_URL);

        // DOM elements
        const chatContainer = document.getElementById('chatContainer');
        const statusEl = document.getElementById('status');
        const modelInfoEl = document.getElementById('modelInfo');
        const micButton = document.getElementById('micButton');
        const messageInput = document.getElementById('messageInput');
        const sendButton = document.getElementById('sendButton');
        const imageInput = document.getElementById('imageInput');
        const imageLabel = document.getElementById('imageLabel');
        const imagePreview = document.getElementById('imagePreview');

        // State
        let socket = null;
        let isListening = false;
        let mediaRecorder = null;
        let audioChunks = [];
        let reconnectAttempts = 0;
        const MAX_RECONNECT_ATTEMPTS = 5;
        let isConnected = false;

        // Update model info
        modelInfoEl.textContent = `Session: ${SESSION_ID} | Gemini 2.5 Flash-Lite`;

        // Update UI based on connection
        function updateUIForConnection(connected) {
            isConnected = connected;
            messageInput.disabled = !connected;
            sendButton.disabled = !connected;
            imageInput.disabled = !connected;
            micButton.disabled = !connected;

            if (!connected) {
                micButton.classList.remove('listening');
            }
        }

        // Update status
        function updateStatus(type, text) {
            statusEl.className = 'status-badge status-' + type;
            statusEl.textContent = text;
        }

        // Add message to chat
        function addMessage(sender, text, isHTML = false) {
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message ' + (sender === 'user' ? 'user-message' : 'ai-message');

            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';

            if (isHTML) {
                bubble.innerHTML = text;
            } else {
                // Check for math
                if (text.includes('=') || text.includes('+') || text.includes('-') || 
                    text.includes('*') || text.includes('/') || text.includes('∫') ||
                    text.includes('∑') || text.includes('√')) {
                    bubble.innerHTML = `<div class="math-display">${text.replace(/\\n/g, '<br>')}</div>`;
                } else {
                    bubble.textContent = text;
                }
            }

            messageDiv.appendChild(bubble);
            chatContainer.appendChild(messageDiv);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        // Show thinking indicator
        function showThinking() {
            const indicator = document.createElement('div');
            indicator.className = 'message ai-message';
            indicator.id = 'thinkingIndicator';
            indicator.innerHTML = '<div class="thinking-indicator"><span></span><span></span><span></span></div>';
            chatContainer.appendChild(indicator);
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }

        // Remove thinking indicator
        function removeThinking() {
            const indicator = document.getElementById('thinkingIndicator');
            if (indicator) indicator.remove();
        }

        // Connect WebSocket
        function connectWebSocket() {
            try {
                socket = new WebSocket(WS_URL);

                socket.onopen = function() {
                    console.log('✅ WebSocket connected');
                    updateStatus('connected', 'Connected');
                    updateUIForConnection(true);
                    reconnectAttempts = 0;
                    addMessage('system', '✅ Connected to Gemini 2.5! Ready to help.');
                };

                socket.onmessage = function(event) {
                    console.log('📨 Received:', event.data);
                    removeThinking();

                    try {
                        const data = JSON.parse(event.data);

                        if (data.type === 'response') {
                            addMessage('ai', data.text);
                            if (data.audio) {
                                const audio = new Audio('data:audio/mp3;base64,' + data.audio);
                                audio.play().catch(e => console.log('Audio error:', e));
                            }
                            updateStatus('connected', 'Connected');
                        } else if (data.type === 'error') {
                            addMessage('system', '❌ ' + data.message);
                            updateStatus('connected', 'Connected');
                        }
                    } catch (e) {
                        console.error('Parse error:', e);
                    }
                };

                socket.onclose = function() {
                    console.log('❌ WebSocket disconnected');
                    updateStatus('disconnected', 'Disconnected');
                    updateUIForConnection(false);

                    if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                        reconnectAttempts++;
                        const delay = 2000 * reconnectAttempts;
                        setTimeout(connectWebSocket, delay);
                    }
                };

                socket.onerror = function(error) {
                    console.error('WebSocket error:', error);
                };

            } catch (e) {
                console.error('Connection error:', e);
                updateStatus('disconnected', 'Connection Failed');
            }
        }

        // Voice recording
        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.ondataavailable = (event) => {
                    audioChunks.push(event.data);
                };

                mediaRecorder.onstop = () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    const reader = new FileReader();
                    reader.onload = () => {
                        if (socket && socket.readyState === WebSocket.OPEN) {
                            socket.send(reader.result);
                            showThinking();
                            updateStatus('thinking', 'Thinking...');
                        }
                    };
                    reader.readAsArrayBuffer(audioBlob);
                    stream.getTracks().forEach(track => track.stop());
                };

                mediaRecorder.start();
                isListening = true;
                micButton.classList.add('listening');
                updateStatus('thinking', 'Listening...');

            } catch (error) {
                console.error('Mic error:', error);
                addMessage('system', '❌ Could not access microphone');
            }
        }

        function stopRecording() {
            if (mediaRecorder && isListening) {
                mediaRecorder.stop();
                isListening = false;
                micButton.classList.remove('listening');
            }
        }

        // Event listeners
        micButton.addEventListener('mousedown', startRecording);
        micButton.addEventListener('mouseup', stopRecording);
        micButton.addEventListener('mouseleave', stopRecording);

        sendButton.addEventListener('click', () => {
            const message = messageInput.value.trim();
            if (message && socket && socket.readyState === WebSocket.OPEN) {
                addMessage('user', message);
                socket.send(JSON.stringify({
                    message_type: 'text',
                    message: message
                }));
                messageInput.value = '';
                showThinking();
                updateStatus('thinking', 'Thinking...');
            }
        });

        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !sendButton.disabled) {
                sendButton.click();
            }
        });

        imageInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = () => {
                    imagePreview.src = reader.result;
                    imagePreview.style.display = 'block';
                    imageLabel.textContent = '📷 Change Photo';

                    const base64Image = reader.result.split(',')[1];
                    if (socket && socket.readyState === WebSocket.OPEN) {
                        addMessage('user', '📷 Uploaded image');
                        socket.send(JSON.stringify({
                            message_type: 'image',
                            image: base64Image,
                            prompt: 'Analyze this image'
                        }));
                        showThinking();
                        updateStatus('thinking', 'Analyzing...');
                    }
                };
                reader.readAsDataURL(file);
            }
        });

        // Start connection
        connectWebSocket();
    </script>
</body>
</html>
"""

# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Serve the main HTML page"""
    return HTMLResponse(content=HTML_CONTENT)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "OmniTutor",
        "model": "Gemini 2.5 Flash-Lite (July 2025)",
        "model_loaded": live_model is not None,
        "active_connections": len(active_connections),
        "api_key_set": bool(GEMINI_API_KEY)
    })

@app.get("/test")
async def test_endpoint():
    """Test endpoint"""
    return JSONResponse({
        "status": "ok",
        "message": "Server is running with Gemini 2.5",
        "connections": len(active_connections)
    })

# ============================================
# WEBSOCKET HANDLER
# ============================================

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Main WebSocket endpoint"""
    await websocket.accept()
    active_connections[session_id] = websocket
    logger.info(f"✅ Client connected: {session_id} (Total: {len(active_connections)})")

    try:
        # Send welcome
        await websocket.send_text(json.dumps({
            "type": "response",
            "text": "Welcome! I'm your Gemini 2.5 tutor. How can I help you today?"
        }))

        while True:
            message = await websocket.receive()

            if "bytes" in message:
                # Audio data
                await handle_voice(message["bytes"], websocket, session_id)

            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                    if data.get("message_type") == "image":
                        await handle_image(data, websocket, session_id)
                    else:
                        await handle_text(data, websocket, session_id)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from {session_id}")

    except WebSocketDisconnect:
        logger.info(f"❌ Client disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if session_id in active_connections:
            del active_connections[session_id]

# ============================================
# GEMINI 2.5 HANDLERS
# ============================================

async def handle_text(data: dict, websocket: WebSocket, session_id: str):
    """Handle text input with Gemini 2.5"""
    try:
        if not live_model:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Gemini 2.5 not configured. Check API key."
            }))
            return

        message = data.get("message", "")
        logger.info(f"📝 Text from {session_id}: {message[:50]}...")

        # Enhanced prompt for Gemini 2.5
        prompt = f"""You are OmniTutor, an expert AI tutor powered by Gemini 2.5.
A student asks: {message}

Provide a helpful, educational response that:
1. Explains concepts clearly with examples
2. Shows step-by-step reasoning
3. Uses analogies when helpful
4. Asks follow-up questions to check understanding

Be encouraging and patient. If it's a math problem, show your work."""

        response = live_model.generate_content(prompt)
        logger.info(f"✅ Response generated for {session_id}")

        await websocket.send_text(json.dumps({
            "type": "response",
            "text": response.text
        }))

    except Exception as e:
        logger.error(f"Text error: {e}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Error: {str(e)}"
        }))

async def handle_voice(audio_data: bytes, websocket: WebSocket, session_id: str):
    """Handle voice input with Gemini 2.5"""
    try:
        if not live_model:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Gemini 2.5 not configured"
            }))
            return

        logger.info(f"🎤 Voice from {session_id}")

        # Gemini 2.5 can process audio directly
        response = live_model.generate_content([
            "You are OmniTutor, a helpful AI tutor. A student is speaking to you. Respond naturally and helpfully.",
            {"mime_type": "audio/webm", "data": audio_data}
        ])

        await websocket.send_text(json.dumps({
            "type": "response",
            "text": response.text
        }))

    except Exception as e:
        logger.error(f"Voice error: {e}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Voice error: {str(e)}"
        }))

async def handle_image(data: dict, websocket: WebSocket, session_id: str):
    """Handle image input with Gemini 2.5 (multimodal)"""
    try:
        if not vision_model:
            await websocket.send_text(json.dumps({
                "type": "error",
                "message": "Vision model not configured"
            }))
            return

        image_data = base64.b64decode(data["image"])
        prompt = data.get("prompt", "Analyze this image")

        logger.info(f"📷 Image from {session_id}")

        # Process image with PIL
        image = Image.open(io.BytesIO(image_data))

        # Gemini 2.5 handles images naturally
        response = vision_model.generate_content([
            "You are OmniTutor. A student has shared an image. Analyze it and provide helpful feedback.",
            prompt,
            image
        ])

        await websocket.send_text(json.dumps({
            "type": "response",
            "text": response.text
        }))

    except Exception as e:
        logger.error(f"Image error: {e}")
        await websocket.send_text(json.dumps({
            "type": "error",
            "message": f"Image error: {str(e)}"
        }))

# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == "__main__":
    import uvicorn

    logger.info("=" * 60)
    logger.info("🚀 Starting OmniTutor with Gemini 2.5")
    logger.info("=" * 60)
    logger.info(f"🔑 API Key Set: {bool(GEMINI_API_KEY)}")
    logger.info(f"🤖 Model: Gemini 2.5 Flash-Lite (July 2025)")
    logger.info(f"📊 Model Loaded: {live_model is not None}")
    logger.info("=" * 60)
    logger.info("🌐 Web Interface: http://0.0.0.0:8080")
    logger.info("🔌 WebSocket: ws://0.0.0.0:8080/ws/{session_id}")
    logger.info("📊 Health Check: http://0.0.0.0:8080/health")
    logger.info("=" * 60)

    uvicorn.run(app, host="0.0.0.0", port=8080)
