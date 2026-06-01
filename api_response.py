from flask import jsonify
import uuid

def ok(data=None, message="ok", code=200, trace_id=None):
    if trace_id is None:
        trace_id = uuid.uuid4().hex[:12]
    return jsonify({"status": "ok", "message": message, "data": data, "trace_id": trace_id}), code

def err(message="error", code=400, data=None, trace_id=None):
    if trace_id is None:
        trace_id = uuid.uuid4().hex[:12]
    return jsonify({"status": "error", "message": message, "data": data, "trace_id": trace_id}), code
