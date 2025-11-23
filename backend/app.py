import os
import json
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from functions import get_function_definitions, extract_information, generate_document, apply_edits
from prompts import get_conversation_context
load_dotenv()

app = Flask(__name__)
CORS(app)
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
conversations = {} #chat history kind of thing


def get_or_create_conversation(session_id: str):
    """Get or create a conversation history for a session"""
    if session_id not in conversations:
        conversations[session_id] = []
    return conversations[session_id]


@app.route('/api/chat', methods=['POST'])
def chat():
    """SSE endpoint for streaming chat responses with function calling"""
    try:
        data = request.json
        message = data.get('message', '')
        session_id = data.get('session_id', 'default')
        conversation_history = get_or_create_conversation(session_id)
        
        # user message to history
        conversation_history.append({
            "role": "user",
            "content": message
        })
        system_prompt = get_conversation_context(conversation_history)
        messages = [
            {"role": "system", "content": system_prompt}
        ] + conversation_history
        
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
                    temperature=0.7
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
                                
                                conversation_history.append({
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [function_call_accumulator]
                                })
                                conversation_history.append({
                                    "role": "tool",
                                    "tool_call_id": function_call_accumulator["id"],
                                    "content": json.dumps(result)
                                })
                                
                                follow_up_messages = [
                                    {"role": "system", "content": system_prompt}
                                ] + conversation_history
                                
                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    tools=tools,
                                    tool_choice="auto",
                                    stream=True,
                                    temperature=0.7
                                )
                                
                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                
                                if follow_up_response:
                                    conversation_history.append({
                                        "role": "assistant",
                                        "content": follow_up_response
                                    })
                            
                            elif function_name == "generate_document":
                                document = generate_document(
                                    arguments.get("document_type", "Unknown"),
                                    arguments.get("extracted_data", {})
                                )
                                yield f"data: {json.dumps({'type': 'function_result', 'function_name': function_name, 'result': {'status': 'success', 'document': document}})}\n\n"
                                yield f"data: {json.dumps({'type': 'document', 'content': document})}\n\n"
                                
                                # Add to conversation
                                conversation_history.append({
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [function_call_accumulator]
                                })
                                conversation_history.append({
                                    "role": "tool",
                                    "tool_call_id": function_call_accumulator["id"],
                                    "content": json.dumps({"status": "success", "document": document})
                                })
                                follow_up_messages = [
                                    {"role": "system", "content": system_prompt}
                                ] + conversation_history
                                
                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    stream=True,
                                    temperature=0.7
                                )
                                
                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                
                                if follow_up_response:
                                    conversation_history.append({
                                        "role": "assistant",
                                        "content": follow_up_response
                                    })
                            
                            elif function_name == "apply_edits":
                                edited_document = apply_edits(
                                    arguments.get("edit_description", ""),
                                    arguments.get("new_values", {}),
                                    arguments.get("document_id")
                                )
                                yield f"data: {json.dumps({'type': 'function_result', 'function_name': function_name, 'result': {'status': 'success', 'document': edited_document}})}\n\n"
                                yield f"data: {json.dumps({'type': 'document', 'content': edited_document})}\n\n"
                                
                                conversation_history.append({
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [function_call_accumulator]
                                })
                                conversation_history.append({
                                    "role": "tool",
                                    "tool_call_id": function_call_accumulator["id"],
                                    "content": json.dumps({"status": "success", "document": edited_document})
                                })
                                
                                follow_up_messages = [
                                    {"role": "system", "content": system_prompt}
                                ] + conversation_history
                                
                                follow_up_stream = openai_client.chat.completions.create(
                                    model="gpt-3.5-turbo",
                                    messages=follow_up_messages,
                                    stream=True,
                                    temperature=0.7
                                )
                                
                                follow_up_response = ""
                                for follow_chunk in follow_up_stream:
                                    if follow_chunk.choices[0].delta.content:
                                        content = follow_chunk.choices[0].delta.content
                                        follow_up_response += content
                                        yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                                
                                if follow_up_response:
                                    conversation_history.append({
                                        "role": "assistant",
                                        "content": follow_up_response
                                    })
                        
                        except json.JSONDecodeError as e:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Error parsing function arguments: {str(e)}'})}\n\n"
                        except Exception as e:
                            yield f"data: {json.dumps({'type': 'error', 'message': f'Error executing function: {str(e)}'})}\n\n"
                        
                        function_call_accumulator = None
                        current_function_name = None
                
                # If there isa full response without function calls, just add it to history
                if full_response and not function_call_accumulator:
                    conversation_history.append({
                        "role": "assistant",
                        "content": full_response
                    })
                
                yield "data: [DONE]\n\n"
            
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                yield "data: [DONE]\n\n"
        
        return Response(generate(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


@app.route('/api/conversations/<session_id>', methods=['DELETE'])
def clear_conversation(session_id):
    """Clear conversation history for a session."""
    if session_id in conversations:
        del conversations[session_id]
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port, threaded=True)

