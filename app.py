import os
import threading  # <--- NEW IMPORT
from flask import Flask, request, jsonify
from flask_cors import CORS
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

if not TWILIO_AUTH_TOKEN:
    raise ValueError("No Twilio Auth Token found. Make sure .env file exists.")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Store call data AND the synchronization events
call_data_store = {}

@app.route('/make-call', methods=['POST'])
def make_call():
    data = request.json
    user_number = data.get('number')
    server_url = request.host_url 

    try:
        # 1. Start the call
        call = client.calls.create(
            to=user_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{server_url}voice-logic",
            method='POST',
            status_callback=f"{server_url}call-status",
            status_callback_event=['completed']
        )
        
        # 2. Create a "Pause Button" (Event) for this specific call
        call_complete_event = threading.Event()
        
        call_data_store[call.sid] = {
            'status': 'initiated', 
            'transcription': None,
            'event': call_complete_event  # Store the event so we can trigger it later
        }
        
        print(f"Waiting for user {user_number} to speak...")
        
        # 3. PAUSE HERE! Wait up to 60 seconds for the user to speak
        # The code stops on this line until 'event.set()' is called in handle_recording
        is_completed = call_complete_event.wait(timeout=60)
        
        # 4. If we get here, either the user spoke OR 60 seconds passed
        if is_completed:
            final_text = call_data_store[call.sid]['transcription']
            return jsonify({
                'status': 'success',
                'call_sid': call.sid,
                'user_response': final_text
            })
        else:
            return jsonify({
                'status': 'timeout', 
                'message': 'User did not respond within 60 seconds.'
            }), 408

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/voice-logic', methods=['GET', 'POST'])
def voice_logic():
    server_url = request.host_url
    resp = VoiceResponse()
    
    resp.say("Hello. Please say your full name clearly.", voice='alice', language='en-IN')
    
    # Listen for speech
    gather = resp.gather(
        input='speech', 
        language='en-IN', 
        speech_timeout='auto',
        action=f"{server_url}handle-recording",
        method='POST'
    )
    
    resp.say("We did not hear anything. Goodbye.", voice='alice', language='en-IN')
    return str(resp)

@app.route('/handle-recording', methods=['GET', 'POST'])
def handle_recording():
    """Called by Twilio when the user stops speaking"""
    call_sid = request.values.get('CallSid')
    speech_text = request.values.get('SpeechResult') 
    
    print(f"DEBUG: Speech received for {call_sid}: {speech_text}")
    
    if call_sid in call_data_store:
        # 1. Save the text
        if speech_text:
            call_data_store[call_sid]['transcription'] = speech_text
            call_data_store[call_sid]['status'] = 'completed'
        else:
            call_data_store[call_sid]['transcription'] = "(No speech detected)"
            
        # 2. PRESS THE PLAY BUTTON!
        # This tells the waiting 'make_call' function to wake up and finish
        if 'event' in call_data_store[call_sid]:
            call_data_store[call_sid]['event'].set()
        
    resp = VoiceResponse()
    if speech_text:
        resp.say(f"Thank you, {speech_text}. We have recorded your response.", voice='alice', language='en-IN')
    else:
        resp.say("Thank you. Goodbye.", voice='alice', language='en-IN')
        
    return str(resp)

@app.route('/call-status', methods=['GET', 'POST'])
def call_status():
    """Handle call completion events (hangups)"""
    call_sid = request.values.get('CallSid')
    call_status = request.values.get('CallStatus')
    
    # If user hangs up without speaking, we still need to unblock the API
    if call_status in ['completed', 'failed', 'busy', 'no-answer']:
        if call_sid in call_data_store and 'event' in call_data_store[call_sid]:
             # If we haven't set a transcription yet, set it to "Call Ended"
             if not call_data_store[call_sid]['transcription']:
                 call_data_store[call_sid]['transcription'] = "User hung up or did not answer."
             call_data_store[call_sid]['event'].set()

    return "OK", 200

# We don't strictly need get-response anymore, but keeping it is fine
@app.route('/get-response/<call_sid>', methods=['GET'])
def get_response(call_sid):
    result = call_data_store.get(call_sid)
    # Remove the event object before returning JSON (events aren't JSON serializable)
    if result:
        response_data = result.copy()
        response_data.pop('event', None) 
        return jsonify(response_data)
    return jsonify({'error': 'Call SID not found'}), 404


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "active",
        "service": "calling-agent",
        "message": "I am awake!"
    }), 200

if __name__ == '__main__':
    # threaded=True is required so the "wait" doesn't block the "handle_recording" request!
    app.run(debug=True, port=5000, threaded=True)