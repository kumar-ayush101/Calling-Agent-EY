import os
from flask import Flask, request, jsonify
from flask_cors import CORS  # <--- ADD THIS IMPORT
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# --- ENABLE CORS FOR ALL ROUTES ---
CORS(app)  # <--- THIS LINE ENABLES UNIVERSAL ACCESS

# --- CONFIGURATION ---
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

# Check if keys loaded correctly
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

@app.route('/voice-logic', methods=['GET', 'POST'])
def voice_logic():
    """Instructions for the call"""
    server_url = request.host_url
    resp = VoiceResponse()
    
    # 1. Speak instructions
    resp.say("Hello. Please say your full name clearly after the beep.", voice='alice', language='en-IN')
    
    # 2. Play Beep
    resp.play('https://api.twilio.com/cowbell.mp3') 

    # 3. Gather Speech
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
    """Called immediately after they stop speaking"""
    call_sid = request.values.get('CallSid')
    speech_text = request.values.get('SpeechResult') 
    confidence = request.values.get('Confidence') 

    print(f"DEBUG: Speech received: {speech_text} (Confidence: {confidence})")
    
    if call_sid in call_data_store:
        if speech_text:
            call_data_store[call_sid]['transcription'] = speech_text
            call_data_store[call_sid]['status'] = 'completed'
        else:
            call_data_store[call_sid]['transcription'] = "(No speech detected)"
        
    resp = VoiceResponse()
    if speech_text:
        resp.say(f"Thank you, {speech_text}. We have recorded your response.", voice='alice', language='en-IN')
    else:
        resp.say("Thank you. Goodbye.", voice='alice', language='en-IN')
        
    return str(resp)

@app.route('/handle-transcription', methods=['GET', 'POST'])
def handle_transcription():
    call_sid = request.values.get('CallSid')
    transcription_text = request.values.get('TranscriptionText')
    
    if call_sid in call_data_store:
        call_data_store[call_sid]['transcription'] = transcription_text
        call_data_store[call_sid]['status'] = 'completed'
        print(f"Transcription Received for {call_sid}: {transcription_text}")
        
    return "OK", 200

@app.route('/call-status', methods=['GET', 'POST'])
def call_status():
    return "OK", 200

@app.route('/get-response/<call_sid>', methods=['GET'])
def get_response(call_sid):
    result = call_data_store.get(call_sid)
    if result:
        return jsonify(result)
    return jsonify({'error': 'Call SID not found'}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)