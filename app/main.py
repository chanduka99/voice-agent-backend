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


async def configure_agent_for_topic(topic: str, title: str, user_id: str, session_id: str):
    """Configure the agent's system instructions based on topic and title."""
    logger.info(f"Configuring agent - Topic: {topic}, Title: {title}")
    
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
        f"WebSocket connection request: user_id={user_id}, session_id={session_id}"
    )
    await websocket.accept()
    logger.debug("WebSocket connection accepted")

    # Flag to track if configuration has been received
    config_received = False
    config_data = {}
    
    # Flag to signal conversation end
    conversation_ended = asyncio.Event()

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
    session_service = await configure_agent_for_topic(
        config_data["topic"], 
        config_data["title"], 
        user_id, 
        session_id
    )
    
    # Define your runner
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    
    # ========================================
    # Phase 3: Session Initialization (after config received)
    # ========================================

    # Automatically determine response modality based on model architecture
    model_name = agent.model
    is_native_audio = "native-audio" in model_name.lower()

    if is_native_audio:
        # Native audio models require AUDIO response modality with audio transcription
        response_modalities = ["AUDIO"]
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=response_modalities,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(),
        )
        logger.debug(
            f"Native audio model detected: {model_name}, using AUDIO response modality"
        )
    else:
        # Half-cascade models support TEXT response modality for faster performance
        response_modalities = ["TEXT"]
        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=response_modalities,
            input_audio_transcription=None,
            output_audio_transcription=None,
            session_resumption=types.SessionResumptionConfig(),
        )
        logger.debug(
            f"Half-cascade model detected: {model_name}, using TEXT response modality"
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
        
        while not conversation_ended.is_set():
            try:
                # Add timeout to check conversation_ended flag periodically
                message = await asyncio.wait_for(
                    websocket.receive(), 
                    timeout=0.5
                )
            except asyncio.TimeoutError:
                # Timeout - just continue loop to check conversation_ended flag
                continue
            except WebSocketDisconnect:
                logger.debug("Client disconnected in upstream_task")
                break
            except Exception as e:
                logger.error(f"Error in upstream_task: {e}")
                break

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
                        f"Sending image: {len(image_data)} bytes, type: {mime_type}"
                    )

                    # Send image as blob
                    image_blob = types.Blob(mime_type=mime_type, data=image_data)
                    live_request_queue.send_realtime(image_blob)
        
        logger.debug("upstream_task ended - conversation complete")

    async def downstream_task() -> None:
        """Receives Events from run_live() and sends to WebSocket."""
        logger.debug("downstream_task started, calling runner.run_live()")
        logger.debug(
            f"Starting run_live with user_id={user_id}, session_id={session_id}"
        )

        # Regex pattern to detect end phrases (case-insensitive)
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
            
            # Send the event first (so user sees the goodbye message)
            await websocket.send_text(event_json)

            # If end detected, send end signal and stop
            if should_end:
                end_signal = {
                    "type": "conversation_end",
                    "reason": "lesson_complete",
                    "message": "The lesson is complete. Great job!"
                }
                await websocket.send_text(json.dumps(end_signal))
                logger.info("Sent conversation_end signal to client")
                
                # Signal the upstream task to stop accepting messages
                conversation_ended.set()
                logger.info("Conversation ended flag set - stopping upstream task")
                
                # Close the queue to stop receiving new messages
                live_request_queue.close()
                logger.info("Live request queue closed - no more messages accepted")
                
                # Exit the downstream loop
                break
                  
        logger.debug("run_live() generator completed")

    # Run both tasks concurrently
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
        # Phase 5: Session Termination
        # ========================================

        # Always close the queue, even if exceptions occurred
        logger.debug("Closing live_request_queue in finally block")
        live_request_queue.close()
        logger.info(f"Session {session_id} terminated")