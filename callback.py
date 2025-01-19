import json
from flask import Flask, request

app = Flask(__name__)
config = {}

def load_config():
    with open("config.json", "r") as f:
        config = json.load(f)
    with open("config-runtime.json", "r") as f:
        config["runtime"] = json.load(f)
    return config

def save_config(config):
    c = config.copy()
    c['runtime'] = {}
    with open("config.json", "w") as f:
        json.dump(c, f, indent=2)
    with open("config-runtime.json", "w") as f:
        json.dump(config["runtime"], f, indent=2)

@app.route('/callback', methods=['GET'])
def callback():
    code = request.args.get('code')
    state = request.args.get('state')

    if state != config["runtime"]["state"]:
        return "State mismatch", 400
    if code:
        config["runtime"]["user_auth_code"] = code
        save_config(config)
        return "Authorization code received", 200
    else:
        return "No authorization code found.", 400

if __name__ == '__main__':
    config = load_config()
    app.run(port=config['callback_port'])

