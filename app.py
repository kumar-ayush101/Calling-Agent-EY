import os
from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv  # Import this

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- CONFIGURATION ---
# Now we read from the secure .env file instead of hardcoding
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Check if keys loaded correctly (Optional safety check)
if not TWILIO_AUTH_TOKEN:
    raise ValueError("No Twilio Auth Token found. Make sure .env file exists.")

# Store call data in memory
call_data_store = {}

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

@app.route('/make-call', methods=['POST'])
def make_call():
    data = request.json
    user_number = data.get('number')
    server_url = request.host_url 

    try:
        call = client.calls.create(
            to=user_number,
            from_=TWILIO_PHONE_NUMBER,
            # We explicitly tell Twilio to use POST to avoid confusion, 
            # but our routes below now support GET too just in case.
            url=f"{server_url}voice-logic",
            method='POST',
            status_callback=f"{server_url}call-status",
            status_callback_event=['completed']
        )
        
        call_data_store[call.sid] = {
            'status': 'initiated', 
            'recording_url': None,
            'transcription': 'Processing...' 
        }
        
        return jsonify({
            'message': 'Call Initiated.', 
            'call_sid': call.sid,
            'check_status_url': f"{server_url}get-response/{call.sid}"
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# FIX: Allow GET and POST so Twilio doesn't get a 405 Error
# --- REPLACE THESE TWO FUNCTIONS IN YOUR APP.PY ---

@app.route('/voice-logic', methods=['GET', 'POST'])
def voice_logic():
    """Instructions for the call"""
    server_url = request.host_url
    resp = VoiceResponse()
    
    # 1. Use Indian English voice so the user subconsciously matches the accent
    resp.say("Hello. Please say your full name clearly after the beep.", voice='alice', language='en-IN')
    
    # 2. Use <Gather> instead of <Record>
    # input='speech': We want speech-to-text
    # language='en-IN': Optimized for Indian accents
    # speechTimeout='auto': Detects when they stop speaking automatically
    gather = resp.gather(
        input='speech', 
        language='en-IN', 
        speech_timeout='auto',
        action=f"{server_url}handle-recording",
        method='POST'
    )
    
    # If they stay silent for 5 seconds, this runs:
    resp.say("We did not hear anything. Goodbye.", voice='alice', language='en-IN')
    
    return str(resp)

@app.route('/handle-recording', methods=['GET', 'POST'])
def handle_recording():
    """Called immediately after they stop speaking"""
    
    # <Gather> sends the text in 'SpeechResult'
    # It also sends a recording URL if we asked for it, but here we prioritize text
    call_sid = request.values.get('CallSid')
    speech_text = request.values.get('SpeechResult') # <--- THIS IS THE TEXT
    confidence = request.values.get('Confidence')    # How sure is the AI? (0.0 to 1.0)

    print(f"DEBUG: Speech received: {speech_text} (Confidence: {confidence})")
    
    if call_sid in call_data_store:
        if speech_text:
            call_data_store[call_sid]['transcription'] = speech_text
            call_data_store[call_sid]['status'] = 'completed'
        else:
            call_data_store[call_sid]['transcription'] = "(No speech detected)"
        
    resp = VoiceResponse()
    # Confirm what we heard to the user (Optional but cool for demos)
    if speech_text:
        resp.say(f"Thank you, {speech_text}. We have recorded your response.", voice='alice', language='en-IN')
    else:
        resp.say("Thank you. Goodbye.", voice='alice', language='en-IN')
        
    return str(resp)


# FIX: Allow GET and POST
@app.route('/handle-transcription', methods=['GET', 'POST'])
def handle_transcription():
    """Called by Twilio when text is ready"""
    call_sid = request.values.get('CallSid')
    transcription_text = request.values.get('TranscriptionText')
    
    if call_sid in call_data_store:
        call_data_store[call_sid]['transcription'] = transcription_text
        call_data_store[call_sid]['status'] = 'completed'
        print(f"Transcription Received for {call_sid}: {transcription_text}")
        
    return "OK", 200

# Optional: Handle status updates to avoid 404 errors in logs
@app.route('/call-status', methods=['GET', 'POST'])
def call_status():
    return "OK", 200

@app.route('/get-response/<call_sid>', methods=['GET'])
def get_response(call_sid):
    """Frontend polls this to get the final text"""
    result = call_data_store.get(call_sid)
    if result:
        return jsonify(result)
    return jsonify({'error': 'Call SID not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)