# Webhook server for GitHub Actions deployment
# Run this on the server to receive deploy signals from GitHub

from flask import Flask, request
import subprocess
import hmac
import hashlib

app = Flask(__name__)

# Secret token - must match the one in GitHub Actions
# Change this to a random string!
WEBHOOK_SECRET = "ba64e70ecc6de9999a6f705339b02f2b517e67a89ce23f34652aa7e62e956591"

@app.route('/deploy', methods=['POST'])
def deploy():
    """Receive deploy signal from GitHub Actions."""
    # Verify signature
    signature = request.headers.get('X-Hub-Signature-256', '')
    expected = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode(),
        request.data,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected):
        return {"error": "Unauthorized"}, 401
    
    # Run deploy commands
    try:
        result = subprocess.run(
            [
                'bash', '-c',
                'cd /opt/hermes/scripts/cargonovo_automation && '
                'git pull origin main && '
                'sudo systemctl restart cargonovo-bot && '
                'echo "Deployment completed at $(date)"'
            ],
            capture_output=True,
            text=True,
            timeout=60
        )
        return {
            "success": True,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return {"status": "ok"}

if __name__ == '__main__':
    # Run on all interfaces, port 5000
    app.run(host='0.0.0.0', port=5000)
