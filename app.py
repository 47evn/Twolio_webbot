from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import google.generativeai as genai
import requests
import sys
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.append(r"D:\testing\webbot")  # adjust path if needed
from helpers import default_instruction

GOOGLE_API_KEY = "AIzaSyD52ImyueMUNql1-uCbbgEK4Ie9K14JRUI"
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

app = Flask(__name__)
CORS(app)

access_token = None

def authenticate_bot():
    global access_token
    url = "https://bi.siissoft.com/secureappointment/api/v1/auth/login"
    payload = {
        "username": "bot@siissoft.it",
        "password": "Dana"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        access_token = data.get("auth", {}).get("access_token")
        print("✅ Access token retrieved.")
    except Exception as e:
        print(f"❌ Auth failed: {e}")

authenticate_bot()

def fetch_group_info(headers, group_id):
    try:
        url = f"https://bi.siissoft.com/secureappointment/api/v1/groups/{group_id}"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return resp.json().get("group", {})
    except Exception as e:
        print(f"⚠️ Group API Error: {e}")
    return {}

def fetch_professionals(headers, group_id):
    try:
        url = "https://bi.siissoft.com/secureappointment/api/v1/professionals"
        body = {"groupId": group_id, "format": "whatsapp"}
        resp = requests.get(url, headers=headers, json=body, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"⚠️ Professionals API Error: {e}")
    return {}

def fetch_slots(headers, group_id):
    try:
        url = f"https://bi.siissoft.com/secureappointment/api/v1/slots/{group_id}"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"⚠️ Slots API Error: {e}")
    return {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    global access_token
    data = request.json
    user_prompt = data.get('prompt', '').strip()

    user_context = {
        "id": data.get("id"),
        "name": data.get("name"),
        "surname": data.get("surname"),
        "phone_number": data.get("phone_number"),
        "email": data.get("email"),
        "group_id": data.get("current_group_id")
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Run 3 API calls concurrently
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(fetch_group_info, headers, user_context["group_id"]): "group",
            executor.submit(fetch_professionals, headers, user_context["group_id"]): "professionals",
            executor.submit(fetch_slots, headers, user_context["group_id"]): "slots"
        }
        results = {"group": {}, "professionals": {}, "slots": {}}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                print(f"⚠️ {key.capitalize()} API concurrency error: {e}")

    group_info = results["group"]
    professionals_info = results["professionals"]
    slots_info = results["slots"]

    # Compose prompt text for Gemini
    user_info_text = (
        f"\n[User Info]\n"
        f"ID: {user_context.get('id')}, "
        f"Name: {user_context.get('name')} {user_context.get('surname')}, "
        f"Email: {user_context.get('email')}, "
        f"Phone: {user_context.get('phone_number')}, "
        f"Group ID: {user_context.get('group_id')}\n"
    )

    group_info_text = (
        f"[Group Info]\n"
        f"Name: {group_info.get('name')}\n"
        f"Description: {group_info.get('description')}\n"
        f"Website: {group_info.get('website')}\n"
        f"VOIP: {group_info.get('telephone_voip')}, "
        f"Virtual: {group_info.get('telephone_virtual')}\n"
        f"Primary Color: {group_info.get('color_primary')}, Accent: {group_info.get('color_accent')}\n"
        f"Logo: {group_info.get('logo')}\n\n"
    ) if group_info else "[Group Info]\n⚠️ Not available.\n\n"

    professionals_text = f"[Professionals Info]\n{professionals_info}\n\n" if professionals_info else "[Professionals Info]\n⚠️ Not available.\n\n"

    slots_text = f"[Available Slots to Book Appointment]\n{slots_info}\n\n" if slots_info else "[Available Slots to Book Appointment]\n⚠️ Not available.\n\n"

    full_prompt = f"{default_instruction}\n{user_info_text}{group_info_text}{professionals_text}{slots_text}User: {user_prompt}\nAI:"

    print(f"\n🧾 Full Prompt to Gemini:\n{full_prompt}")

    try:
        response = model.generate_content(full_prompt)
        ai_reply = response.text.strip()

        # Check for INFO:<endpoint> in AI response
        match = re.search(r'INFO:\s*(\S+)', ai_reply)
        if match:
            endpoint = match.group(1)
            info_url = f"https://bi.siissoft.com/secureappointment/api/v1/info/{endpoint}"
            info_response = requests.get(info_url, headers=headers, json={"format": "webbot"})
            return jsonify({'response': info_response.json().get("message", "✅ Success but no message.")})

        return jsonify({'response': ai_reply})
    except Exception as e:
        return jsonify({'response': f"❌ Gemini Error: {str(e)}"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # fallback to 5000 for local dev
    app.run(host='0.0.0.0', port=port)