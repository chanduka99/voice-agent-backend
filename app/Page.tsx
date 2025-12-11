"use client";

import React, { useEffect, useRef, useState } from "react";

type ConsoleEntry = {
    id: string;
    type: string;
    content: string;
    data?: any;
    emoji?: string;
    author?: string;
};

export default function Page() {
    const userId = "demo-user";
    const sessionId = "demo-session-" + Math.random().toString(36).substring(7);

    const [connected, setConnected] = useState(false);
    const [messages, setMessages] = useState<Array<JSX.Element>>([]);
    const [consoleEntries, setConsoleEntries] = useState<ConsoleEntry[]>([]);
    const [isAudio, setIsAudio] = useState(false);
    const [cameraVisible, setCameraVisible] = useState(false);

    const wsRef = useRef<WebSocket | null>(null);
    const audioPlayerNodeRef = useRef<any>(null);
    const audioPlayerCtxRef = useRef<any>(null);
    const audioRecorderNodeRef = useRef<any>(null);
    const micStreamRef = useRef<MediaStream | null>(null);
    const cameraStreamRef = useRef<MediaStream | null>(null);

    const messageInputRef = useRef<HTMLInputElement | null>(null);
    const messagesDivRef = useRef<HTMLDivElement | null>(null);
    const cameraVideoRef = useRef<HTMLVideoElement | null>(null);

    // Helpers
    function formatTimestamp() {
        const now = new Date();
        return now.toLocaleTimeString("en-US", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            fractionalSecondDigits: 3,
        });
    }

    function addConsoleEntry(type: string, content: string, data = null, emoji: string | null = null, author: string | null = null) {
        const entry: ConsoleEntry = { id: Math.random().toString(36).substring(7), type, content, data, emoji: emoji || undefined, author: author || undefined };
        setConsoleEntries((prev) => [...prev, entry]);
        // scroll handled in render
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            if (messagesDivRef.current) messagesDivRef.current.scrollTop = messagesDivRef.current.scrollHeight;
        });
    }

    function createMessageBubble(text: string, isUser: boolean, isPartial = false) {
        const outerClass = isUser ? "mb-3 flex justify-end" : "mb-3 flex justify-start";
        const bubbleClass = isUser
            ? "px-4 py-2 rounded-xl bg-blue-600 text-white max-w-[70%] break-words shadow"
            : "px-4 py-2 rounded-xl bg-gray-100 text-gray-900 max-w-[70%] break-words shadow-sm";
        const typingDot = (
            <span className="inline-block ml-2 align-middle">
                <span className="inline-block w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse mr-1" />
                <span className="inline-block w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse delay-75 mr-1" />
                <span className="inline-block w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse delay-150" />
            </span>
        );
        return (
            <div key={Math.random().toString(36)} className={outerClass}>
                <div className={bubbleClass}>
                    <p className="text-sm leading-relaxed">
                        {text}
                        {isPartial && !isUser ? typingDot : null}
                    </p>
                </div>
            </div>
        );
    }

    function createImageBubble(imageDataUrl: string, isUser: boolean) {
        const outerClass = isUser ? "mb-3 flex justify-end" : "mb-3 flex justify-start";
        const bubbleClass = "rounded-xl overflow-hidden shadow max-w-[70%]";
        const imgClass = "w-full h-auto block";
        return (
            <div key={Math.random().toString(36)} className={outerClass}>
                <div className={bubbleClass}>
                    <img src={imageDataUrl} className={imgClass} alt="Captured" />
                </div>
            </div>
        );
    }

    // Convert base64 to ArrayBuffer
    function base64ToArray(base64: string) {
        let standardBase64 = base64.replace(/-/g, "+").replace(/_/g, "/");
        while (standardBase64.length % 4) standardBase64 += "=";
        const binaryString = window.atob(standardBase64);
        const len = binaryString.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) bytes[i] = binaryString.charCodeAt(i);
        return bytes.buffer;
    }

    // Clean CJK spaces (simple heuristic)
    function cleanCJKSpaces(text: string) {
        const cjkPattern = /[\u3000-\u303f\u3040-\u309f\u30a0-\u30ff\u4e00-\u9faf\uff00-\uffef]/;
        return text.replace(/(\S)\s+(?=\S)/g, (match, char1) => {
            const nextChar = match.slice(-1);
            if (cjkPattern.test(char1) && cjkPattern.test(nextChar)) return char1;
            return match;
        });
    }

    // Build websocket url
    function getWebSocketUrl() {
        return (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ws/" + userId + "/" + sessionId;
    }

    // WebSocket connect
    useEffect(() => {
        const ws_url = getWebSocketUrl();
        const ws = new WebSocket(ws_url);
        wsRef.current = ws;

        ws.onopen = () => {
            setConnected(true);
            addConsoleEntry("incoming", "WebSocket Connected", { userId, sessionId, url: ws_url }, "🔌", "system");
        };

        ws.onmessage = (evt) => {
            try {
                const adkEvent = JSON.parse(evt.data);
                handleAdkEvent(adkEvent);
            } catch (e) {
                // binary audio may arrive as ArrayBuffer (if server sends raw PCM), ignore here
                console.warn("Non-JSON message received", e);
            }
        };

        ws.onclose = () => {
            setConnected(false);
            addConsoleEntry("error", "WebSocket Disconnected", { reconnecting: true }, "🔌", "system");
            // reconnect after delay
            setTimeout(() => connectWebsocket(), 5000);
        };

        ws.onerror = (e) => {
            setConnected(false);
            addConsoleEntry("error", "WebSocket Error", { e }, "⚠️", "system");
        };

        function connectWebsocket() {
            if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) return;
            const newWs = new WebSocket(getWebSocketUrl());
            wsRef.current = newWs;
            newWs.onopen = ws.onopen;
            newWs.onmessage = ws.onmessage;
            newWs.onclose = ws.onclose;
            newWs.onerror = ws.onerror;
        }

        return () => {
            try {
                ws.close();
            } catch (e) { }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // ADK Event handler (partial port of original app.js logic)
    let currentMessageId: string | null = null;
    let currentBubbleIndex: number | null = null;
    let currentInputTranscriptionIndex: number | null = null;
    let currentOutputTranscriptionIndex: number | null = null;

    function handleAdkEvent(adkEvent: any) {
        const author = adkEvent.author || "system";
        // Prepare event summary
        let eventSummary = "Event";
        let eventEmoji = "📨";

        if (adkEvent.turnComplete) {
            eventSummary = "Turn Complete";
            eventEmoji = "✅";
        } else if (adkEvent.interrupted) {
            eventSummary = "Interrupted";
            eventEmoji = "⏸️";
        } else if (adkEvent.inputTranscription) {
            const transcriptionText = adkEvent.inputTranscription.text || "";
            const truncated = transcriptionText.length > 60 ? transcriptionText.substring(0, 60) + "..." : transcriptionText;
            eventSummary = `Input Transcription: "${truncated}"`;
            eventEmoji = "📝";
        } else if (adkEvent.outputTranscription) {
            const transcriptionText = adkEvent.outputTranscription.text || "";
            const truncated = transcriptionText.length > 60 ? transcriptionText.substring(0, 60) + "..." : transcriptionText;
            eventSummary = `Output Transcription: "${truncated}"`;
            eventEmoji = "📝";
        } else if (adkEvent.content && adkEvent.content.parts) {
            const parts = adkEvent.content.parts;
            const hasText = parts.some((p: any) => p.text);
            const hasAudio = parts.some((p: any) => p.inlineData);
            if (hasText) {
                const textPart = parts.find((p: any) => p.text);
                const text = textPart?.text || "";
                const truncated = text.length > 80 ? text.substring(0, 80) + "..." : text;
                eventSummary = `Text: "${truncated}"`;
                eventEmoji = "💭";
            }
            if (hasAudio) {
                const audioPart = parts.find((p: any) => p.inlineData);
                const mimeType = audioPart?.inlineData?.mimeType || "unknown";
                const dataLength = audioPart?.inlineData?.data ? audioPart.inlineData.data.length : 0;
                const byteSize = Math.floor(dataLength * 0.75);
                eventSummary = `Audio Response: ${mimeType} (${byteSize.toLocaleString()} bytes)`;
                eventEmoji = "🔊";
            }
        }

        addConsoleEntry("incoming", eventSummary, adkEvent, eventEmoji, author);

        // Handle special flags
        if (adkEvent.turnComplete === true) {
            currentMessageId = null;
            currentBubbleIndex = null;
            currentOutputTranscriptionIndex = null;
            return;
        }

        if (adkEvent.interrupted === true) {
            // mark interrupted (no need to deeply mutate for this port)
            currentMessageId = null;
            currentBubbleIndex = null;
            currentOutputTranscriptionIndex = null;
            return;
        }

        // Input transcription
        if (adkEvent.inputTranscription && adkEvent.inputTranscription.text) {
            const transcriptionText = adkEvent.inputTranscription.text;
            const isFinished = !!adkEvent.inputTranscription.finished;
            const cleaned = cleanCJKSpaces(transcriptionText);
            if (currentInputTranscriptionIndex == null) {
                setMessages((prev) => [...prev, createMessageBubble(cleaned, true, !isFinished)]);
                currentInputTranscriptionIndex = messages.length; // approximate
            } else {
                // update last
                setMessages((prev) => {
                    const copy = [...prev];
                    copy[copy.length - 1] = createMessageBubble(cleaned, true, !isFinished);
                    return copy;
                });
            }
            if (isFinished) currentInputTranscriptionIndex = null;
            scrollToBottom();
        }

        // Output transcription
        if (adkEvent.outputTranscription && adkEvent.outputTranscription.text) {
            const transcriptionText = adkEvent.outputTranscription.text;
            const isFinished = !!adkEvent.outputTranscription.finished;
            if (currentOutputTranscriptionIndex == null) {
                setMessages((prev) => [...prev, createMessageBubble(transcriptionText, false, !isFinished)]);
                currentOutputTranscriptionIndex = messages.length;
            } else {
                setMessages((prev) => {
                    const copy = [...prev];
                    copy[copy.length - 1] = createMessageBubble(transcriptionText, false, !isFinished);
                    return copy;
                });
            }
            if (isFinished) currentOutputTranscriptionIndex = null;
            scrollToBottom();
        }

        // Content parts (text / audio)
        if (adkEvent.content && adkEvent.content.parts) {
            for (const part of adkEvent.content.parts) {
                if (part.inlineData) {
                    const mimeType = part.inlineData.mimeType;
                    const data = part.inlineData.data;
                    if (mimeType && mimeType.startsWith("audio/") && audioPlayerNodeRef.current) {
                        try {
                            const buf = base64ToArray(data);
                            audioPlayerNodeRef.current.port.postMessage(buf);
                        } catch (e) {
                            console.warn("Failed to post audio", e);
                        }
                    }
                }
                if (part.text) {
                    if (currentMessageId == null) {
                        currentMessageId = Math.random().toString(36).substring(7);
                        setMessages((prev) => [...prev, createMessageBubble(part.text, false, true)]);
                        currentBubbleIndex = messages.length;
                    } else {
                        setMessages((prev) => {
                            const copy = [...prev];
                            copy[copy.length - 1] = createMessageBubble((copy[copy.length - 1]?.props?.children?.props?.children ?? "") + part.text, false, true);
                            return copy;
                        });
                    }
                    scrollToBottom();
                }
            }
        }
    }

    // Send text message
    function sendMessage(message: string) {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
            const jsonMessage = JSON.stringify({ type: "text", text: message });
            ws.send(jsonMessage);
            addConsoleEntry("outgoing", "User Message: " + message, null, "💬", "user");
        }
    }

    // Camera handling
    async function openCameraPreview() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 768 }, height: { ideal: 768 }, facingMode: "user" } });
            cameraStreamRef.current = stream;
            if (cameraVideoRef.current) cameraVideoRef.current.srcObject = stream;
            setCameraVisible(true);
        } catch (e: any) {
            addConsoleEntry("error", `Failed to access camera: ${e?.message || e}`, { error: e }, "⚠️", "system");
        }
    }

    function closeCameraPreview() {
        if (cameraStreamRef.current) {
            cameraStreamRef.current.getTracks().forEach((t) => t.stop());
            cameraStreamRef.current = null;
        }
        if (cameraVideoRef.current) cameraVideoRef.current.srcObject = null;
        setCameraVisible(false);
    }

    function captureImageFromPreview() {
        const video = cameraVideoRef.current;
        if (!video) return;
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const imageDataUrl = canvas.toDataURL("image/jpeg", 0.85);
        setMessages((prev) => [...prev, createImageBubble(imageDataUrl, true)]);
        canvas.toBlob((blob) => {
            if (!blob) return;
            const reader = new FileReader();
            reader.onloadend = () => {
                const base64data = (reader.result as string).split(",")[1];
                sendImage(base64data);
                addConsoleEntry("outgoing", `Image captured: ${blob.size} bytes (JPEG)`, { size: blob.size, type: "image/jpeg" }, "📷", "user");
            };
            reader.readAsDataURL(blob);
        }, "image/jpeg", 0.85);
        closeCameraPreview();
    }

    function sendImage(base64Image: string) {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
            const jsonMessage = JSON.stringify({ type: "image", data: base64Image, mimeType: "image/jpeg" });
            ws.send(jsonMessage);
            addConsoleEntry("outgoing", "Sent image", null, "📷", "user");
        }
    }

    // Audio handling: dynamically import worklet helpers and start
    async function startAudio() {
        // start player
        try {
            const playerModule: any = await import("/static/js/audio-player.js");
            const recorderModule: any = await import("/static/js/audio-recorder.js");
            const [playerNode, playerCtx] = await playerModule.startAudioPlayerWorklet();
            audioPlayerNodeRef.current = playerNode;
            audioPlayerCtxRef.current = playerCtx;

            const [recNode, recCtx, stream] = await recorderModule.startAudioRecorderWorklet(audioRecorderHandler);
            audioRecorderNodeRef.current = recNode;
            micStreamRef.current = stream;
            setIsAudio(true);
            addConsoleEntry("outgoing", "Audio Mode Enabled", { status: "Audio worklets started" }, "🎤", "system");
        } catch (e) {
            addConsoleEntry("error", "Failed to start audio", { error: e }, "⚠️", "system");
        }
    }

    function audioRecorderHandler(pcmData: ArrayBuffer) {
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN && isAudio) {
            ws.send(pcmData);
            // optional console log suppressed to avoid noise
        }
    }

    // UI handlers
    function onSubmit(e: React.FormEvent) {
        e.preventDefault();
        const message = messageInputRef.current?.value.trim();
        if (!message) return;
        setMessages((prev) => [...prev, createMessageBubble(message, true, false)]);
        if (messageInputRef.current) messageInputRef.current.value = "";
        sendMessage(message!);
        scrollToBottom();
    }

    return (
        <div>
            <header>
                <h1>ADK Bidi-streaming Demo</h1>
                <div className="subtitle">Real-time bidirectional streaming with Google ADK</div>
                <div className="connection-status">
                    <span className={`status-indicator ${connected ? "" : "disconnected"}`} id="statusIndicator"></span>
                    <span id="statusText">{connected ? "Connected" : "Connecting..."}</span>
                </div>
            </header>

            <div className="main-layout">
                <div className="container">
                    <div id="messages" ref={messagesDivRef} className="messages-container">
                        {messages}
                    </div>

                    <div className="input-container">
                        <form id="messageForm" onSubmit={onSubmit}>
                            <div className="input-wrapper">
                                <input ref={messageInputRef} type="text" id="message" name="message" placeholder="Type your message here..." autoComplete="off" />
                                <button type="submit" id="sendButton">Send</button>
                                <button type="button" id="startAudioButton" onClick={() => startAudio()} disabled={isAudio}>Start Audio</button>
                                <button type="button" id="cameraButton" onClick={openCameraPreview}>📷 Camera</button>
                            </div>
                        </form>
                    </div>
                </div>

                <div className="console-panel">
                    <div className="console-header">
                        <h2>Event Console</h2>
                        <button id="clearConsole" className="console-clear-btn" onClick={() => setConsoleEntries([])}>Clear</button>
                    </div>
                    <div id="consoleContent" className="console-content">
                        {consoleEntries.map((entry) => (
                            <div key={entry.id} className={`console-entry ${entry.type}`}>
                                <div className="console-entry-header">
                                    <div className="console-entry-left">
                                        <span className="console-expand-icon">{entry.data ? "▶" : ""}</span>
                                        <span className="console-entry-type">{entry.type === "outgoing" ? "↑ Upstream" : entry.type === "incoming" ? "↓ Downstream" : "⚠ Error"}</span>
                                        {entry.author ? <span className="console-entry-author">{entry.author}</span> : null}
                                    </div>
                                    <span className="console-entry-timestamp">{formatTimestamp()}</span>
                                </div>
                                <div className="console-entry-content">{entry.emoji ? entry.emoji + " " : ""}{entry.content}</div>
                                {entry.data ? <pre className="console-entry-json">{JSON.stringify(entry.data, null, 2)}</pre> : null}
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* Camera Modal */}
            {cameraVisible ? (
                <div id="cameraModal" className="modal show">
                    <div className="modal-content">
                        <div className="modal-header">
                            <h3>Camera Preview</h3>
                            <button id="closeCameraModal" className="close-btn" onClick={closeCameraPreview}>&times;</button>
                        </div>
                        <div className="modal-body">
                            <video ref={cameraVideoRef} id="cameraPreview" autoPlay playsInline />
                        </div>
                        <div className="modal-footer">
                            <button id="cancelCamera" className="btn-secondary" onClick={closeCameraPreview}>Cancel</button>
                            <button id="captureImage" className="btn-primary" onClick={captureImageFromPreview}>📷 Send Image</button>
                        </div>
                    </div>
                </div>
            ) : null}
        </div>
    );
}
