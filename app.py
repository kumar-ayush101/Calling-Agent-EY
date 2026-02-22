import os
import threading
import urllib.parse
import requests  # <--- NEW: To call your messaging API
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
MESSAGING_API_URL = "https://eymessaging.onrender.com/sensor-anomaly"

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
call_data_store = {}

@app.route('/make-call', methods=['POST'])
def make_call():
    data = request.json
    user_number = data.get('number')
    issue = data.get('issue', 'Technical problem')
    # CRITICAL: We need vehicle_id to pass to your messaging API later
    vehicle_id = data.get('vehicle_id', 'TOYOTA_202403A#001') 
    server_url = request.host_url 

    encoded_issue = urllib.parse.quote(issue)

    try:
        call = client.calls.create(
            to=user_number,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{server_url}voice-logic?issue={encoded_issue}",
            method='POST',
            status_callback=f"{server_url}call-status",
            status_callback_event=['completed']
        )
        
        call_complete_event = threading.Event()
        call_data_store[call.sid] = {
            'status': 'initiated', 
            'transcription': None,
            'event': call_complete_event,
            'vehicle_id': vehicle_id, # Store for later use
            'issue': issue
        }
        
        is_completed = call_complete_event.wait(timeout=60)
        
        if is_completed:
            final_text = call_data_store[call.sid]['transcription']
            return jsonify({
                'status': 'success',
                'user_choice': final_text
            })
        else:
            return jsonify({'status': 'timeout'}), 408

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/voice-logic', methods=['GET', 'POST'])
def voice_logic():
    issue = request.values.get('issue', 'a vehicle issue')
    server_url = request.host_url
    resp = VoiceResponse()
    
    message = (
        f"Hello Sir. We have detected the issue of {issue} in your vehicle. "
        "To manually choose a service center on WhatsApp, say Book. "
        "To automatically book at the nearest center, say Auto."
    )
    
    resp.say(message, voice='alice', language='en-IN')
    
    resp.gather(
        input='speech', 
        language='en-IN', 
        hints='Book, Auto',
        speech_timeout='auto',
        action=f"{server_url}handle-recording",
        method='POST'
    )
    return str(resp)

@app.route('/handle-recording', methods=['GET', 'POST'])
def handle_recording():
    call_sid = request.values.get('CallSid')
    speech_result = request.values.get('SpeechResult', '').lower() 
    
    print(f"DEBUG: User choice: {speech_result}")
    resp = VoiceResponse()
    
    if call_sid in call_data_store:
        call_data_store[call_sid]['transcription'] = speech_result
        vehicle_id = call_data_store[call_sid]['vehicle_id']
        issue = call_data_store[call_sid]['issue']
        
        # --- TRIGGER EXTERNAL MESSAGING API ---
        if "book" in speech_result:
            try:
                # Trigger the WhatsApp Menu once
                response = requests.post(MESSAGING_API_URL, json={
                    "vehicle_id": vehicle_id,
                    "issue_detected": issue
                }, timeout=10) # Added timeout for safety
                
                print(f"📡 Messaging API Status: {response.status_code}")
                print(f"📡 Messaging API Response: {response.text}")
                
                resp.say("Please check your WhatsApp to select a service center. Goodbye.", voice='alice', language='en-IN')
            except Exception as e:
                print(f"❌ API Call Failed: {e}")
                resp.say("We encountered an error triggering WhatsApp, but our team will contact you. Goodbye.", voice='alice', language='en-IN')
        
        elif "auto" in speech_result:
            print("🤖 Auto Booking Logic Triggered")
            resp.say("Thank you. We are automatically booking your service. Goodbye.", voice='alice', language='en-IN')
        
        else:
            resp.say("Thank you. Your response has been recorded. Goodbye.", voice='alice', language='en-IN')

        # Wake up the Postman request
        if 'event' in call_data_store[call_sid]:
            call_data_store[call_sid]['event'].set()
        
    return str(resp)

@app.route('/call-status', methods=['GET', 'POST'])
def call_status():
    call_sid = request.values.get('CallSid')
    call_status = request.values.get('CallStatus')
    if call_status in ['completed', 'failed', 'busy', 'no-answer']:
        if call_sid in call_data_store and 'event' in call_data_store[call_sid]:
             if not call_data_store[call_sid]['transcription']:
                 call_data_store[call_sid]['transcription'] = "No Response"
             call_data_store[call_sid]['event'].set()
    return "OK", 200

if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True)