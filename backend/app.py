import os
import json
from datetime import datetime
from uuid import uuid4
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from functions import (
    get_function_definitions,
    extract_information,
    generate_document,
    apply_edits,
)
from prompts import get_conversation_context

load_dotenv()

app = Flask(__name__)
CORS(app)
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# In-memory chat storage per session
session_chats = {}


def get_session_store(session_id: str):
    """Ensure a session store exists."""
    session_key = session_id or "default"
    if session_key not in session_chats:
        session_chats[session_key] = {"chats": {}, "order": []}
    return session_key, session_chats[session_key]


def create_chat(session_id: str, title: str | None = None):
    """Create a new chat thread for a session."""
    session_key, store = get_session_store(session_id)
    chat_id = str(uuid4())
    chat = {
        "id": chat_id,
        "title": title or "New Chat",
        "created_at": datetime.utcnow().isoformat(),
        "messages": [],
    }
    store["chats"][chat_id] = chat
    store["order"].insert(0, chat_id)
    return session_key, chat


def get_chat(session_id: str, chat_id: str, auto_create: bool = False):
    """Fetch a chat by id, optionally creating one."""
    session_key, store = get_session_store(session_id)
    if chat_id and chat_id in store["chats"]:
        return session_key, store["chats"][chat_id]
    if auto_create or not chat_id:
        _, chat = create_chat(session_key)
        return session_key, chat
    raise ValueError(f"Chat not found: {chat_id} in session {session_key}")


def list_chats(session_id: str):
    """Return ordered chat summaries for a session."""
    _, store = get_session_store(session_id)
    summaries = []
    for chat_id in store["order"]:
        chat = store["chats"].get(chat_id)
        if chat:
            summaries.append(
                {"id": chat["id"], "title": chat["title"], "created_at": chat["created_at"]}
            )
    return summaries


def update_chat_title(chat, message: str):
    """Generate a proper subject line from the first user message."""
    if message:
        try:
            # generate a concise title (max 50 chars)
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that creates concise, descriptive titles (max 50 characters) for legal document requests. Return only the title, no quotes or extra text."
                    },
                    {
                        "role": "user",
                        "content": f"Create a short title for this legal document request: {message}"
                    }
                ],
                temperature=0.7,
                max_tokens=20
            )
            title = response.choices[0].message.content.strip().strip('"').strip("'")
            # Fallback to truncated message if AI fails or returns too long
            if len(title) > 50 or not title:
                title = (message[:47] + "...") if len(message) > 47 else message
            chat["title"] = title
        except Exception as e:
            chat["title"] = (message[:47] + "...") if len(message) > 47 else message


@app.route("/api/chat", methods=["POST"])
def chat():
    """SSE endpoint for streaming chat responses with function calling"""
    try:
        data = request.json
        message = data.get("message")
        session_id = data.get("session_id", "default")
        chat_id = data.get("chat_id")
        regenerate = data.get("regenerate", False)

        _, chat_data = get_chat(session_id, chat_id, auto_create=True)
        conversation_history = chat_data["messages"]

        if regenerate:
            if not conversation_history or conversation_history[-1]["role"] != "user":
                return jsonify({"error": "Nothing to regenerate"}), 400
        else:
            if not message or not message.strip():
                return jsonify({"error": "Message is required"}), 400
            conversation_history.append({"role": "user", "content": message})
            update_chat_title(chat_data, message.strip())

        system_prompt = get_conversation_context(conversation_history)
        messages = [{"role": "system", "content": system_prompt}] + conversation_history

        tools = get_function_definitions()

        def generate():
            """Generator function for SSE streaming"""
            try:
                # Make streaming API call
                stream = openai_client.chat.completions.create(
                    model="gpt-3.5-turbo",  # faster/cheaper
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                    temperature=0.7,
                )

                full_response = ""
                function_call_accumulator = None
                current_function_name = None

                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response += content
                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"

                    if chunk.choices[0].delta.tool_calls:
                        for tool_call_delta in chunk.choices[0].delta.tool_calls:
                            if tool_call_delta.index is not None:
                                if function_call_accumulator is None:
                                    function_call_accumulator = {
                                        "id": tool_call_delta.id if tool_call_delta.id else "",
                                        "type": "function",
                                        "function": {
                                            "name": "",
                                            "arguments": ""
                                        }
                                    }
                                
                                if tool_call_delta.function.name:
                                    current_function_name = tool_call_delta.function.name
                                    function_call_accumulator["function"]["name"] = current_function_name
                                    yield f"data: {json.dumps({'type': 'function_call', 'function_name': current_function_name})}\n\n"

                                if tool_call_delta.function.arguments:
                                    function_call_accumulator["function"]["arguments"] += tool_call_delta.function.arguments

                    if chunk.choices[0].finish_reason == "tool_calls" and function_call_accumulator:
                        function_name = function_call_accumulator["function"]["name"]
                        arguments_str = function_call_accumulator["function"]["arguments"]

                        try:
                            arguments = json.loads(arguments_str)

                            if function_name == "extract_information":
                                result = extract_information(
                                    arguments.get("extracted_data", {}),
                                    arguments.get("document_type", "Unknown")
                                )
                                yield f"data: {json.dumps({'type': 'function_result', 'function_name': function_name, 'result': result})}\n\n"

                                conversation_history.append(
                                    {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [function_call_accumulator],
                                    }
                                )
                                conversation_history.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": function_call_accumulator["id"],
                                        "content": json.dumps(result),
                                    }
                                )

                                follow_up_messages = [{"role": "system", "content": system_prompt}] + conversation_history

                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    tools=tools,
                                    tool_choice="auto",
                                    stream=True,
                                    temperature=0.7,
                                )

                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"

                                if follow_up_response:
                                    conversation_history.append({"role": "assistant", "content": follow_up_response})

                            elif function_name == "generate_document":
                                document = generate_document(
                                    arguments.get("document_type", "Unknown"),
                                    arguments.get("extracted_data", {})
                                )
                                yield f"data: {json.dumps({'type': 'function_result', 'function_name': function_name, 'result': {'status': 'success', 'document': document}})}\n\n"
                                yield f"data: {json.dumps({'type': 'document', 'content': document})}\n\n"

                                conversation_history.append(
                                    {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [function_call_accumulator],
                                    }
                                )
                                conversation_history.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": function_call_accumulator["id"],
                                        "content": json.dumps({"status": "success", "document": document}),
                                    }
                                )
                                follow_up_messages = [{"role": "system", "content": system_prompt}] + conversation_history

                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    stream=True,
                                    temperature=0.7,
                                )

                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"

                                if follow_up_response:
                                    conversation_history.append({"role": "assistant", "content": follow_up_response})

                            elif function_name == "apply_edits":
                                edited_document = apply_edits(
                                    arguments.get("edit_description", ""),
                                    arguments.get("new_values", {}),
                                    arguments.get("document_id")
                                )
                                yield f"data: {json.dumps({'type': 'function_result', 'function_name': function_name, 'result': {'status': 'success', 'document': edited_document}})}\n\n"
                                yield f"data: {json.dumps({'type': 'document', 'content': edited_document})}\n\n"

                                conversation_history.append(
                                    {
                                        "role": "assistant",
                                        "content": None,
                                        "tool_calls": [function_call_accumulator],
                                    }
                                )
                                conversation_history.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": function_call_accumulator["id"],
                                        "content": json.dumps({"status": "success", "document": edited_document}),
                                    }
                                )

                                follow_up_messages = [{"role": "system", "content": system_prompt}] + conversation_history

                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    stream=True,
                                    temperature=0.7,
                                )

                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"

                                if follow_up_response:
                                    conversation_history.append({"role": "assistant", "content": follow_up_response})

                        except json.JSONDecodeError as e:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Error parsing function arguments: {str(e)}'})}\n\n"
                        except Exception as e:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Error executing function: {str(e)}'})}\n\n"

                        function_call_accumulator = None
                        current_function_name = None

                if full_response and not function_call_accumulator:
                    conversation_history.append({"role": "assistant", "content": full_response})

                yield "data: [DONE]\n\n"

            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                yield "data: [DONE]\n\n"

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/chats", methods=["POST"])
def create_chat_route():
    """Create a new chat thread."""
    data = request.json or {}
    session_id = data.get("session_id", "default")
    title = data.get("title")
    _, chat = create_chat(session_id, title)
    return jsonify({"chat_id": chat["id"], "title": chat["title"], "created_at": chat["created_at"]})


@app.route("/api/chats/<session_id>", methods=["GET"])
def list_chats_route(session_id):
    """Return chat summaries for a session."""
    return jsonify({"chats": list_chats(session_id)})


@app.route("/api/chats/<session_id>/<chat_id>", methods=["GET"])
def get_chat_route(session_id, chat_id):
    """Fetch a specific chat history."""
    try:
        _, chat = get_chat(session_id, chat_id)
        return jsonify({"chat": {"id": chat["id"], "title": chat["title"], "messages": chat["messages"]}})
    except ValueError:
        return jsonify({"error": "Chat not found"}), 404


@app.route("/api/chats/<session_id>/<chat_id>/edit", methods=["POST"])
def edit_message_route(session_id, chat_id):
    """Edit a previous user message and truncate following history."""
    payload = request.json or {}
    message_index = payload.get("message_index")
    new_content = payload.get("new_content", "").strip()

    if message_index is None:
        return jsonify({"error": "message_index required"}), 400
    if not new_content:
        return jsonify({"error": "new_content required"}), 400

    try:
        _, chat = get_chat(session_id, chat_id)
    except ValueError:
        return jsonify({"error": "Chat not found"}), 404

    messages = chat["messages"]
    if message_index < 0 or message_index >= len(messages):
        return jsonify({"error": "message_index out of range"}), 400
    if messages[message_index]["role"] != "user":
        return jsonify({"error": "Only user messages can be edited"}), 400

    messages[message_index]["content"] = new_content
    chat["messages"] = messages[: message_index + 1]
    
    # if user edits the first message (index 0), update the chat title
    if message_index == 0:
        update_chat_title(chat, new_content)
    
    return jsonify({"messages": chat["messages"], "title": chat["title"]})


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"})


@app.route("/api/chats/<session_id>/<chat_id>", methods=["DELETE"])
def delete_chat_route(session_id, chat_id):
    """Delete a specific chat."""
    try:
        session_key, store = get_session_store(session_id)
        if chat_id in store["chats"]:
            del store["chats"][chat_id]
            if chat_id in store["order"]:
                store["order"].remove(chat_id)
            return jsonify({"status": "deleted"})
        return jsonify({"error": "Chat not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/conversations/<session_id>", methods=["DELETE"])
def clear_conversation(session_id):
    """Clear all chats for a session."""
    session_key, _ = get_session_store(session_id)
    if session_key in session_chats:
        del session_chats[session_key]
    return jsonify({"status": "cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port, threaded=True)

