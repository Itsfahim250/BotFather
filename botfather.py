import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import os
import subprocess
import requests
import json
import uuid
import time
import py_compile
import threading
import shutil
from flask import Flask, request, jsonify

# ===================== PURE PYTHON SYSTEM STATS (psutil ছাড়া) =====================

def get_cpu_percent():
    try:
        with open('/proc/stat', 'r') as f:
            line = f.readline().split()
        idle1 = int(line[4])
        total1 = sum(int(x) for x in line[1:])
        time.sleep(0.3)
        with open('/proc/stat', 'r') as f:
            line = f.readline().split()
        idle2 = int(line[4])
        total2 = sum(int(x) for x in line[1:])
        idle_delta = idle2 - idle1
        total_delta = total2 - total1
        return round(100.0 * (1.0 - idle_delta / total_delta), 1)
    except Exception:
        return 0.0

def get_ram_percent():
    try:
        info = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(':')] = int(parts[1])
        total = info.get('MemTotal', 1)
        available = info.get('MemAvailable', 0)
        used = total - available
        return round(100.0 * used / total, 1)
    except Exception:
        return 0.0

def get_disk_percent():
    try:
        result = subprocess.run(['df', '/'], capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if len(lines) >= 2:
            parts = lines[1].split()
            return float(parts[4].replace('%', ''))
    except Exception:
        pass
    return 0.0

# ===================== CONFIG =====================

BOT_TOKEN = "8679289253:AAFhl_Pm3fRIRm0I0O_81ri5FZVYH8n40UI"
ADMIN_ID = 8789987504
PROJECT_LIMIT = 2
USER_DATA_FILE = "users.json"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ===================== DATA MANAGEMENT =====================

def load_user_data():
    if not os.path.exists(USER_DATA_FILE):
        return {}
    try:
        with open(USER_DATA_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_user_data(data):
    with open(USER_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

user_data = load_user_data()

def get_or_create_user(user_id):
    uid = str(user_id)
    if uid not in user_data:
        user_data[uid] = {
            'api_key': str(uuid.uuid4()),
            'projects': {},
            'is_banned': False
        }
        save_user_data(user_data)
    if 'project_count' in user_data[uid]:
        del user_data[uid]['project_count']
        if 'projects' not in user_data[uid]:
            user_data[uid]['projects'] = {}
        save_user_data(user_data)
    return user_data[uid]

# ===================== HELPERS =====================

user_processes = {}
user_state = {}
BASE_DIR = "user_projects"
os.makedirs(BASE_DIR, exist_ok=True)

def get_project_dir(user_id, project_name):
    path = os.path.join(BASE_DIR, str(user_id), project_name)
    os.makedirs(path, exist_ok=True)
    return path

def is_project_running(user_id, project_name):
    key = (user_id, project_name)
    return key in user_processes and user_processes[key].poll() is None

def get_base_url():
    try:
        if 'RENDER_EXTERNAL_URL' in os.environ:
            return os.environ['RENDER_EXTERNAL_URL']
        response = requests.get('https://api.ipify.org', timeout=5)
        return f"http://{response.text}:8080"
    except Exception:
        return "http://localhost:8080"

# ===================== KEYBOARDS =====================

def main_keypad(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(KeyboardButton("🚀 My Projects"), KeyboardButton("⚙️ API Settings"))
    markup.add(KeyboardButton("📊 Server Stats"))
    if user_id == ADMIN_ID:
        markup.add(KeyboardButton("👑 Admin Panel"))
    return markup

def projects_list_panel(user_id):
    info = get_or_create_user(user_id)
    projects = info.get('projects', {})
    markup = InlineKeyboardMarkup(row_width=1)
    for pname in projects:
        running = is_project_running(user_id, pname)
        icon = "🟢" if running else "🔴"
        markup.add(InlineKeyboardButton(f"{icon} {pname}", callback_data=f"open_project:{pname}"))
    limit = float('inf') if user_id == ADMIN_ID else PROJECT_LIMIT
    if len(projects) < limit:
        markup.add(InlineKeyboardButton("➕ New Project", callback_data="new_project"))
    return markup

def project_panel(user_id, project_name):
    running = is_project_running(user_id, project_name)
    status = "🟢 Running" if running else "🔴 Stopped"
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton(f"Status: {status}", callback_data="none"))
    markup.add(
        InlineKeyboardButton("📤 Upload File", callback_data=f"upload_file:{project_name}"),
        InlineKeyboardButton("▶️ Run", callback_data=f"run:{project_name}")
    )
    markup.add(
        InlineKeyboardButton("⏹️ Stop", callback_data=f"stop:{project_name}"),
        InlineKeyboardButton("📜 Console", callback_data=f"console:{project_name}")
    )
    markup.add(
        InlineKeyboardButton("📦 Install Packages", callback_data=f"install_req:{project_name}"),
        InlineKeyboardButton("🗑️ Clear Project", callback_data=f"clear_project:{project_name}")
    )
    markup.add(InlineKeyboardButton("🔙 Back to Projects", callback_data="back_projects"))
    return markup

# ===================== BOT HANDLERS =====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    get_or_create_user(user_id)
    limit_text = "Unlimited" if user_id == ADMIN_ID else PROJECT_LIMIT
    text = f"🤖 **Welcome!**\nYou can manage up to {limit_text} projects. Use the menu below."
    bot.send_message(user_id, text, parse_mode="Markdown", reply_markup=main_keypad(user_id))

@bot.message_handler(func=lambda m: m.text in ["🚀 My Projects", "⚙️ API Settings", "📊 Server Stats", "👑 Admin Panel"])
def handle_keypad_menu(message):
    user_id = message.from_user.id
    text = message.text

    if user_data.get(str(user_id), {}).get('is_banned', False):
        bot.send_message(user_id, "❌ You are banned from using this bot.")
        return

    if text == "🚀 My Projects":
        info = get_or_create_user(user_id)
        projects = info.get('projects', {})
        count = len(projects)
        limit = "Unlimited" if user_id == ADMIN_ID else PROJECT_LIMIT
        bot.send_message(
            user_id,
            f"📁 **Your Projects** ({count}/{limit})\nSelect a project or create a new one:",
            parse_mode="Markdown",
            reply_markup=projects_list_panel(user_id)
        )

    elif text == "⚙️ API Settings":
        user_info = get_or_create_user(user_id)
        api_key = user_info['api_key']
        base_url = get_base_url()
        api_msg = f"""🔑 **API Settings & Instructions**

*Your API Key:* `{api_key}`
*Base URL:* `{base_url}`

🤖 **Endpoints:**
- `POST {base_url}/create_bot`
- `POST {base_url}/update_bot`
- `POST {base_url}/delete_bot`

*Note:* All requests require `"api_key"` in JSON body.
"""
        bot.send_message(user_id, api_msg, parse_mode="Markdown")

    elif text == "📊 Server Stats":
        cpu = get_cpu_percent()
        ram = get_ram_percent()
        disk = get_disk_percent()
        bot.send_message(
            user_id,
            f"📊 **Server Status**\nCPU: {cpu}%\nRAM: {ram}%\nDisk: {disk}%",
            parse_mode="Markdown"
        )

    elif text == "👑 Admin Panel" and user_id == ADMIN_ID:
        total_users = len(user_data)
        active_processes = len(user_processes)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast"))
        markup.add(
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")
        )
        bot.send_message(
            user_id,
            f"👑 **Admin Panel**\nUsers: {total_users} | Active Bots: {active_processes}",
            parse_mode="Markdown",
            reply_markup=markup
        )

# ===================== CALLBACK HANDLERS =====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    if user_data.get(str(user_id), {}).get('is_banned', False):
        bot.answer_callback_query(call.id, "❌ Banned", show_alert=True)
        return

    try:
        if data == "none":
            bot.answer_callback_query(call.id)
            return

        if data == "back_projects":
            bot.answer_callback_query(call.id)
            info = get_or_create_user(user_id)
            projects = info.get('projects', {})
            count = len(projects)
            limit = "Unlimited" if user_id == ADMIN_ID else PROJECT_LIMIT
            bot.edit_message_text(
                f"📁 **Your Projects** ({count}/{limit})\nSelect a project or create a new one:",
                chat_id=user_id,
                message_id=call.message.message_id,
                parse_mode="Markdown",
                reply_markup=projects_list_panel(user_id)
            )
            return

        if data == "new_project":
            info = get_or_create_user(user_id)
            limit = float('inf') if user_id == ADMIN_ID else PROJECT_LIMIT
            if len(info.get('projects', {})) >= limit:
                bot.answer_callback_query(call.id, "❌ Project limit reached!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            msg = bot.send_message(user_id, "📝 Enter a name for your new project (letters, numbers, underscores only):")
            user_state[user_id] = {'action': 'create_project'}
            bot.register_next_step_handler(msg, process_create_project)
            return

        if data.startswith("open_project:"):
            project_name = data.split(":", 1)[1]
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                f"📂 **Project: {project_name}**\nManage your project below:",
                chat_id=user_id,
                message_id=call.message.message_id,
                parse_mode="Markdown",
                reply_markup=project_panel(user_id, project_name)
            )
            return

        if data.startswith("upload_file:"):
            project_name = data.split(":", 1)[1]
            bot.answer_callback_query(call.id)
            msg = bot.send_message(user_id, f"📤 Send your file for **{project_name}** (.py, .env, requirements.txt only):", parse_mode="Markdown")
            user_state[user_id] = {'action': 'upload_file', 'project': project_name}
            bot.register_next_step_handler(msg, process_file_upload)
            return

        if data.startswith("run:"):
            project_name = data.split(":", 1)[1]
            user_dir = get_project_dir(user_id, project_name)
            py_files = [f for f in os.listdir(user_dir) if f.endswith('.py')]
            if not py_files:
                bot.answer_callback_query(call.id, "❌ No Python file found!", show_alert=True)
                return
            main_file = "main.py" if "main.py" in py_files else py_files[0]
            key = (user_id, project_name)
            if key in user_processes and user_processes[key].poll() is None:
                bot.answer_callback_query(call.id, "⚠️ Already running!", show_alert=True)
                return
            log_path = os.path.join(user_dir, "console.log")
            with open(log_path, "w") as log_file:
                process = subprocess.Popen(
                    ["python3", main_file],
                    cwd=user_dir,
                    stdout=log_file,
                    stderr=subprocess.STDOUT
                )
            time.sleep(2)
            if process.poll() is not None:
                bot.answer_callback_query(call.id, "❌ Bot crashed! Check console.", show_alert=True)
            else:
                user_processes[key] = process
                bot.answer_callback_query(call.id, "✅ Bot is running!")
            bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=call.message.message_id,
                reply_markup=project_panel(user_id, project_name)
            )
            return

        if data.startswith("stop:"):
            project_name = data.split(":", 1)[1]
            key = (user_id, project_name)
            if key in user_processes and user_processes[key].poll() is None:
                user_processes[key].terminate()
                user_processes.pop(key)
                bot.answer_callback_query(call.id, "🛑 Bot stopped.")
            else:
                bot.answer_callback_query(call.id, "Bot is not running.")
            bot.edit_message_reply_markup(
                chat_id=user_id,
                message_id=call.message.message_id,
                reply_markup=project_panel(user_id, project_name)
            )
            return

        if data.startswith("console:"):
            project_name = data.split(":", 1)[1]
            user_dir = get_project_dir(user_id, project_name)
            log_path = os.path.join(user_dir, "console.log")
            if os.path.exists(log_path):
                with open(log_path, "r") as f:
                    logs = f.read().strip()
                log_text = logs[-3000:] if logs else "Empty"
                bot.answer_callback_query(call.id)
                bot.send_message(
                    user_id,
                    f"📜 **Console [{project_name}]:**\n```\n{log_text}\n```",
                    parse_mode="Markdown"
                )
            else:
                bot.answer_callback_query(call.id, "No logs yet.", show_alert=True)
            return

        if data.startswith("install_req:"):
            project_name = data.split(":", 1)[1]
            user_dir = get_project_dir(user_id, project_name)
            req_path = os.path.join(user_dir, "requirements.txt")
            if not os.path.exists(req_path):
                bot.answer_callback_query(call.id, "❌ No requirements.txt found! Upload it first.", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.send_message(user_id, f"📦 Installing packages for **{project_name}**... Please wait.", parse_mode="Markdown")

            def do_install():
                try:
                    result = subprocess.run(
                        ["pip", "install", "-r", req_path, "--break-system-packages"],
                        capture_output=True,
                        text=True,
                        timeout=180
                    )
                    output = (result.stdout + result.stderr)[-2000:]
                    if result.returncode == 0:
                        bot.send_message(user_id, f"✅ **Packages installed!**\n```\n{output}\n```", parse_mode="Markdown")
                    else:
                        bot.send_message(user_id, f"❌ **Install failed:**\n```\n{output}\n```", parse_mode="Markdown")
                except subprocess.TimeoutExpired:
                    bot.send_message(user_id, "❌ Installation timed out (180s).")
                except Exception as e:
                    bot.send_message(user_id, f"❌ Error: {e}")

            threading.Thread(target=do_install, daemon=True).start()
            return

        if data.startswith("clear_project:"):
            project_name = data.split(":", 1)[1]
            key = (user_id, project_name)
            if key in user_processes and user_processes[key].poll() is None:
                bot.answer_callback_query(call.id, "⚠️ Stop the bot first!", show_alert=True)
                return
            user_dir = get_project_dir(user_id, project_name)
            for file in os.listdir(user_dir):
                fp = os.path.join(user_dir, file)
                if os.path.isfile(fp):
                    os.remove(fp)
            bot.answer_callback_query(call.id, "🗑️ Project files cleared!", show_alert=True)
            return

        if data == "admin_broadcast" and user_id == ADMIN_ID:
            bot.answer_callback_query(call.id)
            msg = bot.send_message(user_id, "📢 Enter the message to broadcast:")
            bot.register_next_step_handler(msg, process_broadcast)
            return

        if data == "admin_ban" and user_id == ADMIN_ID:
            bot.answer_callback_query(call.id)
            msg = bot.send_message(user_id, "🚫 Enter user ID to ban:")
            bot.register_next_step_handler(msg, process_ban)
            return

        if data == "admin_unban" and user_id == ADMIN_ID:
            bot.answer_callback_query(call.id)
            msg = bot.send_message(user_id, "✅ Enter user ID to unban:")
            bot.register_next_step_handler(msg, process_unban)
            return

    except Exception as e:
        print(f"Callback Error: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred.")

# ===================== STEP HANDLERS =====================

def process_create_project(message):
    user_id = message.from_user.id
    name = message.text.strip()

    if not name.replace("_", "").replace("-", "").isalnum() or len(name) > 32:
        msg = bot.send_message(user_id, "❌ Invalid name. Use letters, numbers, hyphens, underscores only (max 32 chars).\n📝 Enter project name again:")
        bot.register_next_step_handler(msg, process_create_project)
        return

    info = get_or_create_user(user_id)
    if name in info.get('projects', {}):
        bot.send_message(user_id, f"❌ Project **{name}** already exists!", parse_mode="Markdown")
        return

    limit = float('inf') if user_id == ADMIN_ID else PROJECT_LIMIT
    if len(info.get('projects', {})) >= limit:
        bot.send_message(user_id, "❌ Project limit reached!")
        return

    user_data[str(user_id)]['projects'][name] = {'created_at': time.time()}
    save_user_data(user_data)
    get_project_dir(user_id, name)

    bot.send_message(
        user_id,
        f"✅ Project **{name}** created!\nManage it below:",
        parse_mode="Markdown",
        reply_markup=project_panel(user_id, name)
    )

def process_file_upload(message):
    user_id = message.from_user.id
    state = user_state.get(user_id, {})
    project_name = state.get('project')

    if not project_name:
        bot.send_message(user_id, "❌ Session expired. Go to My Projects again.")
        return

    user_dir = get_project_dir(user_id, project_name)

    if message.content_type == 'document':
        file_name = message.document.file_name
        ext = os.path.splitext(file_name)[1].lower()

        if ext not in ['.py', '.env', '.txt']:
            bot.send_message(user_id, "❌ Only .py, .env, or .txt files are allowed.")
            return

        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_path = os.path.join(user_dir, file_name)

        with open(file_path, 'wb') as f:
            f.write(downloaded_file)

        if ext == '.py':
            try:
                py_compile.compile(file_path, doraise=True)
            except Exception as e:
                os.remove(file_path)
                bot.send_message(
                    user_id,
                    f"❌ **Syntax Error:**\n```\n{str(e)}\n```\nFile was NOT saved.",
                    parse_mode="Markdown"
                )
                return

        bot.send_message(
            user_id,
            f"✅ `{file_name}` uploaded to **{project_name}**!",
            parse_mode="Markdown",
            reply_markup=project_panel(user_id, project_name)
        )
    else:
        bot.send_message(user_id, "❌ Please send a valid document file.")

    user_state.pop(user_id, None)

def process_broadcast(message):
    if message.from_user.id != ADMIN_ID:
        return
    text = message.text
    success = 0
    for uid in user_data:
        try:
            bot.send_message(int(uid), f"📢 **Broadcast:**\n{text}", parse_mode="Markdown")
            success += 1
        except Exception:
            pass
    bot.send_message(ADMIN_ID, f"✅ Broadcast sent to {success} users.")

def process_ban(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target = str(int(message.text.strip()))
        if target in user_data:
            user_data[target]['is_banned'] = True
            save_user_data(user_data)
            bot.send_message(ADMIN_ID, f"✅ User {target} banned.")
        else:
            bot.send_message(ADMIN_ID, "❌ User not found.")
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Invalid user ID.")

def process_unban(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        target = str(int(message.text.strip()))
        if target in user_data:
            user_data[target]['is_banned'] = False
            save_user_data(user_data)
            bot.send_message(ADMIN_ID, f"✅ User {target} unbanned.")
        else:
            bot.send_message(ADMIN_ID, "❌ User not found.")
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ Invalid user ID.")

# ===================== FLASK API SERVER =====================

def get_user_by_api_key(api_key):
    for uid, data in user_data.items():
        if data.get('api_key') == api_key:
            return uid
    return None

@app.route('/create_bot', methods=['POST'])
def api_create_bot():
    data = request.json
    api_key = data.get('api_key')
    code = data.get('code')
    project = data.get('project', 'api_project')
    user_id = get_user_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Invalid API Key"}), 403
    user_dir = get_project_dir(int(user_id), project)
    with open(os.path.join(user_dir, 'main.py'), 'w') as f:
        f.write(code)
    info = get_or_create_user(int(user_id))
    if project not in info.get('projects', {}):
        user_data[user_id]['projects'][project] = {'created_at': time.time()}
        save_user_data(user_data)
    return jsonify({"status": "success", "message": "Bot created successfully!"})

@app.route('/update_bot', methods=['POST'])
def api_update_bot():
    data = request.json
    api_key = data.get('api_key')
    code = data.get('code')
    project = data.get('project', 'api_project')
    user_id = get_user_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 403
    user_dir = get_project_dir(int(user_id), project)
    with open(os.path.join(user_dir, 'main.py'), 'w') as f:
        f.write(code)
    uid_int = int(user_id)
    key = (uid_int, project)
    if key in user_processes:
        user_processes[key].terminate()
        time.sleep(1)
        log_file = open(os.path.join(user_dir, "console.log"), "w")
        process = subprocess.Popen(["python3", "main.py"], cwd=user_dir, stdout=log_file, stderr=subprocess.STDOUT)
        user_processes[key] = process
    return jsonify({"status": "success", "message": "Bot updated and restarted!"})

@app.route('/delete_bot', methods=['POST'])
def api_delete_bot():
    data = request.json
    api_key = data.get('api_key')
    project = data.get('project', 'api_project')
    user_id = get_user_by_api_key(api_key)
    if not user_id:
        return jsonify({"status": "error", "message": "Unauthorized API Key"}), 403
    uid_int = int(user_id)
    key = (uid_int, project)
    if key in user_processes:
        user_processes[key].terminate()
        del user_processes[key]
    user_dir = get_project_dir(uid_int, project)
    shutil.rmtree(user_dir, ignore_errors=True)
    if project in user_data.get(user_id, {}).get('projects', {}):
        del user_data[user_id]['projects'][project]
        save_user_data(user_data)
    return jsonify({"status": "success", "message": "Bot deleted securely!"})

def run_flask():
    app.run(host="0.0.0.0", port=8080, use_reloader=False)

# ===================== MAIN =====================

if __name__ == "__main__":
    print("Starting API Server in background...")
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot is running...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)