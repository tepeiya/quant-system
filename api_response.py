from flask import jsonify

def ok(data=None, message="ok", code=200):
    return jsonify({"status": "ok", "message": message, "data": data}), code

def err(message="error", code=400, data=None):
    return jsonify({"status": "error", "message": message, "data": data}), code
