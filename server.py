from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import json
import random
import os
import uuid
from datetime import datetime

app = Flask(__name__)
CORS(app)

DATA_FILE = os.path.join(os.path.dirname(__file__), 'presets.json')


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"enabled": False, "presets": []}


def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ────────────────────────────────────────────────
# 静态页面
# ────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route('/')
def index():
    return send_from_directory(BASE_DIR, '随机数生成器.html')


@app.route('/admin')
def admin():
    return send_from_directory(BASE_DIR, 'admin.html')


@app.route('/<path:filename>')
def serve_static(filename):
    """兜底：从当前目录提供所有静态文件（图片、CSS 等）"""
    return send_from_directory(BASE_DIR, filename)


# ────────────────────────────────────────────────
# 生成数字（前台调用）
# ────────────────────────────────────────────────

@app.route('/api/generate', methods=['POST'])
def generate():
    body = request.get_json()
    count   = int(body.get('count', 10))
    min_val = int(body.get('min', 0))
    max_val = int(body.get('max', 100))
    type_   = body.get('type', 'unique')

    data = load_data()

    # 预设模式开启时，查找匹配的预设
    if data.get('enabled', False):
        for i, preset in enumerate(data['presets']):
            if (preset['count']  == count   and
                preset['min']    == min_val  and
                preset['max']    == max_val  and
                preset['type']   == type_    and
                preset.get('remaining_uses', 0) > 0):

                numbers = preset['numbers'].copy()
                random.shuffle(numbers)

                data['presets'][i]['remaining_uses'] -= 1
                save_data(data)

                return jsonify({
                    'numbers': numbers,
                    'preset_used': True,
                    'preset_id': preset['id'],
                    'remaining_uses': data['presets'][i]['remaining_uses']
                })

    # 真随机模式
    if type_ == 'unique':
        pool_size    = max_val - min_val + 1
        actual_count = min(count, pool_size)
        numbers      = random.sample(range(min_val, max_val + 1), actual_count)
    else:
        numbers = [random.randint(min_val, max_val) for _ in range(count)]

    return jsonify({'numbers': numbers, 'preset_used': False})


# ────────────────────────────────────────────────
# 状态查询与开关（后台调用）
# ────────────────────────────────────────────────

@app.route('/api/status', methods=['GET'])
def get_status():
    data = load_data()
    return jsonify({
        'enabled': data.get('enabled', False),
        'presets': data.get('presets', [])
    })


@app.route('/api/toggle', methods=['POST'])
def toggle():
    data = load_data()
    data['enabled'] = not data.get('enabled', False)
    save_data(data)
    return jsonify({'enabled': data['enabled']})


# ────────────────────────────────────────────────
# 预设管理（后台调用）
# ────────────────────────────────────────────────

@app.route('/api/presets', methods=['GET'])
def get_presets():
    data = load_data()
    return jsonify(data.get('presets', []))


@app.route('/api/presets', methods=['POST'])
def add_preset():
    body = request.get_json()

    # numbers 支持字符串（逗号分隔）或数组
    raw = body.get('numbers', [])
    if isinstance(raw, str):
        numbers = [int(x.strip()) for x in raw.split(',') if x.strip()]
    else:
        numbers = [int(x) for x in raw]

    count   = int(body['count'])
    min_val = int(body['min'])
    max_val = int(body['max'])
    type_   = body.get('type', 'unique')
    uses    = int(body.get('uses', 1))

    # 校验
    errors = []
    if len(numbers) != count:
        errors.append(f'预设数字个数（{len(numbers)}）与数目（{count}）不符')
    for n in numbers:
        if not (min_val <= n <= max_val):
            errors.append(f'数字 {n} 不在 [{min_val}, {max_val}] 范围内')
    if type_ == 'unique' and len(numbers) != len(set(numbers)):
        errors.append('唯一模式下预设数字中存在重复值')
    if errors:
        return jsonify({'error': '；'.join(errors)}), 400

    data = load_data()
    preset = {
        'id':             str(uuid.uuid4()),
        'count':          count,
        'min':            min_val,
        'max':            max_val,
        'type':           type_,
        'numbers':        numbers,
        'remaining_uses': uses,
        'total_uses':     uses,
        'created_at':     datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    data['presets'].append(preset)
    save_data(data)
    return jsonify(preset), 201


@app.route('/api/presets/<preset_id>', methods=['DELETE'])
def delete_preset(preset_id):
    data = load_data()
    data['presets'] = [p for p in data['presets'] if p['id'] != preset_id]
    save_data(data)
    return jsonify({'success': True})


@app.route('/api/presets/<preset_id>/reset', methods=['POST'])
def reset_preset(preset_id):
    data = load_data()
    for preset in data['presets']:
        if preset['id'] == preset_id:
            preset['remaining_uses'] = preset.get('total_uses', 1)
            save_data(data)
            return jsonify(preset)
    return jsonify({'error': '未找到该预设'}), 404


@app.route('/api/presets/<preset_id>/uses', methods=['PATCH'])
def update_uses(preset_id):
    body = request.get_json()
    uses = int(body.get('uses', 1))
    data = load_data()
    for preset in data['presets']:
        if preset['id'] == preset_id:
            preset['remaining_uses'] = uses
            preset['total_uses']     = uses
            save_data(data)
            return jsonify(preset)
    return jsonify({'error': '未找到该预设'}), 404


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    print(f'前台页面: http://localhost:{port}/')
    print(f'后台管理: http://localhost:{port}/admin')
    app.run(debug=debug, port=port, host='0.0.0.0')
