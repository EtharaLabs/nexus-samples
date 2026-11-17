"""The OpenAPI document served at /api/v1/openapi.json. Every response field is listed."""

_num = {"type": "number"}
_str = {"type": "string"}
_int = {"type": "integer"}
_bool = {"type": "boolean"}
_strs = {"type": "array", "items": _str}
_err = {"description": "client error", "content": {"application/json": {
    "schema": {"type": "object", "properties": {"error": _str}}}}}


def _ok(schema: dict) -> dict:
    return {"200": {"description": "ok", "content": {"application/json": {"schema": schema}}}}


def _get(summary: str, schema: dict, params: list | None = None) -> dict:
    out = {"summary": summary, "responses": _ok(schema)}
    if params:
        out["parameters"] = params
        out["responses"]["400"] = _err
    return out


def _q(name: str, kind: dict, required: bool = False) -> dict:
    return {"name": name, "in": "query", "required": required, "schema": kind}


_setpoints = {"type": "object", "properties": {
    "g1_mw": _num, "g2_mw": _num, "bat_mw": _num, "pv_curtail": _num, "shed": _strs}}
_packet = {"type": "object", "properties": {
    "rtu": _str, "seq": _int, "uptime_s": _int, "interval_start_h": _num, "interval_end_h": _num,
    "values": {"type": "object", "additionalProperties": {"type": "number", "nullable": True}}}}
_event = {"type": "object", "properties": {
    "hour": _num, "source": _str, "event": _str, "subject": _str, "code": _str, "id": _str,
    "reason": _str, "change": {"type": "object"}, "start_hour": _num, "end_hour": _num}}
_message = {"type": "object", "properties": {
    "id": _str, "issued_hour": _num, "effective_hour": _num, "type": _str, "terms": {"type": "object"}}}

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Ridgeway island energy management system", "version": "1.0"},
    "servers": [{"url": "http://ems-sim:8080"}],
    "paths": {
        "/api/v1/status": {"get": _get("Grid clock, ramp state, change count, raw quota, setpoints", {
            "type": "object", "properties": {
                "plant_hour": _num, "contract_window_open": _bool, "ramp_active": _bool,
                "ramp_remaining_s": _int, "changes_accepted": _int, "raw_quota_remaining": _int,
                "setpoints": _setpoints}})},
        "/api/v1/forecast": {"get": _get("Hourly PV and load forecast issued at hour 0", {
            "type": "object", "properties": {"issued_hour": _int, "hourly": {"type": "array", "items": {
                "type": "object", "properties": {"hour": _int, "pv_mw": _num,
                                                  "load_mw": {"type": "object", "additionalProperties": _num}}}}}})},
        "/api/v1/messages": {"get": _get("The utility system operator's dispatch revisions listed so far", {
            "type": "object", "properties": {"plant_hour": _num, "messages": {
                "type": "array", "items": _message}}})},
        "/api/v1/telemetry": {"get": _get("Completed 15-minute packets", {
            "type": "object", "properties": {"plant_hour": _num, "packets": {
                "type": "array", "items": _packet}}}, [_q("from_hour", _num), _q("to_hour", _num)])},
        "/api/v1/events": {"get": _get("The event log", {
            "type": "object", "properties": {"plant_hour": _num, "events": {
                "type": "array", "items": _event}}}, [_q("from_hour", _num)])},
        "/api/v1/raw": {"get": {
            "summary": "1-second samples of up to 8 tags over 30 minutes; 40 calls per run",
            "parameters": [_q("tags", _str, True), _q("start_hour", _num, True)],
            "responses": {**_ok({"type": "object", "properties": {
                "start_hour": _num, "samples": {"type": "object", "additionalProperties": {
                    "type": "array", "items": {"type": "array", "items": _num}}},
                "raw_quota_remaining": _int}}), "400": _err, "429": _err}}},
        "/api/v1/control": {"post": {
            "summary": "One control change",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "properties": {
                    "g1_mw": {"type": "number", "minimum": 0, "maximum": 3},
                    "g2_mw": {"type": "number", "minimum": 0, "maximum": 3},
                    "bat_mw": {"type": "number", "minimum": -2.6, "maximum": 2.6},
                    "pv_curtail": {"type": "number", "minimum": 0, "maximum": 1},
                    "shed": _strs}}}}},
            "responses": {**_ok({"type": "object", "properties": {
                "accepted": _bool, "reason": _str, "plant_hour": _num}}), "400": _err, "409": _err}}},
    },
}
