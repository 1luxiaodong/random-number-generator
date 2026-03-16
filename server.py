from flask import (Flask, request, jsonify, send_from_directory,
                   session, redirect)
from flask_cors import CORS
from functools import wraps
import json, random, os, uuid
from datetime import datetime

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = 'rng-admin-xK9mP2vL-2026'

ADMIN_PASSWORD = 'qazwsxedc'
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'presets.json')
DEFAULT_DATA = {"enabled": False, "presets": []}

try:
    from replit import db as replit_db
    USE_REPLIT_DB = True
except ImportError:
    USE_REPLIT_DB = False


def normalize_data(data):
    if not isinstance(data, dict):
        return dict(DEFAULT_DATA)
    enabled = bool(data.get('enabled', False))
    presets = data.get('presets', [])
    if not isinstance(presets, list):
        presets = []
    return {'enabled': enabled, 'presets': presets}


def load_data():
    if USE_REPLIT_DB:
        try:
            raw = replit_db.get('rng_data')
            if raw:
                return normalize_data(json.loads(raw))
        except Exception:
            pass
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return normalize_data(json.load(f))
        except Exception:
            pass
    return dict(DEFAULT_DATA)


def save_data(data):
    normalized = normalize_data(data)
    if USE_REPLIT_DB:
        try:
            replit_db['rng_data'] = json.dumps(normalized, ensure_ascii=False)
            return
        except Exception:
            pass
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)


# ── 权限装饰器 ─────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            if request.is_json:
                return jsonify({'error': '未授权'}), 401
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated


# ── 静态页面 ──────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, '随机数生成器.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        body = request.get_json() or {}
        pwd  = body.get('password', '') or request.form.get('password', '')
        if pwd == ADMIN_PASSWORD:
            session['is_admin'] = True
            return jsonify({'success': True})
        return jsonify({'error': '密码错误'}), 401
    return send_from_directory(BASE_DIR, 'login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    return redirect('/admin/login')

@app.route('/admin')
@admin_required
def admin():
    return send_from_directory(BASE_DIR, 'admin.html')


# ── API 路由（必须放在 /<path> 之前，否则会被静态路由拦截）──

@app.route('/api/generate', methods=['POST'])
def generate():
    body    = request.get_json(silent=True) or {}
    count   = int(body.get('count', 10))
    min_val = int(body.get('min',   0))
    max_val = int(body.get('max',   100))
    type_   = body.get('type', 'unique')
    # 用户端「随便」发 open，管理端存 repeat，统一映射
    if type_ == 'open':
        type_ = 'repeat'

    data = load_data()

    # 预设模式：只要开关开着就一直触发（无次数限制）
    if data.get('enabled', False):
        for preset in data['presets']:
            ptype = preset['type']
            if ptype == 'open':
                ptype = 'repeat'
            if (preset['count'] == count  and
                preset['min']   == min_val and
                preset['max']   == max_val and
                ptype == type_):
                numbers = preset['numbers'].copy()
                random.shuffle(numbers)
                return jsonify({'numbers': numbers, 'preset_used': True})

    # 真随机
    if type_ == 'unique':
        actual = min(count, max_val - min_val + 1)
        numbers = random.sample(range(min_val, max_val + 1), actual)
    else:
        numbers = [random.randint(min_val, max_val) for _ in range(count)]

    return jsonify({'numbers': numbers, 'preset_used': False})


# ── 管理 API（需登录）────────────────────────────────

@app.route('/api/status', methods=['GET'])
@admin_required
def get_status():
    data = load_data()
    return jsonify({'enabled': data.get('enabled', False),
                    'presets': data.get('presets', [])})

@app.route('/api/toggle', methods=['POST'])
@admin_required
def toggle():
    data = load_data()
    data['enabled'] = not data.get('enabled', False)
    save_data(data)
    return jsonify({'enabled': data['enabled']})

@app.route('/api/presets', methods=['GET'])
@admin_required
def get_presets():
    return jsonify(load_data().get('presets', []))

@app.route('/api/presets', methods=['POST'])
@admin_required
def add_preset():
    body    = request.get_json(silent=True) or {}
    raw     = body.get('numbers', [])
    numbers = [int(x) for x in raw] if isinstance(raw, list) \
              else [int(x.strip()) for x in raw.split(',') if x.strip()]

    count   = int(body['count'])
    min_val = int(body['min'])
    max_val = int(body['max'])
    type_   = body.get('type', 'unique')

    errors = []
    if len(numbers) != count:
        errors.append(f'数字个数（{len(numbers)}）与数目（{count}）不符')
    for n in numbers:
        if not (min_val <= n <= max_val):
            errors.append(f'{n} 不在 [{min_val},{max_val}] 内')
    if type_ == 'unique' and len(numbers) != len(set(numbers)):
        errors.append('唯一模式下存在重复值')
    if errors:
        return jsonify({'error': '；'.join(errors)}), 400

    data   = load_data()
    preset = {
        'id':         str(uuid.uuid4()),
        'count':      count,
        'min':        min_val,
        'max':        max_val,
        'type':       type_,
        'numbers':    numbers,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    # 同类别覆盖：相同 (count, min, max, type) 只保留一条
    key = (count, min_val, max_val, type_)
    data['presets'] = [p for p in data['presets']
                       if (p['count'], p['min'], p['max'], p['type']) != key]
    data['presets'].append(preset)
    save_data(data)
    return jsonify(preset), 201

@app.route('/api/presets/<pid>', methods=['DELETE'])
@admin_required
def delete_preset(pid):
    data = load_data()
    data['presets'] = [p for p in data['presets'] if p['id'] != pid]
    save_data(data)
    return jsonify({'success': True})


@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(BASE_DIR, filename)


if __name__ == '__main__':
    port  = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    print(f'前台: http://localhost:{port}/')
    print(f'后台: http://localhost:{port}/admin')
    app.run(debug=debug, port=port, host='0.0.0.0')
