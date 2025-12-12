"""FastAPI application demonstrating ADK Bidi-streaming with WebSocket."""

import asyncio
import json
import logging
import warnings
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import re

# Load environment variables from .env file BEFORE importing agent
load_dotenv(Path(__file__).parent / ".env")

# Import agent after loading environment variables
# pylint: disable=wrong-import-position
# from google_search_agent.agent import agent  # noqa: E402
from gauging_agent.agent import agent

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Suppress Pydantic serialization warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

# Application name constant
APP_NAME = "bidi-demo"

# ========================================
# Phase 1: Application Initialization (once at startup)
# ========================================

app = FastAPI()

# Mount static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

async def configure_agent_for_topic(topic: str, title: str,user_id:str,session_id:str):
    """Configure the agent's system instructions based on topic and title."""
    print(f'CONFIGURING AGENT NOW ::::::: WITH TOPIC : {topic} AND TITLE : {title}')
    _initial_state_ = {
    "topic": topic,
    "title": title
    }
    # Define your session service
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        state=_initial_state_,
        session_id=session_id
    )
    return session_service
# Define your session service
# session_service = InMemorySessionService()

# # Define your runner
# runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)

# ========================================
# HTTP Endpoints
# ========================================


@app.get("/")
async def root():
    """Serve the index.html page."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")


# ========================================
# WebSocket Endpoint
# ========================================


@app.websocket("/ws/{user_id}/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket, user_id: str, session_id: str
) -> None:
    """WebSocket endpoint for bidirectional streaming with ADK."""
    logger.debug(
        "WebSocket connection request: " f"user_id={user_id}, session_id={session_id}"
    )
    await websocket.accept()
    logger.debug("WebSocket connection accepted")

    # Flag to track if configuration has been received
    config_received = False
    config_data = {}

    # ========================================
    # Phase 2: Wait for Configuration
    # ========================================

    try:
        # Wait for initial configuration message
        logger.info("Waiting for configuration message from client...")
        
        while not config_received:
            message = await websocket.receive()
            
            if "text" in message:
                text_data = message["text"]
                json_message = json.loads(text_data)
                
                # Check if this is a config message
                if json_message.get("type") == "config":
                    topic = json_message.get("topic", "General")
                    title = json_message.get("title", "Introduction")
                    
                    logger.info(f"Configuration received - Topic: {topic}, Title: {title}")
                    
                    # Configure the agent
                    configure_agent_for_topic(topic, title,user_id,session_id)
                    
                    # Store config data
                    config_data = {
                        "topic": topic,
                        "title": title
                    }
                    config_received = True
                    
                    # Send acknowledgment back to client
                    ack_message = {
                        "type": "config_ack",
                        "status": "ready",
                        "message": f"Ready to start conversation about {topic}: {title}",
                        "topic": topic,
                        "title": title
                    }
                    await websocket.send_text(json.dumps(ack_message))
                    logger.info("Configuration acknowledgment sent to client")
                    break
                else:
                    # Not a config message, send error
                    error_message = {
                        "type": "error",
                        "message": "Please send configuration first (type: 'config')"
                    }
                    await websocket.send_text(json.dumps(error_message))

    except WebSocketDisconnect:
        logger.warning("Client disconnected before sending configuration")
        return
    except Exception as e:
        logger.error(f"Error during configuration: {e}", exc_info=True)
        return
    
    # Configure the agent
    global session_service
    session_service = await configure_agent_for_topic(topic, title,user_id,session_id);
    # Define your runner
    global runner 
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service);
    # ========================================
    # Phase 3: Session Initialization (once per streaming session) (after config received)
    # ========================================

    # Automatically determine response modality based on model architecture
    # Native audio models (containing "native-audio" in name)
    # ONLY support AUDIO response modality.
    # Half-cascade models support both TEXT and AUDIO,
    # we default to TEXT for better performance.
    model_name = agent.model
    is_native_audio = "native-audio" in model_name.lower()

    if is_native_audio:
        # Native audio models require AUDIO response modality
        # with audio transcription
        response_modalities = ["AUDIO"]
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=response_modalities,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
        )
        logger.debug(
            f"Native audio model detected: {model_name}, "
            "using AUDIO response modality"
        )
    else:
        # Half-cascade models support TEXT response modality
        # for faster performance
        response_modalities = ["TEXT"]
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=response_modalities,
            input_audio_transcription=None,
            output_audio_transcription=None,
            session_resumption=types.SessionResumptionConfig(),
        )
        logger.debug(
            f"Half-cascade model detected: {model_name}, "
            "using TEXT response modality"
        )
    logger.debug(f"RunConfig created: {run_config}")

    # Get or create session (handles both new sessions and reconnections)
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if not session:
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )

    live_request_queue = LiveRequestQueue()

    # ========================================
    # Phase 4: Active Session (concurrent bidirectional communication)
    # ========================================

    async def upstream_task() -> None:
        """Receives messages from WebSocket and sends to LiveRequestQueue."""
        logger.debug("upstream_task started")
        while True:
            # Receive message from WebSocket (text or binary)
            message = await websocket.receive()

            # Handle binary frames (audio data)
            if "bytes" in message:
                audio_data = message["bytes"]
                logger.debug(f"Received binary audio chunk: {len(audio_data)} bytes")

                audio_blob = types.Blob(
                    mime_type="audio/pcm;rate=16000", data=audio_data
                )
                live_request_queue.send_realtime(audio_blob)

            # Handle text frames (JSON messages)
            elif "text" in message:
                text_data = message["text"]
                logger.debug(f"Received text message: {text_data[:100]}...")

                json_message = json.loads(text_data)

                # Extract text from JSON and send to LiveRequestQueue
                if json_message.get("type") == "text":
                    logger.debug(f"Sending text content: {json_message['text']}")
                    content = types.Content(
                        parts=[types.Part(text=json_message["text"])]
                    )
                    live_request_queue.send_content(content)

                # Handle image data
                elif json_message.get("type") == "image":
                    import base64

                    logger.debug("Received image data")

                    # Decode base64 image data
                    image_data = base64.b64decode(json_message["data"])
                    mime_type = json_message.get("mimeType", "image/jpeg")

                    logger.debug(
                        f"Sending image: {len(image_data)} bytes, " f"type: {mime_type}"
                    )

                    # Send image as blob
                    image_blob = types.Blob(mime_type=mime_type, data=image_data)
                    live_request_queue.send_realtime(image_blob)

    async def downstream_task() -> None:
        """Receives Events from run_live() and sends to WebSocket."""
        logger.debug("downstream_task started, calling runner.run_live()")
        logger.debug(
            f"Starting run_live with user_id={user_id}, " f"session_id={session_id}"
        )


        end_pattern = re.compile(
        r'\b(good\s*bye|goodbye|farewell|lesson\s*complete|end\s*of\s*lesson)\b',
        re.IGNORECASE
            )
        
        async for event in runner.run_live(
            user_id=user_id,
            session_id=session_id,
            live_request_queue=live_request_queue,
            run_config=run_config,
        ):
            event_json = event.model_dump_json(exclude_none=True, by_alias=True)
            logger.debug(f"[SERVER] Event: {event_json}")

            # Check if the agent's response contains any end phrase
            should_end = False
            if hasattr(event, 'content') and event.content and hasattr(event.content, 'parts'):
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        # Check if pattern matches
                        if end_pattern.search(part.text):
                            logger.info(f"Detected end phrase in: {part.text[:100]}...")
                            should_end = True
                            break
            
            await websocket.send_text(event_json)

                    # If end detected, send end signal
            if should_end:
                end_signal = {
                    "type": "conversation_end",
                    "reason": "lesson_complete",
                    "message": "The lesson is complete. Great job!"
                }
                await websocket.send_text(json.dumps(end_signal))
                logger.info("Sent conversation_end signal to client") 
                  
        logger.debug("run_live() generator completed")

    # Run both tasks concurrently
    # Exceptions from either task will propagate and cancel the other task
    try:
        logger.debug("Starting asyncio.gather for upstream and downstream tasks")
        await asyncio.gather(upstream_task(), downstream_task())
        logger.debug("asyncio.gather completed normally")
    except WebSocketDisconnect:
        logger.debug("Client disconnected normally")
    except Exception as e:
        logger.error(f"Unexpected error in streaming tasks: {e}", exc_info=True)
    finally:
        # ========================================
        # Phase 4: Session Termination
        # ========================================

        # Always close the queue, even if exceptions occurred
        logger.debug("Closing live_request_queue")
        live_request_queue.close()